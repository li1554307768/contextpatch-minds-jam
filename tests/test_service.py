from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.minds import MindsSendUncertain, SendReceipt, VerifiedReply, sha256_text
from app.services import ContextPatchService


def create_demo_change(service: ContextPatchService, demo_path: Path) -> int:
    service.load_demo(demo_path)
    source_id = int(service.list_sources()[0]["id"])
    return service.create_change(
        source_id=source_id,
        fact_key="launch_date",
        old_fact="September 30",
        new_fact="October 7",
        disclosure_principle="State the correction plainly and preserve context.",
        due_at="2026-08-22",
    )


class FakeTransport:
    def __init__(
        self,
        *,
        credits: float = 30,
        timeout: bool = False,
        recalled_principle: str = "State the correction plainly and preserve context.",
    ):
        self.credits = credits
        self.timeout = timeout
        self.recalled_principle = recalled_principle
        self.messages: dict[str, str] = {}
        self.send_calls = 0

    async def get_credits(self) -> float:
        await asyncio.sleep(0)
        return self.credits

    async def ensure_conversation(self, alias: str) -> str:
        return f"conversation-{alias}"

    async def send_message(self, alias: str, message: str) -> SendReceipt:
        self.send_calls += 1
        self.messages[alias] = message
        conversation_id = f"conversation-{alias}"
        if self.timeout:
            self.timeout = False
            raise MindsSendUncertain("timeout", alias, conversation_id)
        return SendReceipt(
            alias, conversation_id, f"message-{self.send_calls}", sha256_text(message)
        )

    async def find_reply(
        self, receipt: SendReceipt, request_id: str, expected_request_hash: str
    ) -> VerifiedReply | None:
        message = self.messages.get(receipt.alias, "")
        if not message or sha256_text(message) != expected_request_hash:
            return None
        if '"operation":"store_principle"' in message:
            payload: dict[str, Any] = {
                "schema_version": "1.0",
                "operation": "store_principle",
                "memory_key": _memory_key(message),
                "stored": True,
                "summary": "Approved principle stored.",
            }
        else:
            payload = {
                "schema_version": "1.0",
                "operation": "recall_and_draft",
                "memory_key": _memory_key(message),
                "recalled_principle": self.recalled_principle,
                "platform_patches": {
                    "x": "X correction: October 7 replaces September 30.",
                    "linkedin": "LinkedIn update: October 7 replaces September 30.",
                    "youtube": "YouTube description: October 7 replaces September 30.",
                },
                "why_now": "Three active versions contain the outdated launch date.",
            }
        raw = json.dumps(payload)
        return VerifiedReply(
            raw_text=raw,
            clean_text=raw,
            reply_id=f"reply-{request_id}",
            conversation_id=receipt.conversation_id,
            request_created_at="2026-08-20T00:00:01Z",
            reply_created_at="2026-08-20T00:00:02Z",
            outbound_request_hash=sha256_text(message),
            timestamp_order_verified=True,
            timestamp_evidence_limitation=None,
        )


def _memory_key(message: str) -> str:
    marker = '"memory_key":"'
    return message.split(marker, 1)[1].split('"', 1)[0]


def test_demo_is_idempotent_and_deterministic_impacts(
    service: ContextPatchService, demo_path: Path
) -> None:
    assert service.load_demo(demo_path) == (3, 0)
    assert service.load_demo(demo_path) == (0, 3)
    change_id = create_demo_change(service, demo_path)
    state = service.dashboard()
    change = next(item for item in state["changes"] if item["id"] == change_id)
    assert change["impact_count"] == 3
    assert {item["platform"] for item in state["queue"]} == {"X", "LinkedIn", "YouTube"}
    assert all(item["status"] == "BLOCKED_PENDING_FACT_APPROVAL" for item in state["queue"])
    assert state["auto_publish"] is False


def test_no_matching_fact_produces_empty_queue(
    service: ContextPatchService, demo_path: Path
) -> None:
    service.load_demo(demo_path)
    source_id = int(service.list_sources()[0]["id"])
    change_id = service.create_change(
        source_id=source_id,
        fact_key="unrelated_fact",
        old_fact="does not occur",
        new_fact="new value",
        disclosure_principle="Be clear.",
        due_at="2026-08-22",
    )
    state = service.dashboard()
    change = next(item for item in state["changes"] if item["id"] == change_id)
    assert change["impact_count"] == 0
    assert state["queue"] == []


def test_verified_minds_flow_unlocks_drafts_and_human_decision(
    service: ContextPatchService, demo_path: Path
) -> None:
    change_id = create_demo_change(service, demo_path)
    store_exchange = service.approve_change(change_id)
    fake = FakeTransport()

    async def flow() -> None:
        await service.send_exchange(store_exchange, fake, credit_floor=10)
        assert await service.sync_exchange(store_exchange, fake) is True
        recall_exchange = int(service.dashboard()["exchanges"][0]["id"])
        await service.send_exchange(recall_exchange, fake, credit_floor=10)
        assert await service.sync_exchange(recall_exchange, fake) is True

    asyncio.run(flow())
    state = service.dashboard()
    assert all(item["draft"] for item in state["queue"])
    drafts = {item["platform"]: item["draft"] for item in state["queue"]}
    assert drafts["X"].startswith("X correction")
    assert drafts["LinkedIn"].startswith("LinkedIn update")
    assert drafts["YouTube"].startswith("YouTube description")
    queue_id = int(state["queue"][0]["id"])
    service.mark_follow_up(queue_id)
    service.decide_correction(queue_id, True)
    approved = next(item for item in service.dashboard()["queue"] if item["id"] == queue_id)
    assert approved["status"] == "APPROVED"
    assert approved["follow_up_count"] == 1
    assert fake.send_calls == 2
    recall_exchange = next(
        item for item in state["exchanges"] if item["operation"] == "recall_and_draft"
    )
    assert recall_exchange["recalled_principle"] == (
        "State the correction plainly and preserve context."
    )


def test_pause_reject_and_credit_floor(service: ContextPatchService, demo_path: Path) -> None:
    change_id = create_demo_change(service, demo_path)
    service.set_paused(True)
    with pytest.raises(ValueError, match="暂停"):
        service.approve_change(change_id)
    service.set_paused(False)
    service.reject_change(change_id)
    assert service.dashboard()["changes"][0]["status"] == "REJECTED"

    second_id = create_demo_change(service, demo_path)
    exchange_id = service.approve_change(second_id)
    with pytest.raises(ValueError, match="余额"):
        asyncio.run(service.send_exchange(exchange_id, FakeTransport(credits=10), credit_floor=10))
    exchange = next(item for item in service.dashboard()["exchanges"] if item["id"] == exchange_id)
    assert exchange["status"] == "PREPARED"


def test_double_click_only_sends_once(service: ContextPatchService, demo_path: Path) -> None:
    exchange_id = service.approve_change(create_demo_change(service, demo_path))
    fake = FakeTransport()

    async def double_click() -> list[object]:
        return await asyncio.gather(
            service.send_exchange(exchange_id, fake, credit_floor=10),
            service.send_exchange(exchange_id, fake, credit_floor=10),
            return_exceptions=True,
        )

    results = asyncio.run(double_click())
    assert fake.send_calls == 1
    assert sum(isinstance(item, SendReceipt) for item in results) == 1
    assert sum(isinstance(item, ValueError) for item in results) == 1


def test_timeout_recovers_from_history_without_resend(
    service: ContextPatchService, demo_path: Path
) -> None:
    exchange_id = service.approve_change(create_demo_change(service, demo_path))
    fake = FakeTransport(timeout=True)
    with pytest.raises(MindsSendUncertain):
        asyncio.run(service.send_exchange(exchange_id, fake, credit_floor=10))
    assert fake.send_calls == 1
    exchange = next(item for item in service.dashboard()["exchanges"] if item["id"] == exchange_id)
    assert exchange["status"] == "UNCERTAIN"
    assert exchange["remote_message_id"] is None
    assert asyncio.run(service.sync_exchange(exchange_id, fake)) is True
    assert fake.send_calls == 1
    completed = next(item for item in service.dashboard()["exchanges"] if item["id"] == exchange_id)
    assert completed["status"] == "COMPLETED"
    assert completed["raw_response_hash"]
    assert completed["clean_response_hash"]
    assert completed["history_request_hash"] == completed["request_hash"]


@pytest.mark.parametrize(
    "recalled",
    ["A different principle.", "The approved principle is unavailable."],
)
def test_recalled_principle_must_exactly_match_approved_value(
    service: ContextPatchService, demo_path: Path, recalled: str
) -> None:
    store_exchange = service.approve_change(create_demo_change(service, demo_path))
    fake = FakeTransport(recalled_principle=recalled)

    async def flow() -> int:
        await service.send_exchange(store_exchange, fake, credit_floor=10)
        assert await service.sync_exchange(store_exchange, fake) is True
        recall_exchange = next(
            item
            for item in service.dashboard()["exchanges"]
            if item["operation"] == "recall_and_draft"
        )
        recall_id = int(recall_exchange["id"])
        await service.send_exchange(recall_id, fake, credit_floor=10)
        return recall_id

    recall_id = asyncio.run(flow())
    with pytest.raises(ValueError, match="不精确匹配"):
        asyncio.run(service.sync_exchange(recall_id, fake))
    state = service.dashboard()
    recall = next(item for item in state["exchanges"] if item["id"] == recall_id)
    assert recall["status"] == "SENT"
    assert all(item["draft"] is None for item in state["queue"])


def test_global_send_lock_serializes_different_exchanges(
    service: ContextPatchService, demo_path: Path
) -> None:
    first = service.approve_change(create_demo_change(service, demo_path))
    service.load_demo(demo_path)
    source_id = int(service.list_sources()[0]["id"])
    second_change = service.create_change(
        source_id=source_id,
        fact_key="price",
        old_fact="$149",
        new_fact="$129",
        disclosure_principle="State the correction plainly and preserve context.",
        due_at="2026-08-22",
    )
    second = service.approve_change(second_change)

    class SlowTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0

        async def get_credits(self) -> float:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            return self.credits

        async def send_message(self, alias: str, message: str) -> SendReceipt:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            receipt = await super().send_message(alias, message)
            self.active -= 1
            return receipt

    fake = SlowTransport()

    async def send_both() -> None:
        await asyncio.gather(
            service.send_exchange(first, fake, credit_floor=10),
            service.send_exchange(second, fake, credit_floor=10),
        )

    asyncio.run(send_both())
    assert fake.send_calls == 2
    assert fake.max_active == 1


def test_database_send_lease_fails_closed_before_credit_check(
    service: ContextPatchService, demo_path: Path
) -> None:
    exchange_id = service.approve_change(create_demo_change(service, demo_path))
    with service.database.connect() as connection:
        connection.execute(
            """
            INSERT INTO app_state(key, value) VALUES ('minds_send_lease', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            ('{"token":"other-process","exchange_id":999,"expires_at":9999999999}',),
        )
        connection.commit()
    fake = FakeTransport()
    with pytest.raises(ValueError, match="全局发送通道正忙"):
        asyncio.run(service.send_exchange(exchange_id, fake, credit_floor=10))
    assert fake.send_calls == 0
    exchange = next(
        item for item in service.dashboard()["exchanges"] if item["id"] == exchange_id
    )
    assert exchange["status"] == "PREPARED"


def test_cannot_approve_draft_before_verified_minds_reply(
    service: ContextPatchService, demo_path: Path
) -> None:
    change_id = create_demo_change(service, demo_path)
    service.approve_change(change_id)
    queue_id = int(service.dashboard()["queue"][0]["id"])
    with pytest.raises(ValueError, match="Minds"):
        service.decide_correction(queue_id, True)
    service.decide_correction(queue_id, False)
    assert service.dashboard()["queue"][0]["status"] == "REJECTED"
