"""SQLite database setup and parameterized query helpers.

Uses raw sqlite3 — no ORM. All queries MUST use parameterized placeholders.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import UTC, datetime
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
        conn.execute("PRAGMA journal_mode=WAL")
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


def insert_pending_transaction(
    conn: sqlite3.Connection,
    *,
    date: str,
    amount: str,
    payee: str,
    direction: str,
    source: str,
    upi_ref: str | None,
    email_message_id: str,
    confidence: float,
    suggested_account: str | None,
    account_id: str = "default",
) -> int:
    """Insert a pending transaction and return the row ID.

    Uses keyword-only args to prevent positional ordering mistakes.
    All values should be validated before reaching this function.
    """
    cursor = conn.execute(
        "INSERT INTO pending_transactions "
        "(date, amount, payee, direction, source, upi_ref, "
        "email_message_id, confidence, suggested_account, status, "
        "created_at, account_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
        (
            date,
            amount,
            payee,
            direction,
            source,
            upi_ref,
            email_message_id,
            confidence,
            suggested_account,
            datetime.now(tz=UTC).isoformat(),
            account_id,
        ),
    )
    return cursor.lastrowid or 0


def get_pending_transactions(
    conn: sqlite3.Connection,
    status: str = "pending",
    limit: int = 100,
) -> list[sqlite3.Row]:
    """Fetch pending transactions filtered by status, newest first."""
    return fetch_all(
        conn,
        "SELECT * FROM pending_transactions WHERE status = ? "
        "ORDER BY date DESC, id DESC LIMIT ?",
        (status, limit),
    )


def get_transaction_by_id(
    conn: sqlite3.Connection,
    transaction_id: int,
) -> sqlite3.Row | None:
    """Fetch a single pending transaction by ID."""
    return fetch_one(
        conn,
        "SELECT * FROM pending_transactions WHERE id = ?",
        (transaction_id,),
    )


def update_transaction_status(
    conn: sqlite3.Connection,
    transaction_id: int,
    status: str,
    suggested_account: str | None = None,
) -> bool:
    """Update a pending transaction's status. Returns True if a row was updated."""
    if suggested_account is not None:
        cursor = conn.execute(
            "UPDATE pending_transactions SET status = ?, suggested_account = ? WHERE id = ?",
            (status, suggested_account, transaction_id),
        )
    else:
        cursor = conn.execute(
            "UPDATE pending_transactions SET status = ? WHERE id = ?",
            (status, transaction_id),
        )
    return cursor.rowcount > 0
