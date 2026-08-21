from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_web_demo_change_and_pause(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "web.db"))
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "ContextPatch" in home.text
        assert "Auto-publish: OFF" in home.text
        assert "/accept-response" not in home.text
        token = client.cookies["contextpatch_csrf"]

        loaded = client.post(
            "/demo/load",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert loaded.status_code == 303
        source_id = app.state.service.list_sources()[0]["id"]
        created = client.post(
            "/changes",
            data={
                "csrf_token": token,
                "source_id": source_id,
                "fact_key": "launch_date",
                "old_fact": "September 30",
                "new_fact": "October 7",
                "disclosure_principle": "State corrections plainly.",
                "due_at": "2026-08-22",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert len(app.state.service.dashboard()["queue"]) == 3

        paused = client.post(
            "/pause",
            data={"csrf_token": token, "paused": "1"},
            follow_redirects=False,
        )
        assert paused.status_code == 303
        assert client.get("/health").json()["status"] == "paused"


def test_csrf_is_required(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "csrf.db"))
    with TestClient(app) as client:
        response = client.post("/demo/load", data={"csrf_token": "wrong"})
        assert response.status_code == 403


def test_web_change_approval_rejection_and_unconfigured_minds(tmp_path: Path) -> None:
    app = create_app(Settings(database_path=tmp_path / "routes.db"))
    with TestClient(app) as client:
        client.get("/")
        token = client.cookies["contextpatch_csrf"]
        client.post("/demo/load", data={"csrf_token": token})
        source_id = app.state.service.list_sources()[0]["id"]

        def add_change(new_fact: str) -> int:
            client.post(
                "/changes",
                data={
                    "csrf_token": token,
                    "source_id": source_id,
                    "fact_key": "launch_date",
                    "old_fact": "September 30",
                    "new_fact": new_fact,
                    "disclosure_principle": "State corrections plainly.",
                    "due_at": "2026-08-22",
                },
            )
            return int(app.state.service.dashboard()["changes"][0]["id"])

        approved_id = add_change("October 7")
        approved = client.post(
            f"/changes/{approved_id}/approve",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert approved.status_code == 303
        exchange_id = int(app.state.service.dashboard()["exchanges"][0]["id"])
        queue_ids = [int(item["id"]) for item in app.state.service.dashboard()["queue"]]
        follow_up = client.post(
            f"/queue/{queue_ids[0]}/follow-up",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert follow_up.status_code == 303
        rejected_queue = client.post(
            f"/queue/{queue_ids[1]}/reject",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert rejected_queue.status_code == 303
        premature_approval = client.post(
            f"/queue/{queue_ids[2]}/approve",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert "error=" in premature_approval.headers["location"]
        send = client.post(
            f"/minds/{exchange_id}/send",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert "error=" in send.headers["location"]
        sync = client.post(
            f"/minds/{exchange_id}/sync",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert "error=" in sync.headers["location"]

        rejected_id = add_change("October 8")
        rejected = client.post(
            f"/changes/{rejected_id}/reject",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        rejected_change = next(
            item for item in app.state.service.dashboard()["changes"] if item["id"] == rejected_id
        )
        assert rejected_change["status"] == "REJECTED"

        resumed = client.post(
            "/pause",
            data={"csrf_token": token, "paused": "0"},
            follow_redirects=False,
        )
        assert resumed.status_code == 303
