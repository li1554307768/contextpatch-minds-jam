"""Runtime configuration with safe local defaults."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path("data/contextpatch.db")
    minds_api_key: str = ""
    mind_id: str = ""
    minds_base_url: str = "https://api.build.hellominds.ai"
    credit_floor: float = 10.0

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        floor = float(os.getenv("CONTEXTPATCH_CREDIT_FLOOR", "10"))
        if floor < 10:
            raise ValueError("CONTEXTPATCH_CREDIT_FLOOR 不能低于 10")
        mind_id = os.getenv("CONTEXTPATCH_MIND_ID", "").strip()
        if mind_id:
            mind_id = str(uuid.UUID(mind_id))
        return cls(
            database_path=Path(
                os.getenv("CONTEXTPATCH_DATABASE_PATH", "data/contextpatch.db")
            ),
            minds_api_key=os.getenv("CONTEXTPATCH_MINDS_API_KEY", "").strip(),
            mind_id=mind_id,
            minds_base_url=os.getenv(
                "CONTEXTPATCH_MINDS_BASE_URL", "https://api.build.hellominds.ai"
            ).rstrip("/"),
            credit_floor=floor,
        )
