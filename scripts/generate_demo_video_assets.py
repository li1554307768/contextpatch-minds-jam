#!/usr/bin/env python3
"""Generate the sanitized ContextPatch scene manifest and English narration."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_DIR: Final = ROOT / "output" / "demo-video"
MANIFEST_PATH: Final = OUTPUT_DIR / "scene_manifest.json"
NARRATION_TEXT_PATH: Final = OUTPUT_DIR / "narration.txt"
NARRATION_AUDIO_PATH: Final = OUTPUT_DIR / "narration.aiff"

WIDTH: Final = 1920
HEIGHT: Final = 1080
FPS: Final = 30
TARGET_SECONDS: Final = 111.0

SCENES: Final = [
    {
        "duration": 7.0,
        "style": "title",
        "eyebrow": "TRACK 2 • CONTENT REPURPOSING ACROSS PLATFORMS",
        "title": "The persistent correction layer for creators",
        "subtitle": (
            "ContextPatch fixes the copies that become stale after content has already "
            "been repurposed."
        ),
    },
    {
        "duration": 10.0,
        "style": "branch",
        "eyebrow": "ONE SOURCE → MANY STALE COPIES",
        "title": "A fact changed. Which versions did it touch?",
        "subtitle": (
            "One launch date appears in an X post, a LinkedIn announcement, and a YouTube "
            "description. When the date moves, all three published versions become stale."
        ),
    },
    {
        "duration": 10.0,
        "style": "truth",
        "eyebrow": "HUMAN-APPROVED SOURCE OF TRUTH",
        "title": "One approved date change, no hidden edits",
        "subtitle": (
            "In this fully synthetic demo, Avery approves one fact change: the launch moves "
            "from September thirtieth to October seventh. Price, sessions, and access stay "
            "unchanged."
        ),
    },
    {
        "duration": 12.0,
        "style": "scan",
        "eyebrow": "DETERMINISTIC SCOPE FIRST",
        "title": "Three variants are affected before AI is involved",
        "subtitle": (
            "Local rules match the launch-date fact key and the old date before any model "
            "call. ContextPatch finds three affected versions and blocks their correction "
            "tasks until the fact is approved."
        ),
    },
    {
        "duration": 12.0,
        "style": "memory",
        "eyebrow": "BOUNDED MINDS MEMORY WRITE",
        "title": "Store the principle, not the social account",
        "subtitle": (
            "After human approval, ContextPatch asks Minds to remember one principle: make a "
            "visible public correction, name both dates, preserve the surrounding context, "
            "and never silently edit."
        ),
    },
    {
        "duration": 12.0,
        "style": "sessions",
        "eyebrow": "PERSISTENCE ACROSS A NEW CONVERSATION",
        "title": "Recall the policy without restating it",
        "subtitle": (
            "A new conversation receives the date change, three bounded original versions, "
            "and an opaque memory key, but not the prior principle. The Mind recalls it and "
            "returns exactly three platform patches plus WHY NOW."
        ),
    },
    {
        "duration": 11.0,
        "style": "patches",
        "eyebrow": "PLATFORM-AWARE CORRECTION QUEUE",
        "title": "Exact facts, different platform shapes",
        "subtitle": (
            "The queue shows a concise X correction, a contextual LinkedIn correction, and "
            "a YouTube description update. Each patch changes only the date and preserves "
            "the platform's existing context."
        ),
    },
    {
        "duration": 11.0,
        "style": "review",
        "eyebrow": "HUMAN REVIEW IS THE FINAL GATE",
        "title": "Approve the patch, never the publication",
        "subtitle": (
            "The reviewer sees September thirtieth versus October seventh, the original "
            "platform text, the recalled public-correction principle, and WHY NOW. Approval "
            "means ready for manual use, not posted."
        ),
    },
    {
        "duration": 9.0,
        "style": "pause",
        "eyebrow": "FAIL-CLOSED OPERATIONS",
        "title": "Pause stops follow-up work",
        "subtitle": (
            "If work should stop, Pause prevents new follow-ups. If a Minds request times "
            "out, ContextPatch locks the outcome and checks history before any retry."
        ),
    },
    {
        "duration": 9.0,
        "style": "audit",
        "eyebrow": "EVIDENCE WITHOUT FALSE CLAIMS",
        "title": "Every state change has a distinct meaning",
        "subtitle": (
            "The audit trail separates local scans, human decisions, verified Minds "
            "exchanges, and draft status. Synthetic evidence is never presented as a real "
            "user or live publication."
        ),
    },
    {
        "duration": 8.0,
        "style": "close",
        "eyebrow": "CONTEXTPATCH",
        "title": "Consistent. Persistent. Human-controlled.",
        "subtitle": (
            "ContextPatch keeps every reused claim consistent, persistent, and "
            "human-controlled across platforms."
        ),
    },
]


def validate_scenes() -> None:
    total = sum(float(scene["duration"]) for scene in SCENES)
    if abs(total - TARGET_SECONDS) > 0.001:
        raise ValueError(f"Scene duration must total {TARGET_SECONDS:.1f}s, got {total:.1f}s")
    for index, scene in enumerate(SCENES, start=1):
        required = {"duration", "style", "eyebrow", "title", "subtitle"}
        missing = required - set(scene)
        if missing:
            raise ValueError(f"Scene {index} is missing {sorted(missing)}")
        if float(scene["duration"]) <= 0:
            raise ValueError(f"Scene {index} duration must be positive")


def narration_text() -> str:
    return "\n\n".join(str(scene["subtitle"]) for scene in SCENES) + "\n"


def generate_narration() -> None:
    say = shutil.which("say")
    if say is None:
        raise RuntimeError("macOS 'say' command is required")
    command = [
        say,
        "-v",
        "Samantha",
        "-r",
        "180",
        "-f",
        str(NARRATION_TEXT_PATH),
        "-o",
        str(NARRATION_AUDIO_PATH),
    ]
    subprocess.run(command, check=True)  # noqa: S603 - fixed local macOS say command
    if not NARRATION_AUDIO_PATH.exists() or NARRATION_AUDIO_PATH.stat().st_size < 10_000:
        raise RuntimeError("Narration audio was not generated correctly")


def main() -> None:
    validate_scenes()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "brand": "ContextPatch",
        "dataset_label": "SYNTHETIC_DEMO_ONLY",
        "live_evidence_label": "LIVE MINDS CONTINUITY VERIFIED",
        "width": WIDTH,
        "height": HEIGHT,
        "fps": FPS,
        "duration": TARGET_SECONDS,
        "scenes": SCENES,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    NARRATION_TEXT_PATH.write_text(narration_text(), encoding="utf-8")
    generate_narration()
    print(f"manifest={MANIFEST_PATH}")
    print(f"narration_text={NARRATION_TEXT_PATH}")
    print(f"narration_audio={NARRATION_AUDIO_PATH}")
    print(f"scene_duration_seconds={TARGET_SECONDS:.1f}")


if __name__ == "__main__":
    main()
