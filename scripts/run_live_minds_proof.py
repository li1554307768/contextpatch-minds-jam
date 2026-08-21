"""Run a fresh three-call proof or safely resume its redacted checkpoint.

The explicit modes are mutually exclusive. Recovery never resends an attempted
stage, and neither mode prints or persists keys, UUIDs, aliases, remote IDs,
request bodies, or raw replies.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.minds import (
    MindsBuilderTransport,
    MindsError,
    MindsPacket,
    MindsSendUncertain,
    SendReceipt,
    VerifiedReply,
    build_recall_packet,
    build_store_packet,
    parse_minds_response,
    reconstruct_packet_from_outbound,
    sha256_text,
)

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_PATH = ROOT / "output" / "live_minds_evidence.json"
CHECKPOINT_PATH = ROOT / "output" / "live_minds_transport_checkpoint.json"
RUN_LOCK_PATH = ROOT / "output" / "live_minds_proof.lock.json"
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SENTINEL_PATTERN = re.compile(r"\bcp-continuity-[0-9a-f]{24}\b")


@dataclass(frozen=True)
class RecoveredStore:
    packet: MindsPacket
    request_data: dict[str, Any]
    parsed_response: dict[str, Any]
    alias: str
    conversation_id: str
    outbound_message_id: str
    reply: VerifiedReply
    checkpoint: dict[str, Any]


def hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def random_alias(label: str) -> str:
    return f"cp-{label}-{secrets.token_hex(6)}"


@contextmanager
def live_run_lock(path: Path | None = None) -> Iterator[None]:
    """Hold one non-blocking process-wide live-proof lease on macOS/Linux."""
    lock_path = path or RUN_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MindsError("另一个 live proof 进程正在运行；本进程立即停止") from exc
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def read_checkpoint_entries(
    path: Path | None = None, *, allow_missing: bool = False
) -> list[dict[str, Any]]:
    checkpoint_path = path or CHECKPOINT_PATH
    if not checkpoint_path.is_file():
        if allow_missing:
            return []
        raise MindsError("找不到脱敏运输检查点")
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MindsError("脱敏运输检查点无法解析") from exc
    if not isinstance(payload, list) or not payload or not all(
        isinstance(item, dict) for item in payload
    ):
        raise MindsError("脱敏运输检查点必须是非空 JSON 对象列表")
    forbidden = {
        "alias",
        "conversation_id",
        "message_id",
        "reply_id",
        "request_body",
        "raw_response",
        "api_key",
        "mind_id",
    }
    normalized: list[dict[str, Any]] = []
    seen_stages: set[str] = set()
    for index, raw_item in enumerate(payload):
        item = dict(raw_item)
        if forbidden.intersection(item):
            raise MindsError("检查点含不允许持久化的原始标识或正文")
        # The first real run predated staged checkpoints; normalize that one store entry.
        if "stage" not in item and index == 0 and item.get("operation") == "store_principle":
            item["stage"] = "store"
            item["status"] = "VERIFIED"
        stage = item.get("stage")
        if stage not in {"store", "recall_a", "recall_b"} or stage in seen_stages:
            raise MindsError("检查点阶段缺失、重复或无效")
        seen_stages.add(stage)
        expected_operation = "store_principle" if stage == "store" else "recall_and_draft"
        if item.get("operation") != expected_operation:
            raise MindsError("检查点阶段与 operation 不匹配")
        if item.get("status") not in {
            "SEND_ATTEMPT_STARTED",
            "SENT",
            "UNCERTAIN",
            "TRANSPORT_VERIFIED",
            "VERIFIED",
            "REJECTED",
        }:
            raise MindsError("检查点发送状态无效")
        request_hash = item.get("request_hash")
        if not isinstance(request_hash, str) or not HASH_PATTERN.fullmatch(request_hash):
            raise MindsError("检查点 request_hash 缺失或非 SHA-256")
        for field, value in item.items():
            if field.endswith("_hash") and value is not None:
                if not isinstance(value, str) or not HASH_PATTERN.fullmatch(value):
                    raise MindsError(f"检查点 {field} 非 SHA-256")
        if item.get("history_request_hash") not in {None, request_hash}:
            raise MindsError("检查点出站原文哈希内部不一致")
        normalized.append(item)
    stage_order = [str(item["stage"]) for item in normalized]
    if stage_order != ["store", "recall_a", "recall_b"][: len(stage_order)]:
        raise MindsError("检查点阶段顺序无效")
    return normalized


def write_checkpoint_entries(entries: list[dict[str, Any]], path: Path | None = None) -> None:
    checkpoint_path = path or CHECKPOINT_PATH
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = checkpoint_path.with_name(
        f".{checkpoint_path.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, checkpoint_path)


def checkpoint_for_stage(entries: list[dict[str, Any]], stage: str) -> dict[str, Any] | None:
    matches = [item for item in entries if item.get("stage") == stage]
    if len(matches) > 1:
        raise MindsError("检查点包含重复阶段")
    return matches[0] if matches else None


def begin_send_attempt(stage: str, packet: MindsPacket, alias: str, credits: float) -> None:
    entries = read_checkpoint_entries(allow_missing=True)
    if checkpoint_for_stage(entries, stage) is not None:
        raise MindsError(f"{stage} 已有发送尝试；禁止重发")
    entries.append(
        {
            "stage": stage,
            "operation": packet.operation,
            "status": "SEND_ATTEMPT_STARTED",
            "request_hash": packet.request_hash,
            "semantic_hash": packet.semantic_hash,
            "alias_hash": hash_identifier(alias),
            "credits_before": credits,
            "attempt_started_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }
    )
    write_checkpoint_entries(entries)


def update_send_attempt(stage: str, **updates: Any) -> dict[str, Any]:
    entries = read_checkpoint_entries()
    entry = checkpoint_for_stage(entries, stage)
    if entry is None:
        raise MindsError(f"{stage} 检查点不存在")
    entry.update(updates)
    write_checkpoint_entries(entries)
    return entry


def repair_final_evidence_from_checkpoint(
    evidence_path: Path | None = None,
    checkpoint_path: Path | None = None,
) -> int:
    """Fill only missing history-request hashes from a fully verified checkpoint."""
    final_path = evidence_path or EVIDENCE_PATH
    entries = read_checkpoint_entries(checkpoint_path)
    try:
        evidence = json.loads(final_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MindsError("最终证据无法解析") from exc
    calls = evidence.get("calls") if isinstance(evidence, dict) else None
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema_version") != "1.0"
        or evidence.get("continuity_verified") is not True
        or not isinstance(calls, list)
        or len(calls) != 3
        or len(entries) != 3
        or not all(isinstance(call, dict) for call in calls)
    ):
        raise MindsError("最终证据不是可修复的三调用连续性证据")

    expected_stages = ("store", "recall_a", "recall_b")
    binding_fields = (
        "operation",
        "request_hash",
        "semantic_hash",
        "conversation_hash",
        "remote_request_hash",
        "remote_reply_hash",
        "raw_response_hash",
        "clean_response_hash",
        "response_hash",
    )
    repaired = 0
    for stage, entry, call in zip(expected_stages, entries, calls, strict=True):
        if entry.get("stage") != stage or entry.get("status") != "VERIFIED":
            raise MindsError("检查点三阶段未全部 VERIFIED")
        for field in binding_fields:
            if entry.get(field) != call.get(field):
                raise MindsError(f"最终证据 {stage} 的 {field} 与检查点不匹配")
        history_hash = entry.get("history_request_hash")
        if history_hash != entry.get("request_hash"):
            raise MindsError(f"检查点 {stage} 未证明官方历史出站原文匹配")
        existing = call.get("history_request_hash")
        if existing is not None and existing != history_hash:
            raise MindsError(f"最终证据 {stage} 已有冲突的历史请求哈希")
        if existing is None:
            call["history_request_hash"] = history_hash
            repaired += 1

    if repaired:
        temporary = final_path.with_name(f".{final_path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, final_path)
    return repaired


def load_recovery_checkpoint(path: Path | None = None) -> dict[str, Any]:
    entries = read_checkpoint_entries(path)
    store = checkpoint_for_stage(entries, "store")
    if store is None:
        raise MindsError("恢复检查点缺少 store 阶段")
    return store


def _identifier_values(item: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    return tuple(values)


def _conversation_ids(item: dict[str, Any]) -> tuple[str, ...]:
    return _identifier_values(item, ("conversationId", "conversation_id", "id"))


def _message_ids(item: dict[str, Any]) -> tuple[str, ...]:
    # `messageId` is canonical. Builder may also return a different database
    # row `id`; it is a fallback, not an ambiguous second message identifier.
    for key in ("messageId", "id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return (value,)
    return ()


def _matching_hashed_identifier(values: tuple[str, ...], expected_hash: str) -> str | None:
    matches = [value for value in values if hash_identifier(value) == expected_hash]
    return matches[0] if len(matches) == 1 else None


async def recover_checkpoint_exchange(
    transport: MindsBuilderTransport,
    checkpoint: dict[str, Any],
    mind_id: str,
) -> RecoveredStore:
    if checkpoint.get("status") == "REJECTED":
        raise MindsError("该阶段已被明确拒绝；自动恢复不会重发")
    conversations = await transport.list_conversations()
    candidates: list[tuple[str, str]] = []
    for item in conversations:
        alias = item.get("alias")
        if not isinstance(alias, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", alias):
            continue
        alias_hash = checkpoint.get("alias_hash")
        if isinstance(alias_hash, str) and hash_identifier(alias) != alias_hash:
            continue
        item_mind_id = item.get("mindId", item.get("mind_id"))
        if isinstance(item_mind_id, str) and item_mind_id != mind_id:
            continue
        ids = _conversation_ids(item)
        conversation_hash = checkpoint.get("conversation_hash")
        if isinstance(conversation_hash, str):
            conversation_id = _matching_hashed_identifier(ids, conversation_hash)
        else:
            conversation_id = ids[0] if len(ids) == 1 else None
        if conversation_id is not None and (
            isinstance(alias_hash, str) or isinstance(conversation_hash, str)
        ):
            candidates.append((alias, conversation_id))
    if len(candidates) != 1:
        raise MindsError("会话列表中未找到唯一脱敏检查点匹配")
    alias, conversation_id = candidates[0]

    details = await transport.get_conversation_read_only(alias)
    detail_ids = _conversation_ids(details)
    conversation_hash = checkpoint.get("conversation_hash")
    detail_id = (
        _matching_hashed_identifier(detail_ids, conversation_hash)
        if isinstance(conversation_hash, str)
        else (detail_ids[0] if len(detail_ids) == 1 else None)
    )
    if detail_id != conversation_id:
        raise MindsError("会话详情与脱敏检查点不匹配")

    history = await transport.get_history_read_only(alias)
    outbound_matches: list[dict[str, Any]] = []
    for item in history:
        raw_text = item.get("messageText")
        if item.get("senderType") != 1 or not isinstance(raw_text, str):
            continue
        if sha256_text(raw_text) != checkpoint["request_hash"]:
            continue
        conversation_values = _identifier_values(item, ("conversationId", "conversation_id"))
        if conversation_values and conversation_id not in conversation_values:
            continue
        outbound_matches.append(item)
    if len(outbound_matches) != 1:
        raise MindsError("官方历史中未找到唯一出站原文哈希匹配")
    outbound = outbound_matches[0]
    outbound_text = str(outbound["messageText"])
    outbound_ids = _message_ids(outbound)
    if len(outbound_ids) != 1:
        raise MindsError("恢复出站消息缺少唯一官方 ID")
    packet, request_data = reconstruct_packet_from_outbound(
        outbound_text, str(checkpoint["request_hash"])
    )
    if packet.operation != checkpoint.get("operation"):
        raise MindsError("恢复出站请求 operation 与检查点不匹配")
    semantic_hash = checkpoint.get("semantic_hash")
    if isinstance(semantic_hash, str) and packet.semantic_hash != semantic_hash:
        raise MindsError("恢复出站请求语义哈希不匹配")
    remote_request_hash = checkpoint.get("remote_request_hash")
    if isinstance(remote_request_hash, str) and hash_identifier(
        outbound_ids[0]
    ) != remote_request_hash:
        raise MindsError("恢复出站官方 ID 哈希不匹配")
    receipt = SendReceipt(
        alias,
        conversation_id,
        outbound_ids[0],
        str(checkpoint["request_hash"]),
    )
    reply = await transport.find_reply(receipt, packet.request_id, packet.request_hash)
    if reply is None:
        raise MindsError("官方历史未找到严格顺序窗口内的 store 回复")
    if isinstance(checkpoint.get("remote_reply_hash"), str) and hash_identifier(
        reply.reply_id
    ) != checkpoint["remote_reply_hash"]:
        raise MindsError("store 回复 ID 哈希与检查点不匹配")
    if isinstance(checkpoint.get("raw_response_hash"), str) and sha256_text(
        reply.raw_text
    ) != checkpoint["raw_response_hash"]:
        raise MindsError("store 回复原文哈希与检查点不匹配")
    if isinstance(checkpoint.get("clean_response_hash"), str) and sha256_text(
        reply.clean_text
    ) != checkpoint["clean_response_hash"]:
        raise MindsError("store 回复清理文本哈希与检查点不匹配")
    if isinstance(checkpoint.get("history_request_hash"), str) and (
        reply.outbound_request_hash != checkpoint["history_request_hash"]
    ):
        raise MindsError("store 官方历史出站哈希与检查点不匹配")
    for field, actual in (
        ("request_created_at", reply.request_created_at),
        ("reply_created_at", reply.reply_created_at),
    ):
        expected = checkpoint.get(field)
        if expected is not None and expected != actual:
            raise MindsError(f"store {field} 与检查点不匹配")
    parsed = parse_minds_response(packet, reply.clean_text, transport_verified=True)
    return RecoveredStore(
        packet=packet,
        request_data=request_data,
        parsed_response=parsed,
        alias=alias,
        conversation_id=conversation_id,
        outbound_message_id=outbound_ids[0],
        reply=reply,
        checkpoint=checkpoint,
    )


async def recover_store_from_official_history(
    transport: MindsBuilderTransport,
    checkpoint: dict[str, Any],
    mind_id: str,
) -> RecoveredStore:
    recovered = await recover_checkpoint_exchange(transport, checkpoint, mind_id)
    if recovered.packet.operation != "store_principle":
        raise MindsError("恢复出站请求不是 store_principle")
    if recovered.parsed_response.get("stored") is not True:
        raise MindsError("store 官方回复未确认 stored=true")
    return recovered


def load_synthetic_affected_versions() -> list[dict[str, Any]]:
    path = ROOT / "data" / "synthetic_demo.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MindsError("无法读取本地合成版本") from exc
    if not isinstance(payload, dict):
        raise MindsError("本地合成数据必须是 JSON 对象")
    versions = payload.get("versions")
    if payload.get("dataset_label") != "SYNTHETIC_DEMO_ONLY" or not isinstance(versions, list):
        raise MindsError("本地版本不是明确标注的合成数据")
    result: list[dict[str, Any]] = []
    for item in versions:
        if not isinstance(item, dict):
            raise MindsError("合成版本格式无效")
        result.append(
            {
                "platform": item.get("platform"),
                "content": item.get("content"),
                "synthetic": True,
            }
        )
    if len(result) != 3:
        raise MindsError("恢复证据需要恰好三个合成平台版本")
    return result


def build_fresh_proof_packets() -> tuple[str, str, MindsPacket, list[MindsPacket]]:
    memory_key = f"contextpatch:fact:launch_date:{secrets.token_hex(6)}"
    sentinel = f"cp-continuity-{secrets.token_hex(12)}"
    principle = (
        "State the correction plainly, preserve the original context, and do not hide "
        f"the prior error. Continuity marker: {sentinel}."
    )
    affected_versions = load_synthetic_affected_versions()
    store = build_store_packet(
        memory_key,
        fact_key="launch_date",
        old_fact="September 30",
        new_fact="October 7",
        disclosure_principle=principle,
    )
    recalls = [
        build_recall_packet(
            memory_key,
            fact_key="launch_date",
            old_fact="September 30",
            new_fact="October 7",
            affected_versions=affected_versions,
        ),
        build_recall_packet(
            memory_key,
            fact_key="price",
            old_fact="$149",
            new_fact="$129",
            affected_versions=affected_versions,
        ),
    ]
    return principle, sentinel, store, recalls


def build_pending_recall_packets(
    recovered: RecoveredStore,
) -> tuple[str, str, list[MindsPacket]]:
    data = recovered.request_data
    allowed_data_keys = {
        frozenset({"fact_change", "approved_disclosure_principle"}),
        frozenset(
            {"fact_change", "approved_disclosure_principle", "expected_response_keys"}
        ),
    }
    if frozenset(data) not in allowed_data_keys:
        raise MindsError("store 自包含 data 字段不在受控兼容集合")
    fact_change = data.get("fact_change")
    principle = data.get("approved_disclosure_principle")
    if not isinstance(fact_change, dict) or set(fact_change) != {
        "fact_key",
        "old_fact",
        "new_fact",
    }:
        raise MindsError("store fact_change 格式无效")
    if not all(isinstance(fact_change.get(key), str) for key in fact_change):
        raise MindsError("store fact_change 必须全部是文本")
    if not isinstance(principle, str) or not principle.strip():
        raise MindsError("store 缺少已批准披露原则")
    sentinels = SENTINEL_PATTERN.findall(principle)
    if len(sentinels) != 1:
        raise MindsError("store 已批准原则缺少唯一不可猜测连续性标记")
    if (
        fact_change["fact_key"] != "launch_date"
        or fact_change["old_fact"] != "September 30"
        or fact_change["new_fact"] != "October 7"
    ):
        raise MindsError("检查点 store 不是预期的合成 launch_date 变更")
    affected_versions = load_synthetic_affected_versions()
    packets = [
        build_recall_packet(
            recovered.packet.memory_key,
            fact_key="launch_date",
            old_fact="September 30",
            new_fact="October 7",
            affected_versions=affected_versions,
        ),
        build_recall_packet(
            recovered.packet.memory_key,
            fact_key="price",
            old_fact="$149",
            new_fact="$129",
            affected_versions=affected_versions,
        ),
    ]
    if any(packet.operation != "recall_and_draft" for packet in packets):
        raise MindsError("恢复模式只允许构建尚未发送的 recall")
    return principle, sentinels[0], packets


async def wait_for_reply(
    transport: MindsBuilderTransport,
    receipt: SendReceipt,
    packet: MindsPacket,
    stage: str,
    *,
    attempts: int = 24,
    interval_seconds: float = 5.0,
) -> tuple[dict[str, Any], VerifiedReply, dict[str, Any]]:
    """Poll history only. Never resend after the single send call."""
    for attempt in range(attempts):
        reply = await transport.find_reply(
            receipt, packet.request_id, packet.request_hash
        )
        if reply is not None:
            transport_evidence = {
                "operation": packet.operation,
                "request_hash": packet.request_hash,
                "raw_response_hash": sha256_text(reply.raw_text),
                "clean_response_hash": sha256_text(reply.clean_text),
                "history_request_hash": reply.outbound_request_hash,
                "request_created_at": reply.request_created_at,
                "reply_created_at": reply.reply_created_at,
                "timestamp_order_verified": reply.timestamp_order_verified,
                "timestamp_evidence_limitation": reply.timestamp_evidence_limitation,
                "conversation_hash": hash_identifier(reply.conversation_id),
                "remote_reply_hash": hash_identifier(reply.reply_id),
            }
            # Persist transport evidence before parsing any model-authored JSON.
            update_send_attempt(
                stage,
                status="TRANSPORT_VERIFIED",
                **transport_evidence,
            )
            parsed = parse_minds_response(packet, reply.clean_text, transport_verified=True)
            update_send_attempt(
                stage,
                status="VERIFIED",
                response_hash=sha256_text(json.dumps(parsed, sort_keys=True)),
            )
            return parsed, reply, transport_evidence
        if attempt + 1 < attempts:
            await asyncio.sleep(interval_seconds)
    raise MindsError("轮询历史后仍无可核验回复；已停止，未重发")


async def send_once_and_verify(
    transport: MindsBuilderTransport,
    packet: MindsPacket,
    alias: str,
    stage: str,
    *,
    attempts: int = 24,
    interval_seconds: float = 5.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    entries = read_checkpoint_entries(allow_missing=True)
    existing = checkpoint_for_stage(entries, stage)
    if existing is not None:
        if existing.get("semantic_hash") != packet.semantic_hash:
            raise MindsError(f"{stage} 检查点语义哈希与待恢复 recall 不匹配")
        recovered = await recover_checkpoint_exchange(
            transport, existing, transport.mind_id
        )
        update_send_attempt(
            stage,
            status="VERIFIED",
            alias_hash=hash_identifier(recovered.alias),
            conversation_hash=hash_identifier(recovered.conversation_id),
            remote_request_hash=hash_identifier(recovered.outbound_message_id),
            remote_reply_hash=hash_identifier(recovered.reply.reply_id),
            raw_response_hash=sha256_text(recovered.reply.raw_text),
            clean_response_hash=sha256_text(recovered.reply.clean_text),
            history_request_hash=recovered.reply.outbound_request_hash,
            request_created_at=recovered.reply.request_created_at,
            reply_created_at=recovered.reply.reply_created_at,
            timestamp_order_verified=recovered.reply.timestamp_order_verified,
            timestamp_evidence_limitation=recovered.reply.timestamp_evidence_limitation,
            response_hash=sha256_text(
                json.dumps(recovered.parsed_response, sort_keys=True)
            ),
        )
        return recovered_exchange_evidence(recovered), recovered.parsed_response

    credits_before = await transport.get_credits()
    if credits_before <= 10:
        raise MindsError(f"Minds 余额 {credits_before:.2f} <= 10，已停止；禁止充值")
    begin_send_attempt(stage, packet, alias, credits_before)
    try:
        receipt = await transport.send_message(alias, packet.body)
    except MindsSendUncertain as exc:
        # The send happened at most once. Recover only through exact request-id history lookup.
        receipt = SendReceipt(exc.alias, exc.conversation_id, "", packet.request_hash)
        update_send_attempt(
            stage,
            status="UNCERTAIN",
            conversation_hash=hash_identifier(exc.conversation_id),
        )
    except MindsError:
        update_send_attempt(stage, status="REJECTED")
        raise
    else:
        update_send_attempt(
            stage,
            status="SENT",
            conversation_hash=hash_identifier(receipt.conversation_id),
            remote_request_hash=hash_identifier(receipt.message_id),
        )
    if receipt.request_hash != packet.request_hash:
        raise MindsError("发送回执与本地请求哈希不匹配")
    parsed, reply, transport_evidence = await wait_for_reply(
        transport,
        receipt,
        packet,
        stage,
        attempts=attempts,
        interval_seconds=interval_seconds,
    )
    credits_after = await transport.get_credits()
    update_send_attempt(stage, credits_after=credits_after)
    evidence = {
        "operation": packet.operation,
        "request_hash": packet.request_hash,
        "semantic_hash": packet.semantic_hash,
        "response_hash": sha256_text(json.dumps(parsed, sort_keys=True)),
        "alias_hash": hash_identifier(alias),
        "conversation_hash": hash_identifier(receipt.conversation_id),
        "remote_request_hash": (
            hash_identifier(receipt.message_id) if receipt.message_id else None
        ),
        "remote_reply_hash": hash_identifier(reply.reply_id),
        "raw_response_hash": transport_evidence["raw_response_hash"],
        "clean_response_hash": transport_evidence["clean_response_hash"],
        "history_request_hash": transport_evidence["history_request_hash"],
        "request_created_at": reply.request_created_at,
        "reply_created_at": reply.reply_created_at,
        "timestamp_order_verified": reply.timestamp_order_verified,
        "timestamp_evidence_limitation": reply.timestamp_evidence_limitation,
        "credits_before": credits_before,
        "credits_after": credits_after,
        "strict_schema_valid": True,
        "sent_this_run": True,
    }
    return evidence, parsed


def normalize_proof_text(value: str) -> str:
    return " ".join(value.casefold().split())


def assert_continuity_recall(
    parsed: dict[str, Any], approved_principle: str, sentinel: str
) -> None:
    recalled = parsed.get("recalled_principle")
    if not isinstance(recalled, str):
        raise MindsError("召回响应缺少已批准原则")
    normalized = normalize_proof_text(recalled)
    unavailable_markers = (
        "unavailable",
        "not available",
        "could not recall",
        "cannot recall",
        "unknown memory",
    )
    if any(marker in normalized for marker in unavailable_markers):
        raise MindsError("新会话明确表示记忆不可用，连续性证据失败")
    sentinel_match = normalize_proof_text(sentinel) in normalized
    full_principle_match = normalize_proof_text(approved_principle) in normalized
    if not sentinel_match and not full_principle_match:
        raise MindsError("新会话未精确召回不可猜测标记或完整批准原则")


async def send_pending_recalls(
    transport: MindsBuilderTransport,
    packets: list[MindsPacket],
    approved_principle: str,
    sentinel: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if len(packets) != 2 or any(
        packet.operation != "recall_and_draft" for packet in packets
    ):
        raise MindsError("恢复模式必须且只能发送两个待完成 recall")
    aliases = [random_alias("recall-a"), random_alias("recall-b")]
    calls: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    stages = ["recall_a", "recall_b"]
    for packet, alias, stage in zip(packets, aliases, stages, strict=True):
        call_evidence, parsed = await send_once_and_verify(
            transport, packet, alias, stage
        )
        try:
            assert_continuity_recall(parsed, approved_principle, sentinel)
        except MindsError:
            # A schema-valid reply that fails continuity must never unlock a
            # later recall on a retry. Persist only the rejection state.
            update_send_attempt(
                stage,
                status="REJECTED",
                continuity_verified=False,
                rejection_reason_code="CONTINUITY_MISMATCH",
            )
            raise
        call_evidence["continuity_match"] = True
        calls.append(call_evidence)
        responses.append(parsed)
    return calls, responses


def recovered_exchange_evidence(recovered: RecoveredStore) -> dict[str, Any]:
    checkpoint = recovered.checkpoint
    evidence = {
        "operation": recovered.packet.operation,
        "request_hash": recovered.packet.request_hash,
        "semantic_hash": recovered.packet.semantic_hash,
        "response_hash": sha256_text(
            json.dumps(recovered.parsed_response, sort_keys=True)
        ),
        "alias_hash": hash_identifier(recovered.alias),
        "conversation_hash": hash_identifier(recovered.conversation_id),
        "remote_request_hash": hash_identifier(recovered.outbound_message_id),
        "remote_reply_hash": hash_identifier(recovered.reply.reply_id),
        "raw_response_hash": sha256_text(recovered.reply.raw_text),
        "clean_response_hash": sha256_text(recovered.reply.clean_text),
        "history_request_hash": recovered.reply.outbound_request_hash,
        "request_created_at": recovered.reply.request_created_at,
        "reply_created_at": recovered.reply.reply_created_at,
        "timestamp_order_verified": recovered.reply.timestamp_order_verified,
        "timestamp_evidence_limitation": recovered.reply.timestamp_evidence_limitation,
        "credits_before": checkpoint.get("credits_before"),
        "credits_after": checkpoint.get("credits_after"),
        "strict_schema_valid": True,
        "recovered_from_official_history": True,
        "sent_this_run": False,
    }
    if evidence["credits_before"] is None or evidence["credits_after"] is None:
        evidence["credits_evidence_limitation"] = (
            "Historical credits were not captured before or after this recovered call."
        )
    return evidence


def recovered_store_evidence(recovered: RecoveredStore) -> dict[str, Any]:
    evidence = recovered_exchange_evidence(recovered)
    evidence["operation"] = "store_principle"
    return evidence


async def execute_mode(*, confirm_live: bool) -> int:
    if EVIDENCE_PATH.exists():
        raise MindsError("最终 live 证据已存在；禁止重复发送")
    if confirm_live and CHECKPOINT_PATH.exists():
        raise MindsError("已有发送检查点；禁止 fresh 重发，请用 --recover-checkpoint")

    load_dotenv(ROOT.parent / ".env")
    load_dotenv(ROOT / ".env", override=True)
    api_key = os.getenv("CONTEXTPATCH_MINDS_API_KEY") or os.getenv("MINDS_BUILDER_API_KEY", "")
    mind_id = os.getenv("CONTEXTPATCH_MIND_ID") or os.getenv("MINDS_MIND_ID", "")
    base_url = os.getenv(
        "CONTEXTPATCH_MINDS_BASE_URL", "https://api.build.hellominds.ai"
    )
    if not api_key or not mind_id:
        raise MindsError("未找到本机现有 MINDS_BUILDER_API_KEY / MINDS_MIND_ID")

    transport = MindsBuilderTransport(api_key, mind_id, base_url)
    if confirm_live:
        approved_principle, sentinel, store_packet, packets = build_fresh_proof_packets()
        store_call, store_response = await send_once_and_verify(
            transport, store_packet, random_alias("store"), "store"
        )
        if store_response.get("stored") is not True:
            raise MindsError("fresh store 回复未确认 stored=true")
        calls: list[dict[str, Any]] = [store_call]
        evidence_mode = "FRESH_THREE_CALL_CONTINUITY_PROOF"
    else:
        checkpoint = load_recovery_checkpoint()
        recovered = await recover_store_from_official_history(
            transport, checkpoint, mind_id
        )
        update_send_attempt(
            "store",
            status="VERIFIED",
            semantic_hash=recovered.packet.semantic_hash,
            alias_hash=hash_identifier(recovered.alias),
            conversation_hash=hash_identifier(recovered.conversation_id),
            remote_request_hash=hash_identifier(recovered.outbound_message_id),
            remote_reply_hash=hash_identifier(recovered.reply.reply_id),
            raw_response_hash=sha256_text(recovered.reply.raw_text),
            clean_response_hash=sha256_text(recovered.reply.clean_text),
            history_request_hash=recovered.reply.outbound_request_hash,
            request_created_at=recovered.reply.request_created_at,
            reply_created_at=recovered.reply.reply_created_at,
            timestamp_order_verified=recovered.reply.timestamp_order_verified,
            timestamp_evidence_limitation=recovered.reply.timestamp_evidence_limitation,
            response_hash=sha256_text(
                json.dumps(recovered.parsed_response, sort_keys=True)
            ),
        )
        approved_principle, sentinel, packets = build_pending_recall_packets(recovered)
        calls = [recovered_store_evidence(recovered)]
        evidence_mode = "RECOVERED_STORE_PLUS_TWO_RECALL_CONTINUITY_PROOF"
    recall_calls, responses = await send_pending_recalls(
        transport, packets, approved_principle, sentinel
    )
    calls.extend(recall_calls)
    conversation_hashes = {str(call["conversation_hash"]) for call in calls}
    if len(conversation_hashes) != 3:
        raise MindsError("三次调用未落在三个不同会话，证据失败")
    if len(responses) != 2:
        raise MindsError("两个 recall 未全部完成连续性断言")

    evidence = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mode": evidence_mode,
        "synthetic_content": True,
        "mind_id_hash": hash_identifier(mind_id),
        "same_mind": True,
        "distinct_conversations": True,
        "continuity_verified": True,
        "continuity_sentinel_hash": hash_identifier(sentinel),
        "new_sessions_receive_change_memory_key_and_bounded_untrusted_versions": True,
        "auto_publish": False,
        "auto_recharge": False,
        "raw_identifiers_persisted": False,
        "store_messages_sent_this_run": sum(
            1
            for call in calls
            if call["operation"] == "store_principle" and call.get("sent_this_run") is True
        ),
        "recall_messages_sent_this_run": sum(
            1
            for call in calls
            if call["operation"] == "recall_and_draft"
            and call.get("sent_this_run") is True
        ),
        "calls": calls,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(  # noqa: T201
        "LIVE_MINDS_PROOF_PASS: 1 store + 2 recalls, 3 distinct conversations"
    )
    return 0


async def run() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--confirm-live",
        action="store_true",
        help="Start a fresh three-call proof only when no checkpoint exists.",
    )
    mode.add_argument(
        "--recover-checkpoint",
        action="store_true",
        help=(
            "Recover a checkpoint from official history and send only unattempted stages."
        ),
    )
    mode.add_argument(
        "--repair-evidence-from-checkpoint",
        action="store_true",
        help="Locally add only missing verified history hashes; never use the network.",
    )
    args = parser.parse_args()
    with live_run_lock():
        if args.repair_evidence_from_checkpoint:
            repaired = repair_final_evidence_from_checkpoint()
            print(  # noqa: T201
                f"LOCAL_EVIDENCE_REPAIR_PASS: repaired_fields={repaired}"
            )
            return 0
        return await execute_mode(confirm_live=bool(args.confirm_live))


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except (MindsError, ValueError) as exc:
        print(f"LIVE_MINDS_PROOF_STOPPED: {exc}", file=sys.stderr)  # noqa: T201
        raise SystemExit(1) from exc
