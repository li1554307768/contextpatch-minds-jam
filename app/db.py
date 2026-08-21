"""SQLite schema and connection boundary."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    synthetic INTEGER NOT NULL CHECK (synthetic IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    platform TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    content TEXT NOT NULL,
    fact_keys_json TEXT NOT NULL,
    synthetic INTEGER NOT NULL CHECK (synthetic IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(platform, external_ref)
);

CREATE TABLE IF NOT EXISTS fact_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    fact_key TEXT NOT NULL,
    old_fact TEXT NOT NULL,
    new_fact TEXT NOT NULL,
    disclosure_principle TEXT NOT NULL,
    due_at TEXT NOT NULL,
    memory_key TEXT NOT NULL UNIQUE,
    injection_flagged INTEGER NOT NULL CHECK (injection_flagged IN (0, 1)),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING_APPROVAL', 'APPROVED', 'REJECTED')
    ),
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL REFERENCES fact_changes(id),
    version_id INTEGER NOT NULL REFERENCES content_versions(id),
    reason TEXT NOT NULL,
    UNIQUE(change_id, version_id)
);

CREATE TABLE IF NOT EXISTS correction_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL REFERENCES fact_changes(id),
    version_id INTEGER NOT NULL REFERENCES content_versions(id),
    status TEXT NOT NULL CHECK (
        status IN (
            'BLOCKED_PENDING_FACT_APPROVAL', 'PENDING_REVIEW', 'APPROVED',
            'REJECTED', 'CANCELLED'
        )
    ),
    draft TEXT,
    why_now TEXT NOT NULL,
    due_at TEXT NOT NULL,
    follow_up_count INTEGER NOT NULL DEFAULT 0,
    last_follow_up_at TEXT,
    decided_at TEXT,
    UNIQUE(change_id, version_id)
);

CREATE TABLE IF NOT EXISTS minds_exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id INTEGER NOT NULL REFERENCES fact_changes(id),
    operation TEXT NOT NULL CHECK (operation IN ('store_principle', 'recall_and_draft')),
    request_id TEXT NOT NULL UNIQUE,
    memory_key TEXT NOT NULL,
    session_alias TEXT NOT NULL,
    request_body TEXT NOT NULL,
    request_hash TEXT NOT NULL UNIQUE,
    semantic_hash TEXT NOT NULL UNIQUE,
    expected_platforms_json TEXT NOT NULL DEFAULT '[]',
    injection_flagged INTEGER NOT NULL CHECK (injection_flagged IN (0, 1)),
    status TEXT NOT NULL CHECK (
        status IN ('PREPARED', 'SENDING', 'SENT', 'UNCERTAIN', 'COMPLETED', 'REJECTED')
    ),
    credits_before REAL,
    remote_conversation_id TEXT,
    remote_message_id TEXT,
    remote_reply_id TEXT UNIQUE,
    response_json TEXT,
    response_hash TEXT UNIQUE,
    raw_response_hash TEXT,
    clean_response_hash TEXT,
    history_request_hash TEXT,
    request_created_at TEXT,
    reply_created_at TEXT,
    timestamp_order_verified INTEGER CHECK (timestamp_order_verified IN (0, 1)),
    timestamp_evidence_limitation TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            exchange_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(minds_exchanges)").fetchall()
            }
            if "expected_platforms_json" not in exchange_columns:
                connection.execute(
                    """
                    ALTER TABLE minds_exchanges
                    ADD COLUMN expected_platforms_json TEXT NOT NULL DEFAULT '[]'
                    """
                )
            if "history_request_hash" not in exchange_columns:
                connection.execute(
                    "ALTER TABLE minds_exchanges ADD COLUMN history_request_hash TEXT"
                )
            if "timestamp_order_verified" not in exchange_columns:
                connection.execute(
                    "ALTER TABLE minds_exchanges ADD COLUMN timestamp_order_verified INTEGER"
                )
            if "timestamp_evidence_limitation" not in exchange_columns:
                connection.execute(
                    "ALTER TABLE minds_exchanges ADD COLUMN timestamp_evidence_limitation TEXT"
                )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('paused', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO app_state(key, value) VALUES ('auto_publish', '0')"
            )
            connection.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()
