from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTPATCH_DATABASE_PATH", "data/custom.db")
    monkeypatch.setenv("CONTEXTPATCH_CREDIT_FLOOR", "12")
    monkeypatch.setenv("CONTEXTPATCH_MIND_ID", "00000000-0000-4000-8000-000000000001")
    settings = Settings.from_env()
    assert str(settings.database_path) == "data/custom.db"
    assert settings.credit_floor == 12
    assert settings.mind_id == "00000000-0000-4000-8000-000000000001"


def test_credit_floor_cannot_be_weakened(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTPATCH_CREDIT_FLOOR", "9")
    with pytest.raises(ValueError, match="10"):
        Settings.from_env()
