"""Tests for app.routes.transactions — approve/reject/list routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.models import (
    get_connection,
    get_transaction_by_id,
    insert_pending_transaction,
)
from tests.conftest import login


def _insert_test_txn(client: TestClient, **overrides: object) -> int:
    """Insert a test pending transaction and return its ID."""
    db_path = client.app.state.db_path  # type: ignore[union-attr]
    conn = get_connection(db_path)
    try:
        defaults = {
            "date": "2026-02-23",
            "amount": "500.00",
            "payee": "Swiggy",
            "direction": "sent",
            "source": "gpay",
            "upi_ref": "402012345678",
            "email_message_id": "msg-test-001",
            "confidence": 1.0,
            "suggested_account": "expenses:food:delivery",
        }
        defaults.update(overrides)  # type: ignore[arg-type]
        row_id = insert_pending_transaction(conn, **defaults)  # type: ignore[arg-type]
        conn.commit()
        return row_id
    finally:
        conn.close()


class TestTransactionsList:
    """Tests for GET /transactions."""

    def test_requires_auth(self, client: TestClient) -> None:
        """GET /transactions redirects to login."""
        response = client.get("/transactions", follow_redirects=False)
        assert response.status_code == 303

    def test_shows_pending(self, client: TestClient) -> None:
        """Shows pending transactions."""
        login(client)
        _insert_test_txn(client)
        response = client.get("/transactions")
        assert response.status_code == 200
        assert "Swiggy" in response.text
        assert "500.00" in response.text

    def test_empty_state(self, client: TestClient) -> None:
        """Shows empty message when no transactions."""
        login(client)
        response = client.get("/transactions")
        assert response.status_code == 200
        assert "No pending transactions" in response.text


class TestApproveTransaction:
    """Tests for POST /transactions/{id}/approve."""

    def test_requires_auth(self, client: TestClient) -> None:
        """POST approve redirects to login."""
        response = client.post("/transactions/1/approve", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    @patch("app.routes.transactions.write_entries", return_value=1)
    def test_approve_writes_journal(self, mock_write: MagicMock, client: TestClient) -> None:
        """Approve writes to journal and updates status."""
        login(client)
        txn_id = _insert_test_txn(client)
        response = client.post(
            f"/transactions/{txn_id}/approve",
            data={"account": "expenses:food:delivery"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "success=" in response.headers["location"]
        mock_write.assert_called_once()

        db_path = client.app.state.db_path  # type: ignore[union-attr]
        conn = get_connection(db_path)
        try:
            row = get_transaction_by_id(conn, txn_id)
            assert row is not None
            assert row["status"] == "approved"
        finally:
            conn.close()

    @patch("app.routes.transactions.write_entries", return_value=1)
    def test_approve_uses_suggested_account_when_no_override(
        self,
        mock_write: MagicMock,
        client: TestClient,
    ) -> None:
        """Approve uses suggested_account when no form override."""
        login(client)
        txn_id = _insert_test_txn(client, suggested_account="expenses:food:delivery")
        response = client.post(
            f"/transactions/{txn_id}/approve",
            data={"account": ""},
            follow_redirects=False,
        )
        assert response.status_code == 303

        db_path = client.app.state.db_path  # type: ignore[union-attr]
        conn = get_connection(db_path)
        try:
            row = get_transaction_by_id(conn, txn_id)
            assert row is not None
            assert row["suggested_account"] == "expenses:food:delivery"
        finally:
            conn.close()

    def test_approve_nonexistent_redirects(self, client: TestClient) -> None:
        """Approve nonexistent transaction redirects with error."""
        login(client)
        response = client.post("/transactions/99999/approve", follow_redirects=False)
        assert response.status_code == 303
        assert "not+found" in response.headers["location"]

    @patch("app.routes.transactions.write_entries", return_value=1)
    @patch("app.routes.transactions.save_merchant_mapping")
    @patch("app.routes.transactions.remap_pending_transactions", return_value=0)
    def test_approve_with_save_mapping(
        self,
        mock_remap: MagicMock,
        mock_save: MagicMock,
        mock_write: MagicMock,
        client: TestClient,
    ) -> None:
        """Approve with 'Remember' checkbox saves merchant mapping."""
        login(client)
        txn_id = _insert_test_txn(client)
        client.post(
            f"/transactions/{txn_id}/approve",
            data={"account": "expenses:food:delivery", "save_mapping": "on"},
            follow_redirects=False,
        )
        mock_save.assert_called_once()
        mock_remap.assert_called_once()

    @patch("app.routes.transactions.write_entries", return_value=1)
    @patch("app.routes.transactions.save_merchant_mapping")
    @patch("app.routes.transactions.remap_pending_transactions", return_value=3)
    def test_approve_with_remember_shows_remap_count(
        self,
        mock_remap: MagicMock,
        mock_save: MagicMock,
        mock_write: MagicMock,
        client: TestClient,
    ) -> None:
        """Approve with Remember includes remap count in success message."""
        login(client)
        txn_id = _insert_test_txn(client)
        response = client.post(
            f"/transactions/{txn_id}/approve",
            data={"account": "expenses:food:delivery", "save_mapping": "on"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        location = response.headers["location"]
        assert "Updated+3+similar" in location

    @patch("app.routes.transactions.write_entries", return_value=1)
    def test_approve_without_remember_skips_remap(
        self,
        mock_write: MagicMock,
        client: TestClient,
    ) -> None:
        """Approve without Remember does not trigger remap."""
        login(client)
        txn_id = _insert_test_txn(client)
        response = client.post(
            f"/transactions/{txn_id}/approve",
            data={"account": "expenses:food:delivery"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "similar" not in response.headers["location"]


class TestApproveAllTransactions:
    """Tests for POST /transactions/approve-all."""

    def test_requires_auth(self, client: TestClient) -> None:
        """POST approve-all redirects to login."""
        response = client.post("/transactions/approve-all", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_approve_all_empty(self, client: TestClient) -> None:
        """Approve all with no pending transactions shows error."""
        login(client)
        response = client.post("/transactions/approve-all", follow_redirects=False)
        assert response.status_code == 303
        assert "No+pending" in response.headers["location"]

    @patch("app.routes.transactions.write_entries", return_value=2)
    def test_approve_all_writes_journal(self, mock_write: MagicMock, client: TestClient) -> None:
        """Approve all writes all entries to journal and marks as approved."""
        login(client)
        id1 = _insert_test_txn(client, email_message_id="msg-1", payee="Swiggy")
        id2 = _insert_test_txn(client, email_message_id="msg-2", payee="Zomato")
        response = client.post("/transactions/approve-all", follow_redirects=False)
        assert response.status_code == 303
        assert "Approved+2" in response.headers["location"]
        mock_write.assert_called_once()

        # Both should be approved in DB
        db_path = client.app.state.db_path  # type: ignore[union-attr]
        conn = get_connection(db_path)
        try:
            row1 = get_transaction_by_id(conn, id1)
            row2 = get_transaction_by_id(conn, id2)
            assert row1 is not None and row1["status"] == "approved"
            assert row2 is not None and row2["status"] == "approved"
        finally:
            conn.close()


class TestRejectTransaction:
    """Tests for POST /transactions/{id}/reject."""

    def test_requires_auth(self, client: TestClient) -> None:
        """POST reject redirects to login."""
        response = client.post("/transactions/1/reject", follow_redirects=False)
        assert response.status_code == 303

    def test_reject_updates_status(self, client: TestClient) -> None:
        """Reject updates transaction status to 'rejected'."""
        login(client)
        txn_id = _insert_test_txn(client)
        response = client.post(f"/transactions/{txn_id}/reject", follow_redirects=False)
        assert response.status_code == 303

        db_path = client.app.state.db_path  # type: ignore[union-attr]
        conn = get_connection(db_path)
        try:
            row = get_transaction_by_id(conn, txn_id)
            assert row is not None
            assert row["status"] == "rejected"
        finally:
            conn.close()

    def test_reject_nonexistent(self, client: TestClient) -> None:
        """Reject nonexistent transaction redirects with error."""
        login(client)
        response = client.post("/transactions/99999/reject", follow_redirects=False)
        assert response.status_code == 303
        assert "not+found" in response.headers["location"]
