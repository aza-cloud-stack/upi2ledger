"""SQLite database setup and parameterized query helpers.

Uses raw sqlite3 — no ORM. All queries MUST use parameterized placeholders.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_SCHEMA = """\
CREATE TABLE IF NOT EXISTS processed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    processed_at TEXT NOT NULL,
    parser_source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS merchant_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    merchant_pattern TEXT UNIQUE NOT NULL,
    account TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount TEXT NOT NULL,
    payee TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('sent', 'received')),
    source TEXT NOT NULL,
    upi_ref TEXT,
    email_message_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    suggested_account TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""

CURRENT_SCHEMA_VERSION = 2


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add account_id column to processed_emails and pending_transactions."""
    cursor = conn.execute("PRAGMA table_info(processed_emails)")
    columns = {row[1] for row in cursor.fetchall()}
    if "account_id" in columns:
        return

    conn.execute(
        "ALTER TABLE processed_emails ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default'"
    )
    conn.execute(
        "ALTER TABLE pending_transactions ADD COLUMN account_id TEXT NOT NULL DEFAULT 'default'"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_processed_account_message "
        "ON processed_emails (account_id, message_id)"
    )
    conn.commit()
    logger.info("Database migrated from v1 to v2 (added account_id)")


def get_db_path() -> Path:
    """Return the database file path (data/upi2ledger.db relative to project root)."""
    return Path("data") / "upi2ledger.db"


def init_db(db_path: Path) -> None:
    """Create database tables and set secure file permissions.

    Creates the data/ directory if needed, initialises the schema,
    and sets file permissions to 0o600 (owner read/write only).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(DB_SCHEMA)
        # Track schema version and run migrations
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        current_version = row[0] if row else 0

        if current_version < 1:
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (CURRENT_SCHEMA_VERSION,)
            )
        if current_version < 2:
            _migrate_v1_to_v2(conn)
            if current_version >= 1:
                conn.execute(
                    "UPDATE schema_version SET version = ? WHERE version = ?",
                    (CURRENT_SCHEMA_VERSION, current_version),
                )
        conn.commit()
    finally:
        conn.close()

    # Restrict file permissions — owner only
    os.chmod(db_path, 0o600)
    logger.info("Database initialised at %s", db_path.name)


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a connection with row factory enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def execute(
    conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
) -> sqlite3.Cursor:
    """Execute a parameterized query and return the cursor."""
    return conn.execute(query, params)


def fetch_one(
    conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
) -> sqlite3.Row | None:
    """Execute a parameterized query and return a single row or None."""
    cursor = conn.execute(query, params)
    return cursor.fetchone()  # type: ignore[return-value]


def fetch_all(
    conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    """Execute a parameterized query and return all rows."""
    cursor = conn.execute(query, params)
    return cursor.fetchall()
