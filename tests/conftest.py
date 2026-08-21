from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.services import ContextPatchService


@pytest.fixture
def service(tmp_path: Path) -> ContextPatchService:
    return ContextPatchService(Database(tmp_path / "test.db"))


@pytest.fixture
def demo_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "synthetic_demo.json"
