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
    get_pending_transactions,
    get_transaction_by_id,
    init_db,
    insert_pending_transaction,
    update_transaction_status,
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

    def test_schema_version_is_3(self, test_db: Path) -> None:
        """Fresh install sets schema version to 3."""
        assert CURRENT_SCHEMA_VERSION == 3
        conn = get_connection(test_db)
        try:
            row = fetch_one(conn, "SELECT version FROM schema_version")
            assert row is not None
            assert row["version"] == 3
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
            assert row["version"] == 3
        finally:
            conn.close()


class TestPendingTransactionHelpers:
    """Tests for pending_transactions insert/query/update helpers."""

    def test_insert_pending_transaction(self, test_db: Path) -> None:
        """insert_pending_transaction creates a row with correct fields."""
        conn = get_connection(test_db)
        try:
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="500.00",
                payee="Swiggy",
                direction="sent",
                source="gpay",
                upi_ref="402012345678",
                email_message_id="msg-001",
                confidence=1.0,
                suggested_account="expenses:food:delivery",
                account_id="personal",
            )
            conn.commit()
            assert row_id > 0

            row = get_transaction_by_id(conn, row_id)
            assert row is not None
            assert row["payee"] == "Swiggy"
            assert row["amount"] == "500.00"
            assert row["direction"] == "sent"
            assert row["status"] == "pending"
            assert row["account_id"] == "personal"
            assert row["upi_ref"] == "402012345678"
            assert row["suggested_account"] == "expenses:food:delivery"
        finally:
            conn.close()

    def test_insert_without_optional_fields(self, test_db: Path) -> None:
        """insert_pending_transaction handles None upi_ref and suggested_account."""
        conn = get_connection(test_db)
        try:
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="200.00",
                payee="Bank Transfer",
                direction="sent",
                source="bank",
                upi_ref=None,
                email_message_id="msg-002",
                confidence=0.8,
                suggested_account=None,
            )
            conn.commit()
            assert row_id > 0

            row = get_transaction_by_id(conn, row_id)
            assert row is not None
            assert row["upi_ref"] is None
            assert row["suggested_account"] is None
        finally:
            conn.close()

    def test_get_pending_transactions_ordered(self, test_db: Path) -> None:
        """get_pending_transactions returns rows ordered by date desc."""
        conn = get_connection(test_db)
        try:
            for i, date in enumerate(["2026-02-20", "2026-02-22", "2026-02-21"]):
                insert_pending_transaction(
                    conn,
                    date=date,
                    amount="100.00",
                    payee=f"Merchant{i}",
                    direction="sent",
                    source="gpay",
                    upi_ref=None,
                    email_message_id=f"msg-{i}",
                    confidence=1.0,
                    suggested_account=None,
                )
            conn.commit()

            rows = get_pending_transactions(conn)
            assert len(rows) == 3
            assert rows[0]["date"] == "2026-02-22"
            assert rows[2]["date"] == "2026-02-20"
        finally:
            conn.close()

    def test_get_pending_transactions_filters_status(self, test_db: Path) -> None:
        """get_pending_transactions only returns rows with matching status."""
        conn = get_connection(test_db)
        try:
            insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="100.00",
                payee="A",
                direction="sent",
                source="gpay",
                upi_ref=None,
                email_message_id="msg-a",
                confidence=1.0,
                suggested_account=None,
            )
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="200.00",
                payee="B",
                direction="sent",
                source="gpay",
                upi_ref=None,
                email_message_id="msg-b",
                confidence=1.0,
                suggested_account=None,
            )
            update_transaction_status(conn, row_id, "approved")
            conn.commit()

            pending = get_pending_transactions(conn, status="pending")
            assert len(pending) == 1
            assert pending[0]["payee"] == "A"

            approved = get_pending_transactions(conn, status="approved")
            assert len(approved) == 1
            assert approved[0]["payee"] == "B"
        finally:
            conn.close()

    def test_update_transaction_status(self, test_db: Path) -> None:
        """update_transaction_status changes status and optional account."""
        conn = get_connection(test_db)
        try:
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="100.00",
                payee="Test",
                direction="sent",
                source="gpay",
                upi_ref=None,
                email_message_id="msg-x",
                confidence=1.0,
                suggested_account=None,
            )
            conn.commit()

            result = update_transaction_status(conn, row_id, "approved", "expenses:food")
            conn.commit()
            assert result is True

            row = get_transaction_by_id(conn, row_id)
            assert row is not None
            assert row["status"] == "approved"
            assert row["suggested_account"] == "expenses:food"
        finally:
            conn.close()

    def test_update_status_without_account(self, test_db: Path) -> None:
        """update_transaction_status works without changing suggested_account."""
        conn = get_connection(test_db)
        try:
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="100.00",
                payee="Test",
                direction="sent",
                source="gpay",
                upi_ref=None,
                email_message_id="msg-y",
                confidence=1.0,
                suggested_account="expenses:food",
            )
            conn.commit()

            update_transaction_status(conn, row_id, "rejected")
            conn.commit()

            row = get_transaction_by_id(conn, row_id)
            assert row is not None
            assert row["status"] == "rejected"
            assert row["suggested_account"] == "expenses:food"
        finally:
            conn.close()

    def test_update_nonexistent_returns_false(self, test_db: Path) -> None:
        """update_transaction_status returns False for nonexistent ID."""
        conn = get_connection(test_db)
        try:
            result = update_transaction_status(conn, 99999, "approved")
            assert result is False
        finally:
            conn.close()

    def test_get_transaction_by_id_not_found(self, test_db: Path) -> None:
        """get_transaction_by_id returns None for nonexistent ID."""
        conn = get_connection(test_db)
        try:
            row = get_transaction_by_id(conn, 99999)
            assert row is None
        finally:
            conn.close()
