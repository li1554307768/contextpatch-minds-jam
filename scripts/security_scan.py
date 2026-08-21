#!/usr/bin/env python3
"""Fail closed on common secrets in the public tree, artifacts and Git objects.

Matched values are never printed. A local ``.env`` is permitted only when Git
confirms it is ignored.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_EXECUTABLE = shutil.which("git")
MAX_FILE_BYTES = 40_000_000
SKIP_PARTS = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
SKIP_NAMES = {".env", "uv.lock", ".coverage"}

PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    (
        "private key",
        re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    ("AWS key", re.compile(rb"(?<![A-Z0-9])A[KS]IA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("GitHub token", re.compile(rb"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}")),
    (
        "OpenAI-style key",
        re.compile(rb"(?<![A-Za-z0-9])sk-(?!ant-)[A-Za-z0-9_-]{20,}"),
    ),
    ("Anthropic key", re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("Stripe live key", re.compile(rb"sk_live_[A-Za-z0-9]{16,}")),
    ("Google API key", re.compile(rb"AIza[0-9A-Za-z_-]{30,}")),
    (
        "JWT",
        re.compile(
            rb"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\."
            rb"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
        ),
    ),
    ("bearer token", re.compile(rb"(?i)bearer[ \t]+[A-Za-z0-9._~+/=-]{20,}")),
)


def matching_kinds(content: bytes) -> set[str]:
    return {name for name, pattern in PATTERNS if pattern.search(content)}


def run_git(*arguments: str) -> bytes:
    if GIT_EXECUTABLE is None:
        raise RuntimeError("Git executable not found")
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, *arguments], cwd=ROOT, check=False, capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError("Git object inspection failed")
    return result.stdout


def verify_env_is_ignored() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    if GIT_EXECUTABLE is None:
        raise RuntimeError("Git executable not found")
    result = subprocess.run(  # noqa: S603
        [GIT_EXECUTABLE, "check-ignore", "--quiet", "--", ".env"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("local .env is not ignored by Git")


def scan_tree() -> tuple[int, list[tuple[str, set[str]]]]:
    checked = 0
    findings: list[tuple[str, set[str]]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in relative.parts) or path.name in SKIP_NAMES:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        checked += 1
        kinds = matching_kinds(path.read_bytes())
        if kinds:
            findings.append((relative.as_posix(), kinds))
    return checked, findings


def scan_git_objects() -> tuple[int, list[tuple[str, set[str]]]]:
    objects = run_git(
        "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype)"
    ).splitlines()
    checked = 0
    findings: list[tuple[str, set[str]]] = []
    for line in objects:
        parts = line.decode("ascii", errors="strict").split()
        if len(parts) != 2:
            raise RuntimeError("unexpected Git object listing")
        object_id, object_type = parts
        if object_type != "blob":
            continue
        checked += 1
        kinds = matching_kinds(run_git("cat-file", "blob", object_id))
        if kinds:
            findings.append((f"blob:{object_id[:12]}", kinds))
    return checked, findings


def scan_artifacts() -> tuple[int, list[tuple[str, set[str]]]]:
    artifacts = sorted((ROOT / "dist").glob("*.whl"))
    artifacts += sorted((ROOT / "dist").glob("*.tar.gz"))
    video = ROOT / "output" / "demo-video" / "contextpatch-demo.mp4"
    if video.exists():
        artifacts.append(video)
    findings: list[tuple[str, set[str]]] = []
    checked = 0
    for path in artifacts:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir() or member.file_size > MAX_FILE_BYTES:
                        continue
                    checked += 1
                    kinds = matching_kinds(archive.read(member))
                    if kinds:
                        findings.append((f"{path.name}:{member.filename}", kinds))
        elif path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                for member in archive.getmembers():
                    if not member.isfile() or member.size > MAX_FILE_BYTES:
                        continue
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise RuntimeError("could not read sdist member")
                    checked += 1
                    kinds = matching_kinds(extracted.read())
                    if kinds:
                        findings.append((f"{path.name}:{member.name}", kinds))
        else:
            checked += 1
            kinds = matching_kinds(path.read_bytes())
            if kinds:
                findings.append((path.name, kinds))
    return checked, findings


def report(label: str, checked: int, findings: list[tuple[str, set[str]]]) -> bool:
    if not findings:
        print(f"{label}_PASS: checked={checked}; candidates=0")
        return True
    print(f"{label}_FAIL: checked={checked}; candidates={len(findings)}", file=sys.stderr)
    for location, kinds in findings:
        print(f"- {location}: {', '.join(sorted(kinds))}", file=sys.stderr)
    return False


def main() -> int:
    try:
        verify_env_is_ignored()
        tree = scan_tree()
        history = scan_git_objects()
        artifacts = scan_artifacts()
    except (OSError, RuntimeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"SECRET_SCAN_ERROR: {type(exc).__name__}", file=sys.stderr)
        return 2
    ok = report("TREE_SECRET_SCAN", *tree)
    ok = report("GIT_SECRET_SCAN", *history) and ok
    ok = report("ARTIFACT_SECRET_SCAN", *artifacts) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
