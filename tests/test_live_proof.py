from __future__ import annotations

import asyncio
import copy
import json
import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.minds import (
    LEGACY_RECEIPT_MARKER,
    RECEIPT_MARKER,
    MindsBuilderTransport,
    MindsError,
    SendReceipt,
    VerifiedReply,
    build_recall_packet,
    build_store_packet,
    clean_history_message_text,
    sha256_text,
)


def proof_assertion() -> Callable[[dict[str, Any], str, str], None]:
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_live_minds_proof.py"
    namespace = runpy.run_path(str(script))
    assertion = namespace["assert_continuity_recall"]
    assert callable(assertion)
    return assertion


def script_namespace() -> dict[str, Any]:
    script = Path(__file__).resolve().parent.parent / "scripts" / "run_live_minds_proof.py"
    return runpy.run_path(str(script))


def test_live_continuity_requires_exact_unpredictable_marker_or_full_principle() -> None:
    assertion = proof_assertion()
    principle = "State corrections plainly. Continuity marker: cp-continuity-abc123."
    assertion(
        {"recalled_principle": principle.upper()},
        principle,
        "cp-continuity-abc123",
    )
    with pytest.raises(MindsError, match="连续性"):
        assertion(
            {"recalled_principle": "The approved principle is unavailable."},
            principle,
            "cp-continuity-abc123",
        )
    with pytest.raises(MindsError, match="未精确召回"):
        assertion(
            {"recalled_principle": "State corrections plainly."},
            principle,
            "cp-continuity-abc123",
        )


def test_recovers_legacy_store_from_hashed_official_history_without_post() -> None:
    namespace = script_namespace()
    principle = (
        "State the correction plainly. Continuity marker: "
        "cp-continuity-0123456789abcdef01234567."
    )
    packet = build_store_packet(
        "contextpatch:fact:launch_date:abc12345",
        fact_key="launch_date",
        old_fact="September 30",
        new_fact="October 7",
        disclosure_principle=principle,
    )
    outbound = packet.body.replace(RECEIPT_MARKER, LEGACY_RECEIPT_MARKER)
    request_hash = sha256_text(outbound)
    reply_payload = {
        "schema_version": "1.0",
        "request_id": packet.request_id,
        "operation": "store_principle",
        "memory_key": packet.memory_key,
        "stored": True,
        "summary": "Approved principle stored.",
    }
    raw_reply = (
        f"Stored.\n{LEGACY_RECEIPT_MARKER}\n"
        f"{json.dumps(reply_payload, separators=(',', ':'))}"
    )
    conversation_id = "conversation-recovered"
    outbound_id = "outbound-recovered"
    outbound_row_id = "outbound-row-recovered"
    reply_id = "reply-recovered"
    reply_row_id = "reply-row-recovered"
    mind_id = "00000000-0000-4000-8000-000000000001"
    hash_identifier = namespace["hash_identifier"]
    checkpoint = {
        "stage": "store",
        "operation": "store_principle",
        "status": "VERIFIED",
        "request_hash": request_hash,
        "history_request_hash": request_hash,
        "conversation_hash": hash_identifier(conversation_id),
        "remote_reply_hash": hash_identifier(reply_id),
        "raw_response_hash": sha256_text(raw_reply),
        "clean_response_hash": sha256_text(clean_history_message_text(raw_reply)),
        "request_created_at": "2026-08-20T00:00:01Z",
        "reply_created_at": "2026-08-20T00:00:02Z",
    }
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/v1/messaging/conversations":
            return httpx.Response(
                200,
                json=[
                    {
                        "alias": "cp-store-recovered",
                        "conversationId": conversation_id,
                        "mindId": mind_id,
                    }
                ],
            )
        if request.url.path == "/v1/messaging/conversations/cp-store-recovered":
            return httpx.Response(200, json={"conversationId": conversation_id})
        if request.url.path == "/v1/messaging/histories/cp-store-recovered":
            return httpx.Response(
                200,
                json=[
                    {
                        "senderType": 0,
                        "messageId": reply_id,
                        "id": reply_row_id,
                        "conversationId": conversation_id,
                        "messageText": raw_reply,
                        "createdAt": "2026-08-20T00:00:02Z",
                    },
                    {
                        "senderType": 1,
                        "messageId": outbound_id,
                        "id": outbound_row_id,
                        "conversationId": conversation_id,
                        "messageText": outbound,
                        "createdAt": "2026-08-20T00:00:01Z",
                    },
                ],
            )
        raise AssertionError(request.url.path)

    transport = MindsBuilderTransport(
        "test-key",
        mind_id,
        "https://example.test",
        transport=httpx.MockTransport(handler),
    )
    recovered = asyncio.run(
        namespace["recover_store_from_official_history"](
            transport, checkpoint, mind_id
        )
    )
    assert recovered.parsed_response["stored"] is True
    assert recovered.outbound_message_id == outbound_id
    assert recovered.reply.reply_id == reply_id
    approved, sentinel, pending = namespace["build_pending_recall_packets"](recovered)
    assert approved == principle
    assert sentinel == "cp-continuity-0123456789abcdef01234567"
    assert [item.operation for item in pending] == ["recall_and_draft", "recall_and_draft"]
    assert set(methods) == {"GET"}


def test_post_success_empty_history_never_resends_on_second_run(tmp_path: Path) -> None:
    namespace = script_namespace()
    checkpoint_path = tmp_path / "checkpoint.json"
    namespace["send_once_and_verify"].__globals__["CHECKPOINT_PATH"] = checkpoint_path
    namespace["write_checkpoint_entries"](
        [
            {
                "stage": "store",
                "operation": "store_principle",
                "status": "VERIFIED",
                "request_hash": "a" * 64,
            }
        ]
    )
    packet = build_recall_packet(
        "contextpatch:fact:launch_date:abc12345",
        fact_key="launch_date",
        old_fact="September 30",
        new_fact="October 7",
        affected_versions=[
            {"platform": "X", "content": "Old X post.", "synthetic": True}
        ],
    )
    alias = "cp-recall-empty"
    conversation_id = "conversation-empty"
    post_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.url.path.endswith("/credits"):
            return httpx.Response(200, json={"swarm": 40})
        if request.url.path == "/v1/messaging/conversations":
            return httpx.Response(
                200,
                json=[{"alias": alias, "conversationId": conversation_id}],
            )
        if request.url.path == f"/v1/messaging/conversations/{alias}":
            return httpx.Response(200, json={"conversationId": conversation_id})
        if request.url.path == "/v1/messaging/message":
            post_calls += 1
            return httpx.Response(
                200,
                json={"conversationId": conversation_id, "messageId": "outbound-empty"},
            )
        if request.url.path == f"/v1/messaging/histories/{alias}":
            return httpx.Response(200, json=[])
        raise AssertionError(request.url.path)

    transport = MindsBuilderTransport(
        "test-key",
        "00000000-0000-4000-8000-000000000001",
        "https://example.test",
        transport=httpx.MockTransport(handler),
    )
    send_once = namespace["send_once_and_verify"]
    with pytest.raises(MindsError, match="未重发"):
        asyncio.run(
            send_once(
                transport,
                packet,
                alias,
                "recall_a",
                attempts=1,
                interval_seconds=0,
            )
        )
    assert post_calls == 1
    with pytest.raises(MindsError):
        asyncio.run(
            send_once(
                transport,
                packet,
                alias,
                "recall_a",
                attempts=1,
                interval_seconds=0,
            )
        )
    assert post_calls == 1
    entries = namespace["read_checkpoint_entries"]()
    assert entries[1]["stage"] == "recall_a"
    assert entries[1]["status"] == "SENT"


def test_bad_first_recall_stops_before_second_send() -> None:
    namespace = script_namespace()
    principle = (
        "State the correction plainly. Continuity marker: "
        "cp-continuity-0123456789abcdef01234567."
    )
    _, sentinel, _, packets = namespace["build_fresh_proof_packets"]()
    calls: list[str] = []

    async def fake_send_once(
        _transport: Any, packet: Any, _alias: str, _stage: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        calls.append(packet.operation)
        return {"operation": packet.operation}, {
            "recalled_principle": "The approved principle is unavailable."
        }

    send_pending = namespace["send_pending_recalls"]
    rejection_updates: list[tuple[str, dict[str, Any]]] = []

    def fake_update(stage: str, **updates: Any) -> dict[str, Any]:
        rejection_updates.append((stage, updates))
        return updates

    send_pending.__globals__["send_once_and_verify"] = fake_send_once
    send_pending.__globals__["update_send_attempt"] = fake_update
    with pytest.raises(MindsError, match="连续性"):
        asyncio.run(send_pending(object(), packets, principle, sentinel))
    assert calls == ["recall_and_draft"]
    assert rejection_updates == [
        (
            "recall_a",
            {
                "status": "REJECTED",
                "continuity_verified": False,
                "rejection_reason_code": "CONTINUITY_MISMATCH",
            },
        )
    ]


def test_live_run_lock_fails_closed_without_waiting(tmp_path: Path) -> None:
    namespace = script_namespace()
    lock = namespace["live_run_lock"]
    lock_path = tmp_path / "proof.lock.json"
    with lock(lock_path):
        with pytest.raises(MindsError, match="另一个 live proof"):
            with lock(lock_path):
                raise AssertionError("second lock must never be acquired")


def test_new_send_evidence_includes_verified_history_request_hash(
    tmp_path: Path,
) -> None:
    namespace = script_namespace()
    checkpoint_path = tmp_path / "checkpoint.json"
    send_once = namespace["send_once_and_verify"]
    send_once.__globals__["CHECKPOINT_PATH"] = checkpoint_path
    namespace["write_checkpoint_entries"](
        [
            {
                "stage": "store",
                "operation": "store_principle",
                "status": "VERIFIED",
                "request_hash": "a" * 64,
            }
        ],
        checkpoint_path,
    )
    packet = build_recall_packet(
        "contextpatch:fact:launch_date:abc12345",
        fact_key="launch_date",
        old_fact="September 30",
        new_fact="October 7",
        affected_versions=[
            {"platform": "X", "content": "Old X post.", "synthetic": True}
        ],
    )
    raw_reply = json.dumps(
        {
            "schema_version": "1.0",
            "request_id": packet.request_id,
            "operation": "recall_and_draft",
            "memory_key": packet.memory_key,
            "recalled_principle": "State corrections plainly.",
            "platform_patches": {"x": "Correction: October 7."},
            "why_now": "The active X post has the old launch date.",
        }
    )

    class LocalTransport:
        mind_id = "00000000-0000-4000-8000-000000000001"

        def __init__(self) -> None:
            self.credit_reads = 0

        async def get_credits(self) -> float:
            self.credit_reads += 1
            return 40.0 if self.credit_reads == 1 else 39.0

        async def send_message(self, alias: str, message: str) -> SendReceipt:
            return SendReceipt(alias, "conversation", "message", sha256_text(message))

        async def find_reply(
            self, receipt: SendReceipt, request_id: str, expected_request_hash: str
        ) -> VerifiedReply:
            assert request_id == packet.request_id
            assert expected_request_hash == packet.request_hash
            return VerifiedReply(
                raw_text=raw_reply,
                clean_text=raw_reply,
                reply_id="reply",
                conversation_id=receipt.conversation_id,
                request_created_at="2026-08-20T00:00:01Z",
                reply_created_at="2026-08-20T00:00:02Z",
                outbound_request_hash=packet.request_hash,
                timestamp_order_verified=True,
                timestamp_evidence_limitation=None,
            )

    evidence, _ = asyncio.run(
        send_once(
            LocalTransport(),
            packet,
            "cp-recall-local",
            "recall_a",
            attempts=1,
            interval_seconds=0,
        )
    )
    assert evidence["history_request_hash"] == packet.request_hash


def test_local_evidence_repair_is_strict_atomic_and_idempotent(
    tmp_path: Path,
) -> None:
    namespace = script_namespace()
    checkpoint_path = tmp_path / "checkpoint.json"
    evidence_path = tmp_path / "evidence.json"
    fields = (
        "request_hash",
        "semantic_hash",
        "conversation_hash",
        "remote_request_hash",
        "remote_reply_hash",
        "raw_response_hash",
        "clean_response_hash",
        "response_hash",
    )
    stages = ("store", "recall_a", "recall_b")
    operations = ("store_principle", "recall_and_draft", "recall_and_draft")
    entries: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    for index, (stage, operation) in enumerate(
        zip(stages, operations, strict=True), start=1
    ):
        request_hash = f"{index:x}" * 64
        entry: dict[str, Any] = {
            "stage": stage,
            "status": "VERIFIED",
            "operation": operation,
            "history_request_hash": request_hash,
        }
        for offset, field in enumerate(fields):
            entry[field] = request_hash if field == "request_hash" else (
                f"{index + offset:x}"[-1] * 64
            )
        entries.append(entry)
        calls.append({field: entry[field] for field in ("operation", *fields)})
        if stage != "recall_b":
            calls[-1]["history_request_hash"] = request_hash
    namespace["write_checkpoint_entries"](entries, checkpoint_path)
    evidence = {
        "schema_version": "1.0",
        "continuity_verified": True,
        "calls": calls,
    }
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

    repair = namespace["repair_final_evidence_from_checkpoint"]
    assert repair(evidence_path, checkpoint_path) == 1
    repaired = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert repaired["calls"][2]["history_request_hash"] == entries[2]["request_hash"]
    assert repair(evidence_path, checkpoint_path) == 0

    tampered = copy.deepcopy(repaired)
    tampered["calls"][2]["raw_response_hash"] = "f" * 64
    evidence_path.write_text(json.dumps(tampered), encoding="utf-8")
    before = evidence_path.read_bytes()
    with pytest.raises(MindsError, match="raw_response_hash"):
        repair(evidence_path, checkpoint_path)
    assert evidence_path.read_bytes() == before
