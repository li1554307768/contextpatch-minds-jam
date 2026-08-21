#!/usr/bin/env python3
"""Fail closed when installed packages lack a recognized permissive license."""

from __future__ import annotations

import re
import sys
from importlib import metadata

UNKNOWN = {"", "unknown", "none", "n/a", "na", "unlicensed", "proprietary"}
ALLOWED = (
    "MIT",
    "BSD",
    "APACHE",
    "MOZILLA PUBLIC LICENSE",
    "MPL-",
    "PYTHON SOFTWARE FOUNDATION",
    "PSF-",
    "ISC",
    "ZLIB",
    "CC0",
    "PUBLIC DOMAIN",
    "LGPL",
    "GNU LESSER GENERAL PUBLIC LICENSE",
)
FORBIDDEN = re.compile(
    r"(?<![A-Z])(?:AGPL|GPL)(?:V?[-_. ]?\d|\b)|GNU (?:AFFERO )?GENERAL PUBLIC LICENSE",
    re.IGNORECASE,
)


def evidence(distribution: metadata.Distribution) -> list[str]:
    values: list[str] = []
    for field in ("License-Expression", "License"):
        value = distribution.metadata.get(field)
        if value and value.strip().casefold() not in UNKNOWN:
            values.append(value.strip())
    values.extend(
        classifier
        for classifier in distribution.metadata.get_all("Classifier") or []
        if classifier.startswith("License ::")
    )
    return values


def main() -> int:
    problems: list[tuple[str, str]] = []
    seen: set[str] = set()
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name", "<unknown>")
        identity = name.casefold().replace("_", "-")
        if identity in seen:
            continue
        seen.add(identity)
        values = evidence(distribution)
        combined = " | ".join(values)
        if not values:
            problems.append((name, "missing"))
        elif FORBIDDEN.search(combined):
            problems.append((name, "GPL/AGPL"))
        elif not any(marker in combined.upper() for marker in ALLOWED):
            problems.append((name, "unrecognized"))
    if problems:
        print(f"LICENSE_SCAN_FAIL: {len(problems)} package(s)", file=sys.stderr)
        for name, reason in sorted(problems):
            print(f"- {name}: {reason}", file=sys.stderr)
        return 1
    print(f"LICENSE_SCAN_PASS: checked={len(seen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
