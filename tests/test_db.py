"""Tests for app.db.models — SQLite setup and query helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.db.models import (
    CURRENT_SCHEMA_VERSION,
    _migrate_v1_to_v2,
    execute,
    fetch_all,
    fetch_one,
    get_connection,
    init_db,
)


class TestInitDb:
    """Test database initialization."""

    def test_creates_db_file(self, db_path: Path) -> None:
        init_db(db_path)
        assert db_path.exists()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        nested_path = tmp_path / "subdir" / "test.db"
        init_db(nested_path)
        assert nested_path.exists()

    def test_file_permissions_600(self, db_path: Path) -> None:
        init_db(db_path)
        mode = os.stat(db_path).st_mode & 0o777
        assert mode == 0o600

    def test_tables_exist(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row[0] for row in cursor.fetchall()]
            assert "processed_emails" in tables
            assert "merchant_mappings" in tables
            assert "pending_transactions" in tables
            assert "schema_version" in tables
        finally:
            conn.close()

    def test_schema_version_tracked(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        try:
            row = fetch_one(conn, "SELECT version FROM schema_version")
            assert row is not None
            assert row["version"] == CURRENT_SCHEMA_VERSION
        finally:
            conn.close()

    def test_idempotent_init(self, db_path: Path) -> None:
        """Running init_db twice should not error or duplicate schema version."""
        init_db(db_path)
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            rows = fetch_all(conn, "SELECT version FROM schema_version")
            assert len(rows) == 1
        finally:
            conn.close()


class TestQueryHelpers:
    """Test parameterized query helpers."""

    def test_execute_insert_and_fetch(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        sql = (
            "INSERT INTO processed_emails"
            " (message_id, processed_at, parser_source)"
            " VALUES (?, ?, ?)"
        )
        try:
            execute(conn, sql, ("msg-001", "2026-01-15T10:00:00Z", "regex"))
            conn.commit()

            row = fetch_one(
                conn,
                "SELECT message_id, parser_source FROM processed_emails" " WHERE message_id = ?",
                ("msg-001",),
            )
            assert row is not None
            assert row["message_id"] == "msg-001"
            assert row["parser_source"] == "regex"
        finally:
            conn.close()

    def test_fetch_all_returns_list(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        sql = (
            "INSERT INTO processed_emails"
            " (message_id, processed_at, parser_source)"
            " VALUES (?, ?, ?)"
        )
        try:
            for i in range(3):
                execute(conn, sql, (f"msg-{i}", "2026-01-15T10:00:00Z", "regex"))
            conn.commit()

            rows = fetch_all(conn, "SELECT * FROM processed_emails")
            assert len(rows) == 3
        finally:
            conn.close()

    def test_fetch_one_returns_none_for_missing(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        try:
            row = fetch_one(
                conn,
                "SELECT * FROM processed_emails WHERE message_id = ?",
                ("nonexistent",),
            )
            assert row is None
        finally:
            conn.close()

    def test_direction_check_constraint(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        sql = (
            "INSERT INTO pending_transactions"
            " (date, amount, payee, direction, source,"
            " email_message_id, confidence, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        )
        try:
            with pytest.raises(sqlite3.IntegrityError):
                execute(
                    conn,
                    sql,
                    (
                        "2026-01-15",
                        "100.00",
                        "Test",
                        "invalid",
                        "gpay",
                        "msg-1",
                        1.0,
                        "2026-01-15T10:00:00Z",
                    ),
                )
        finally:
            conn.close()

    def test_account_id_column_exists(self, test_db: Path) -> None:
        """Fresh init creates processed_emails with account_id column."""
        conn = get_connection(test_db)
        try:
            cursor = conn.execute("PRAGMA table_info(processed_emails)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "account_id" in columns
        finally:
            conn.close()

    def test_account_id_default_value(self, test_db: Path) -> None:
        """account_id defaults to 'default' on insert."""
        conn = get_connection(test_db)
        try:
            conn.execute(
                "INSERT INTO processed_emails (message_id, processed_at, parser_source) "
                "VALUES (?, ?, ?)",
                ("msg-acct", "2026-01-15T10:00:00Z", "regex"),
            )
            conn.commit()
            row = fetch_one(
                conn,
                "SELECT account_id FROM processed_emails WHERE message_id = ?",
                ("msg-acct",),
            )
            assert row is not None
            assert row["account_id"] == "default"
        finally:
            conn.close()

    def test_schema_version_is_2(self, test_db: Path) -> None:
        """Fresh install sets schema version to 2."""
        assert CURRENT_SCHEMA_VERSION == 2
        conn = get_connection(test_db)
        try:
            row = fetch_one(conn, "SELECT version FROM schema_version")
            assert row is not None
            assert row["version"] == 2
        finally:
            conn.close()

    def test_status_check_constraint(self, test_db: Path) -> None:
        conn = get_connection(test_db)
        sql = (
            "INSERT INTO pending_transactions"
            " (date, amount, payee, direction, source,"
            " email_message_id, confidence, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        try:
            with pytest.raises(sqlite3.IntegrityError):
                execute(
                    conn,
                    sql,
                    (
                        "2026-01-15",
                        "100.00",
                        "Test",
                        "sent",
                        "gpay",
                        "msg-1",
                        1.0,
                        "invalid_status",
                        "2026-01-15T10:00:00Z",
                    ),
                )
        finally:
            conn.close()


class TestMigrationV1ToV2:
    """Test schema migration from v1 to v2."""

    def _create_v1_db(self, db_path: Path) -> None:
        """Create a v1 database (no account_id columns)."""
        from app.db.models import DB_SCHEMA

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(DB_SCHEMA)
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            conn.execute(
                "INSERT INTO processed_emails (message_id, processed_at, parser_source) "
                "VALUES (?, ?, ?)",
                ("old-msg", "2026-01-01T00:00:00Z", "regex"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_migration_adds_account_id(self, tmp_path: Path) -> None:
        """Migration adds account_id column to processed_emails."""
        db_path = tmp_path / "v1.db"
        self._create_v1_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            _migrate_v1_to_v2(conn)
            cursor = conn.execute("PRAGMA table_info(processed_emails)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "account_id" in columns
        finally:
            conn.close()

    def test_migration_existing_rows_get_default(self, tmp_path: Path) -> None:
        """Existing rows get account_id='default' after migration."""
        db_path = tmp_path / "v1.db"
        self._create_v1_db(db_path)

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            _migrate_v1_to_v2(conn)
            row = conn.execute(
                "SELECT account_id FROM processed_emails WHERE message_id = ?",
                ("old-msg",),
            ).fetchone()
            assert row is not None
            assert row["account_id"] == "default"
        finally:
            conn.close()

    def test_migration_idempotent(self, tmp_path: Path) -> None:
        """Running migration twice does not error."""
        db_path = tmp_path / "v1.db"
        self._create_v1_db(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            _migrate_v1_to_v2(conn)
            _migrate_v1_to_v2(conn)  # Should not raise
        finally:
            conn.close()

    def test_init_db_runs_migration_on_v1(self, tmp_path: Path) -> None:
        """init_db migrates a v1 database to v2."""
        db_path = tmp_path / "v1.db"
        self._create_v1_db(db_path)

        init_db(db_path)

        conn = get_connection(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(processed_emails)")
            columns = {row[1] for row in cursor.fetchall()}
            assert "account_id" in columns

            row = fetch_one(conn, "SELECT version FROM schema_version")
            assert row is not None
            assert row["version"] == 2
        finally:
            conn.close()
