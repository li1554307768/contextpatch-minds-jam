"""Deterministic correction workflow and audit trail."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, cast

from app.db import Database
from app.minds import (
    MindsError,
    MindsPacket,
    MindsSendUncertain,
    MindsTransport,
    SendReceipt,
    VerifiedReply,
    build_recall_packet,
    build_store_packet,
    has_prompt_injection,
    parse_minds_response,
    sha256_text,
    stable_json,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def clean_text(value: str, field: str, maximum: int = 2_000) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError(f"{field} 不能为空")
    if len(cleaned) > maximum:
        raise ValueError(f"{field} 超过 {maximum} 字符")
    return cleaned


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def platform_patch_key(platform: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", platform.casefold())
    aliases = {"x": "x", "twitter": "x", "linkedin": "linkedin", "youtube": "youtube"}
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"不支持的更正平台：{platform}") from exc


class ContextPatchService:
    def __init__(self, database: Database):
        self.database = database
        self._send_lock = asyncio.Lock()

    def _audit(
        self,
        connection: sqlite3.Connection,
        action: str,
        entity_type: str,
        entity_id: str | int,
        details: dict[str, Any],
        *,
        actor: str = "local_human",
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_events(
                occurred_at, actor, action, entity_type, entity_id, details_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (utc_now(), actor, action, entity_type, str(entity_id), stable_json(details)),
        )

    def is_paused(self) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key='paused'"
            ).fetchone()
        return bool(row and row["value"] == "1")

    def set_paused(self, paused: bool) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE app_state SET value=? WHERE key='paused'", ("1" if paused else "0",)
            )
            self._audit(
                connection,
                "PAUSE_ENABLED" if paused else "PAUSE_DISABLED",
                "system",
                "global",
                {"paused": paused, "auto_publish": False},
            )
            connection.commit()

    def assert_not_paused(self) -> None:
        if self.is_paused():
            raise ValueError("ContextPatch 已暂停；新建和 Minds 发送都已锁定")

    def _acquire_send_lease(self, exchange_id: int) -> str:
        token = f"lease-{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc).timestamp()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM app_state WHERE key='minds_send_lease'"
            ).fetchone()
            if row is not None:
                try:
                    lease = json.loads(str(row["value"]))
                    expires_at = float(lease["expires_at"])
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError("Minds 全局发送租约损坏；已失败关闭") from exc
                if expires_at > now:
                    raise ValueError("Minds 全局发送通道正忙；本次未进入余额检查")
            connection.execute(
                """
                INSERT INTO app_state(key, value) VALUES ('minds_send_lease', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (
                    stable_json(
                        {
                            "token": token,
                            "exchange_id": exchange_id,
                            "expires_at": now + 120,
                        }
                    ),
                ),
            )
            connection.commit()
        return token

    def _release_send_lease(self, token: str) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM app_state WHERE key='minds_send_lease'"
            ).fetchone()
            if row is not None:
                try:
                    lease = json.loads(str(row["value"]))
                except json.JSONDecodeError:
                    connection.rollback()
                    return
                if isinstance(lease, dict) and lease.get("token") == token:
                    connection.execute("DELETE FROM app_state WHERE key='minds_send_lease'")
            connection.commit()

    def load_demo(self, path: Path) -> tuple[int, int]:
        self.assert_not_paused()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("无法读取合成演示数据") from exc
        if payload.get("dataset_label") != "SYNTHETIC_DEMO_ONLY":
            raise ValueError("演示数据必须明确标注 SYNTHETIC_DEMO_ONLY")
        source = payload.get("source")
        versions = payload.get("versions")
        if not isinstance(source, dict) or source.get("synthetic") is not True:
            raise ValueError("合成来源标记缺失")
        if not isinstance(versions, list) or not versions:
            raise ValueError("合成平台版本缺失")
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM sources WHERE title=? AND synthetic=1",
                (str(source.get("title", "")),),
            ).fetchone()
            if existing:
                source_id = int(existing["id"])
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO sources(title, body, synthetic, created_at)
                    VALUES (?, ?, 1, ?)
                    """,
                    (
                        clean_text(str(source.get("title", "")), "title", 300),
                        clean_text(str(source.get("body", "")), "body", 5_000),
                        utc_now(),
                    ),
                )
                source_id = int(cursor.lastrowid or 0)
            inserted = 0
            duplicates = 0
            for item in versions:
                if not isinstance(item, dict):
                    raise ValueError("合成版本格式无效")
                fact_keys = item.get("fact_keys")
                if not isinstance(fact_keys, list) or not all(
                    isinstance(value, str) for value in fact_keys
                ):
                    raise ValueError("合成版本 fact_keys 无效")
                try:
                    connection.execute(
                        """
                        INSERT INTO content_versions(
                            source_id, platform, external_ref, content,
                            fact_keys_json, synthetic, created_at
                        ) VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            source_id,
                            clean_text(str(item.get("platform", "")), "platform", 100),
                            clean_text(str(item.get("external_ref", "")), "external_ref", 200),
                            clean_text(str(item.get("content", "")), "content", 10_000),
                            stable_json({"keys": sorted(set(fact_keys))}),
                            utc_now(),
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    duplicates += 1
            self._audit(
                connection,
                "SYNTHETIC_DEMO_LOADED",
                "source",
                source_id,
                {"inserted_versions": inserted, "duplicates": duplicates, "synthetic": True},
            )
            connection.commit()
        return inserted, duplicates

    def list_sources(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT * FROM sources ORDER BY id DESC").fetchall()
        return [row_dict(row) for row in rows]

    def list_versions(self) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT v.*, s.title AS source_title
                FROM content_versions v JOIN sources s ON s.id=v.source_id
                ORDER BY v.id
                """
            ).fetchall()
        return [row_dict(row) for row in rows]

    def create_change(
        self,
        *,
        source_id: int,
        fact_key: str,
        old_fact: str,
        new_fact: str,
        disclosure_principle: str,
        due_at: str,
    ) -> int:
        self.assert_not_paused()
        safe_key = clean_text(fact_key, "fact_key", 100).casefold().replace(" ", "_")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,99}", safe_key):
            raise ValueError("fact_key 只能使用小写字母、数字、下划线和连字符")
        safe_old = clean_text(old_fact, "old_fact")
        safe_new = clean_text(new_fact, "new_fact")
        if normalize(safe_old) == normalize(safe_new):
            raise ValueError("新旧事实不能相同")
        safe_principle = clean_text(disclosure_principle, "disclosure_principle", 1_000)
        try:
            due = date.fromisoformat(due_at)
        except ValueError as exc:
            raise ValueError("due_at 必须是 YYYY-MM-DD") from exc
        memory_key = f"contextpatch:fact:{safe_key}:{uuid.uuid4().hex[:12]}"
        flagged = has_prompt_injection(safe_old, safe_new, safe_principle)
        with self.database.connect() as connection:
            source = connection.execute(
                "SELECT id FROM sources WHERE id=?", (source_id,)
            ).fetchone()
            if source is None:
                raise ValueError("来源内容不存在")
            cursor = connection.execute(
                """
                INSERT INTO fact_changes(
                    source_id, fact_key, old_fact, new_fact, disclosure_principle,
                    due_at, memory_key, injection_flagged, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL', ?)
                """,
                (
                    source_id,
                    safe_key,
                    safe_old,
                    safe_new,
                    safe_principle,
                    due.isoformat(),
                    memory_key,
                    int(flagged),
                    utc_now(),
                ),
            )
            change_id = int(cursor.lastrowid or 0)
            versions = connection.execute(
                "SELECT * FROM content_versions WHERE source_id=? ORDER BY id", (source_id,)
            ).fetchall()
            impact_count = 0
            for version in versions:
                declared = json.loads(str(version["fact_keys_json"]))["keys"]
                key_match = safe_key in declared
                text_match = normalize(safe_old) in normalize(str(version["content"]))
                if not key_match and not text_match:
                    continue
                reason_parts: list[str] = []
                if key_match:
                    reason_parts.append(f"版本声明依赖 fact_key={safe_key}")
                if text_match:
                    reason_parts.append("版本文本包含旧事实")
                reason = "；".join(reason_parts)
                connection.execute(
                    "INSERT INTO impacts(change_id, version_id, reason) VALUES (?, ?, ?)",
                    (change_id, int(version["id"]), reason),
                )
                why_now = (
                    f"更正期限为 {due.isoformat()}；{reason}。"
                    "应先人工核对，再决定是否在平台更正。"
                )
                connection.execute(
                    """
                    INSERT INTO correction_queue(
                        change_id, version_id, status, why_now, due_at
                    ) VALUES (?, ?, 'BLOCKED_PENDING_FACT_APPROVAL', ?, ?)
                    """,
                    (change_id, int(version["id"]), why_now, due.isoformat()),
                )
                impact_count += 1
            self._audit(
                connection,
                "FACT_CHANGE_RECORDED",
                "fact_change",
                change_id,
                {
                    "fact_key": safe_key,
                    "impact_count": impact_count,
                    "injection_flagged": flagged,
                    "status": "PENDING_APPROVAL",
                },
            )
            connection.commit()
        return change_id

    def _create_exchange(
        self, connection: sqlite3.Connection, change: sqlite3.Row, packet: MindsPacket
    ) -> int:
        existing = connection.execute(
            "SELECT id FROM minds_exchanges WHERE semantic_hash=?", (packet.semantic_hash,)
        ).fetchone()
        if existing:
            return int(existing["id"])
        alias_prefix = "cp-memory" if packet.operation == "store_principle" else "cp-recall"
        alias = f"{alias_prefix}-{packet.request_id[-12:]}"
        cursor = connection.execute(
            """
            INSERT INTO minds_exchanges(
                change_id, operation, request_id, memory_key, session_alias,
                request_body, request_hash, semantic_hash, expected_platforms_json,
                injection_flagged,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PREPARED', ?)
            """,
            (
                int(change["id"]),
                packet.operation,
                packet.request_id,
                packet.memory_key,
                alias,
                packet.body,
                packet.request_hash,
                packet.semantic_hash,
                stable_json({"platforms": list(packet.expected_platforms)}),
                int(packet.injection_flagged),
                utc_now(),
            ),
        )
        exchange_id = int(cursor.lastrowid or 0)
        self._audit(
            connection,
            "MINDS_REQUEST_PREPARED",
            "minds_exchange",
            exchange_id,
            {
                "operation": packet.operation,
                "semantic_hash": packet.semantic_hash,
                "new_session": True,
                "sent": False,
            },
            actor="system",
        )
        return exchange_id

    def approve_change(self, change_id: int) -> int:
        self.assert_not_paused()
        with self.database.connect() as connection:
            change = connection.execute(
                "SELECT * FROM fact_changes WHERE id=?", (change_id,)
            ).fetchone()
            if change is None or change["status"] != "PENDING_APPROVAL":
                raise ValueError("事实变更不存在或已决策")
            connection.execute(
                "UPDATE fact_changes SET status='APPROVED', decided_at=? WHERE id=?",
                (utc_now(), change_id),
            )
            connection.execute(
                """
                UPDATE correction_queue SET status='PENDING_REVIEW'
                WHERE change_id=? AND status='BLOCKED_PENDING_FACT_APPROVAL'
                """,
                (change_id,),
            )
            packet = build_store_packet(
                str(change["memory_key"]),
                fact_key=str(change["fact_key"]),
                old_fact=str(change["old_fact"]),
                new_fact=str(change["new_fact"]),
                disclosure_principle=str(change["disclosure_principle"]),
            )
            exchange_id = self._create_exchange(connection, change, packet)
            self._audit(
                connection,
                "FACT_CHANGE_APPROVED",
                "fact_change",
                change_id,
                {"memory_write_exchange_id": exchange_id, "auto_publish": False},
            )
            connection.commit()
        return exchange_id

    def reject_change(self, change_id: int) -> None:
        self.assert_not_paused()
        with self.database.connect() as connection:
            changed = connection.execute(
                """
                UPDATE fact_changes SET status='REJECTED', decided_at=?
                WHERE id=? AND status='PENDING_APPROVAL'
                """,
                (utc_now(), change_id),
            ).rowcount
            if changed != 1:
                raise ValueError("事实变更不存在或已决策")
            connection.execute(
                "UPDATE correction_queue SET status='CANCELLED' WHERE change_id=?",
                (change_id,),
            )
            self._audit(
                connection, "FACT_CHANGE_REJECTED", "fact_change", change_id, {"sent": False}
            )
            connection.commit()

    def _packet_from_exchange(self, exchange: sqlite3.Row) -> MindsPacket:
        operation = cast(
            Any,
            str(exchange["operation"]),
        )
        expected_payload = json.loads(str(exchange["expected_platforms_json"]))
        expected_values = expected_payload.get("platforms", [])
        if not isinstance(expected_values, list) or not all(
            isinstance(value, str) for value in expected_values
        ):
            raise ValueError("Minds 预期平台证据格式无效")
        return MindsPacket(
            request_id=str(exchange["request_id"]),
            operation=operation,
            memory_key=str(exchange["memory_key"]),
            body=str(exchange["request_body"]),
            request_hash=str(exchange["request_hash"]),
            semantic_hash=str(exchange["semantic_hash"]),
            injection_flagged=bool(exchange["injection_flagged"]),
            expected_platforms=tuple(expected_values),
        )

    def _accept_verified_minds_response(
        self, exchange_id: int, reply: VerifiedReply
    ) -> int | None:
        """Persist transport evidence first, then parse and advance the workflow."""
        with self.database.connect() as connection:
            exchange = connection.execute(
                "SELECT * FROM minds_exchanges WHERE id=?", (exchange_id,)
            ).fetchone()
            if exchange is None or exchange["status"] not in {"SENT", "UNCERTAIN"}:
                raise ValueError("只接受已发送且运输可核验的 Minds 回复")
            if (
                not exchange["remote_conversation_id"]
                or reply.conversation_id != exchange["remote_conversation_id"]
            ):
                raise ValueError("Minds 回复与已知会话不匹配")
            if reply.outbound_request_hash != str(exchange["request_hash"]):
                raise ValueError("Minds 历史中的出站原文哈希不匹配")
            raw_hash = sha256_text(reply.raw_text)
            clean_hash = sha256_text(reply.clean_text)
            connection.execute(
                """
                UPDATE minds_exchanges SET remote_reply_id=?, raw_response_hash=?,
                    clean_response_hash=?, history_request_hash=?, request_created_at=?,
                    reply_created_at=?, timestamp_order_verified=?,
                    timestamp_evidence_limitation=?
                WHERE id=?
                """,
                (
                    reply.reply_id,
                    raw_hash,
                    clean_hash,
                    reply.outbound_request_hash,
                    reply.request_created_at,
                    reply.reply_created_at,
                    int(reply.timestamp_order_verified),
                    reply.timestamp_evidence_limitation,
                    exchange_id,
                ),
            )
            self._audit(
                connection,
                "MINDS_TRANSPORT_VERIFIED",
                "minds_exchange",
                exchange_id,
                {
                    "raw_response_hash": raw_hash,
                    "clean_response_hash": clean_hash,
                    "history_request_hash": reply.outbound_request_hash,
                    "request_created_at": reply.request_created_at,
                    "reply_created_at": reply.reply_created_at,
                    "timestamp_order_verified": reply.timestamp_order_verified,
                    "timestamp_evidence_limitation": reply.timestamp_evidence_limitation,
                },
                actor="system",
            )
            connection.commit()

        # Parsing happens only after the immutable transport hashes and timestamps are durable.
        with self.database.connect() as connection:
            exchange = connection.execute(
                "SELECT * FROM minds_exchanges WHERE id=?", (exchange_id,)
            ).fetchone()
            if exchange is None:
                raise ValueError("Minds 请求不存在")
            packet = self._packet_from_exchange(exchange)
            parsed = parse_minds_response(packet, reply.clean_text, transport_verified=True)
            response_json = stable_json(parsed)
            response_hash = sha256_text(response_json)
            duplicate = connection.execute(
                "SELECT id FROM minds_exchanges WHERE response_hash=? AND id!=?",
                (response_hash, exchange_id),
            ).fetchone()
            if duplicate:
                raise ValueError("该 Minds 响应已绑定到其他请求")
            change = connection.execute(
                "SELECT * FROM fact_changes WHERE id=?", (int(exchange["change_id"]),)
            ).fetchone()
            if change is None:
                raise ValueError("事实变更不存在")
            if exchange["operation"] == "recall_and_draft":
                recalled = parsed.get("recalled_principle")
                approved_principle = str(change["disclosure_principle"])
                if not isinstance(recalled, str) or normalize(recalled) != normalize(
                    approved_principle
                ):
                    raise ValueError(
                        "Minds 召回原则与人工批准原则不精确匹配；已拒绝草稿"
                    )
            next_exchange_id: int | None = None
            if exchange["operation"] == "store_principle":
                affected = connection.execute(
                    """
                    SELECT v.platform, v.content, v.synthetic
                    FROM correction_queue q
                    JOIN content_versions v ON v.id=q.version_id
                    WHERE q.change_id=? AND q.status='PENDING_REVIEW'
                    ORDER BY q.id
                    """,
                    (int(change["id"]),),
                ).fetchall()
                if affected:
                    packet = build_recall_packet(
                        str(change["memory_key"]),
                        fact_key=str(change["fact_key"]),
                        old_fact=str(change["old_fact"]),
                        new_fact=str(change["new_fact"]),
                        affected_versions=[
                            {
                                "platform": str(item["platform"]),
                                "content": str(item["content"]),
                                "synthetic": bool(item["synthetic"]),
                            }
                            for item in affected
                        ],
                    )
                    next_exchange_id = self._create_exchange(connection, change, packet)
            else:
                patches = parsed["platform_patches"]
                if not isinstance(patches, dict):
                    raise ValueError("Minds 平台更正对象格式无效")
                targets = connection.execute(
                    """
                    SELECT q.id, v.platform FROM correction_queue q
                    JOIN content_versions v ON v.id=q.version_id
                    WHERE q.change_id=? AND q.status='PENDING_REVIEW'
                    """,
                    (int(change["id"]),),
                ).fetchall()
                assignments: list[tuple[str, str, int]] = []
                for target in targets:
                    patch_key = platform_patch_key(str(target["platform"]))
                    patch = patches.get(patch_key)
                    if not isinstance(patch, str) or not patch.strip():
                        raise ValueError(f"Minds 响应缺少 {patch_key} 平台草稿")
                    assignments.append((patch, str(parsed["why_now"]), int(target["id"])))
                connection.executemany(
                    "UPDATE correction_queue SET draft=?, why_now=? WHERE id=?",
                    assignments,
                )
            connection.execute(
                """
                UPDATE minds_exchanges
                SET status='COMPLETED', response_json=?, response_hash=?, completed_at=?
                WHERE id=?
                """,
                (response_json, response_hash, utc_now(), exchange_id),
            )
            self._audit(
                connection,
                "MINDS_RESPONSE_ACCEPTED",
                "minds_exchange",
                exchange_id,
                {
                    "operation": str(exchange["operation"]),
                    "response_hash": response_hash,
                    "next_exchange_id": next_exchange_id,
                },
                actor="system",
            )
            connection.commit()
        return next_exchange_id

    async def send_exchange(
        self, exchange_id: int, transport: MindsTransport, *, credit_floor: float
    ) -> SendReceipt:
        self.assert_not_paused()
        if credit_floor < 10:
            raise ValueError("余额安全阈值不能低于 10")
        async with self._send_lock:
            self.assert_not_paused()
            lease_token = self._acquire_send_lease(exchange_id)
            try:
                return await self._send_exchange_locked(
                    exchange_id, transport, credit_floor=credit_floor
                )
            finally:
                self._release_send_lease(lease_token)

    async def _send_exchange_locked(
        self, exchange_id: int, transport: MindsTransport, *, credit_floor: float
    ) -> SendReceipt:
        with self.database.connect() as connection:
            exchange = connection.execute(
                "SELECT * FROM minds_exchanges WHERE id=?", (exchange_id,)
            ).fetchone()
            if exchange is None:
                raise ValueError("Minds 请求不存在")
            claimed = connection.execute(
                """
                UPDATE minds_exchanges SET status='SENDING'
                WHERE id=? AND status='PREPARED'
                """,
                (exchange_id,),
            ).rowcount
            if claimed != 1:
                raise ValueError("请求不存在或已发送；禁止重发")
            connection.commit()
        try:
            credits = await transport.get_credits()
        except Exception:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE minds_exchanges SET status='PREPARED' WHERE id=? AND status='SENDING'",
                    (exchange_id,),
                )
                connection.commit()
            raise
        if credits <= 10 or credits <= credit_floor:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE minds_exchanges SET status='PREPARED' WHERE id=? AND status='SENDING'",
                    (exchange_id,),
                )
                connection.commit()
            raise ValueError(f"Minds 余额 {credits:.2f} 已达安全线，停止发送")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE minds_exchanges SET credits_before=? WHERE id=?", (credits, exchange_id)
            )
            connection.commit()
        try:
            receipt = await transport.send_message(
                str(exchange["session_alias"]), str(exchange["request_body"])
            )
        except MindsError as exc:
            with self.database.connect() as connection:
                conversation_id = (
                    exc.conversation_id if isinstance(exc, MindsSendUncertain) else None
                )
                connection.execute(
                    """
                    UPDATE minds_exchanges SET status=?, remote_conversation_id=COALESCE(?,
                        remote_conversation_id) WHERE id=?
                    """,
                    (
                        "UNCERTAIN" if exc.uncertain else "REJECTED",
                        conversation_id,
                        exchange_id,
                    ),
                )
                self._audit(
                    connection,
                    "MINDS_SEND_UNCERTAIN" if exc.uncertain else "MINDS_SEND_REJECTED",
                    "minds_exchange",
                    exchange_id,
                    {"blind_retry_allowed": False},
                    actor="system",
                )
                connection.commit()
            raise
        if receipt.request_hash != str(exchange["request_hash"]):
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE minds_exchanges SET status='UNCERTAIN', remote_conversation_id=?,
                        remote_message_id=? WHERE id=?
                    """,
                    (receipt.conversation_id, receipt.message_id, exchange_id),
                )
                self._audit(
                    connection,
                    "MINDS_RECEIPT_HASH_MISMATCH",
                    "minds_exchange",
                    exchange_id,
                    {"blind_retry_allowed": False},
                    actor="system",
                )
                connection.commit()
            raise ValueError("Minds 运输回执的请求哈希不匹配")
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE minds_exchanges SET status='SENT', remote_conversation_id=?,
                    remote_message_id=? WHERE id=?
                """,
                (receipt.conversation_id, receipt.message_id, exchange_id),
            )
            self._audit(
                connection,
                "MINDS_REQUEST_SENT",
                "minds_exchange",
                exchange_id,
                {"credits_before": credits, "auto_publish": False},
                actor="system",
            )
            connection.commit()
        return receipt

    async def sync_exchange(self, exchange_id: int, transport: MindsTransport) -> bool:
        with self.database.connect() as connection:
            exchange = connection.execute(
                "SELECT * FROM minds_exchanges WHERE id=?", (exchange_id,)
            ).fetchone()
        if exchange is None or exchange["status"] not in {"SENT", "UNCERTAIN"}:
            raise ValueError("只能查询已发送或结果未知的请求")
        if not exchange["remote_conversation_id"]:
            raise ValueError("结果未知且缺少会话证据；不得盲目重发")
        receipt = SendReceipt(
            str(exchange["session_alias"]),
            str(exchange["remote_conversation_id"]),
            str(exchange["remote_message_id"] or ""),
            str(exchange["request_hash"]),
        )
        reply = await transport.find_reply(
            receipt, str(exchange["request_id"]), str(exchange["request_hash"])
        )
        if reply is None:
            return False
        self._accept_verified_minds_response(exchange_id, reply)
        return True

    def decide_correction(self, queue_id: int, approved: bool) -> None:
        self.assert_not_paused()
        desired = "APPROVED" if approved else "REJECTED"
        with self.database.connect() as connection:
            queue = connection.execute(
                "SELECT * FROM correction_queue WHERE id=?", (queue_id,)
            ).fetchone()
            if queue is None or queue["status"] != "PENDING_REVIEW":
                raise ValueError("更正项不存在或已决策")
            if approved and not queue["draft"]:
                raise ValueError("尚无严格校验的 Minds 草稿，不能批准")
            connection.execute(
                "UPDATE correction_queue SET status=?, decided_at=? WHERE id=?",
                (desired, utc_now(), queue_id),
            )
            self._audit(
                connection,
                f"CORRECTION_{desired}",
                "correction_queue",
                queue_id,
                {"auto_published": False, "manual_platform_action_required": approved},
            )
            connection.commit()

    def mark_follow_up(self, queue_id: int) -> None:
        self.assert_not_paused()
        with self.database.connect() as connection:
            queue = connection.execute(
                "SELECT * FROM correction_queue WHERE id=?", (queue_id,)
            ).fetchone()
            if queue is None or queue["status"] != "PENDING_REVIEW":
                raise ValueError("只能跟进待审核更正")
            connection.execute(
                """
                UPDATE correction_queue
                SET follow_up_count=follow_up_count+1, last_follow_up_at=? WHERE id=?
                """,
                (utc_now(), queue_id),
            )
            self._audit(
                connection,
                "WHY_NOW_FOLLOW_UP_RECORDED",
                "correction_queue",
                queue_id,
                {"why_now": str(queue["why_now"]), "external_message_sent": False},
            )
            connection.commit()

    def dashboard(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            changes = [
                row_dict(row)
                for row in connection.execute(
                    """
                    SELECT c.*, COUNT(i.id) AS impact_count
                    FROM fact_changes c LEFT JOIN impacts i ON i.change_id=c.id
                    GROUP BY c.id ORDER BY c.id DESC
                    """
                ).fetchall()
            ]
            queue = [
                row_dict(row)
                for row in connection.execute(
                    """
                    SELECT q.*, v.platform, v.external_ref, v.content,
                           c.fact_key, c.old_fact, c.new_fact
                    FROM correction_queue q
                    JOIN content_versions v ON v.id=q.version_id
                    JOIN fact_changes c ON c.id=q.change_id
                    ORDER BY q.due_at, q.id
                    """
                ).fetchall()
            ]
            exchanges = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM minds_exchanges ORDER BY id DESC"
                ).fetchall()
            ]
            audits = [
                row_dict(row)
                for row in connection.execute(
                    "SELECT * FROM audit_events ORDER BY id DESC LIMIT 40"
                ).fetchall()
            ]
        today = date.today().isoformat()
        for item in queue:
            item["overdue"] = item["status"] == "PENDING_REVIEW" and item["due_at"] <= today
        for exchange in exchanges:
            exchange["recalled_principle"] = None
            response_json = exchange.get("response_json")
            if isinstance(response_json, str) and response_json:
                try:
                    response = json.loads(response_json)
                except json.JSONDecodeError:
                    continue
                if isinstance(response, dict) and isinstance(
                    response.get("recalled_principle"), str
                ):
                    exchange["recalled_principle"] = response["recalled_principle"]
        return {
            "paused": self.is_paused(),
            "auto_publish": False,
            "sources": self.list_sources(),
            "versions": self.list_versions(),
            "changes": changes,
            "queue": queue,
            "exchanges": exchanges,
            "audits": audits,
        }
