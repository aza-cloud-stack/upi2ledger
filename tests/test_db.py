"""Tests for app.db.models — SQLite setup and query helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from app.db.models import (
    CURRENT_SCHEMA_VERSION,
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
