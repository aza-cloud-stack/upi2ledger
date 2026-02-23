"""Tests for app.routes.sync — sync endpoint."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.models import get_connection, get_pending_transactions
from tests.conftest import login


class TestSyncRoute:
    """Tests for POST /sync."""

    def test_requires_auth(self, client: TestClient) -> None:
        """POST /sync redirects to login when unauthenticated."""
        response = client.post("/sync", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    @patch("app.routes.sync.load_credentials", return_value=None)
    def test_sync_disconnected_accounts(
        self,
        mock_creds: MagicMock,
        client: TestClient,
    ) -> None:
        """Disconnected accounts show 'Not connected' in results."""
        login(client)
        response = client.post("/sync")
        assert response.status_code == 200
        assert "Not connected" in response.text

    @patch("app.routes.sync.fetch_emails", return_value=[])
    @patch("app.routes.sync.get_gmail_service")
    @patch("app.routes.sync.load_credentials")
    def test_sync_no_new_emails(
        self,
        mock_creds: MagicMock,
        mock_service: MagicMock,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        """Sync with no new emails shows zero counts."""
        mock_creds.return_value = MagicMock()
        login(client)
        response = client.post("/sync")
        assert response.status_code == 200
        assert "0" in response.text

    @patch("app.routes.sync.mark_as_processed")
    @patch("app.routes.sync.map_merchant", return_value="expenses:food:delivery")
    @patch("app.routes.sync.parse_email")
    @patch("app.routes.sync.fetch_emails")
    @patch("app.routes.sync.get_gmail_service")
    @patch("app.routes.sync.load_credentials")
    def test_sync_fetches_and_stores(
        self,
        mock_creds: MagicMock,
        mock_service: MagicMock,
        mock_fetch: MagicMock,
        mock_parse: MagicMock,
        mock_map: MagicMock,
        mock_mark: MagicMock,
        client: TestClient,
    ) -> None:
        """Sync fetches, parses, and inserts into pending_transactions."""
        from datetime import date

        from app.gmail.fetch import EmailMessage
        from app.parser.base import ParsedTransaction

        mock_creds.return_value = MagicMock()
        mock_fetch.return_value = [
            EmailMessage(
                message_id="msg-sync-1",
                date="Thu, 23 Feb 2026 10:00:00 +0530",
                sender="Google <noreply@google.com>",
                subject="You paid ₹500 to Swiggy",
                body="UPI Ref: 402012345678",
            )
        ]
        mock_parse.return_value = ParsedTransaction(
            date=date(2026, 2, 23),
            amount=Decimal("500"),
            payee="Swiggy",
            direction="sent",
            source="gpay",
            upi_ref="402012345678",
            email_message_id="msg-sync-1",
            confidence=1.0,
        )

        login(client)
        response = client.post("/sync")
        assert response.status_code == 200
        assert "1" in response.text

        # Verify DB insertion
        db_path = client.app.state.db_path  # type: ignore[union-attr]
        conn = get_connection(db_path)
        try:
            rows = get_pending_transactions(conn)
            assert len(rows) == 1
            assert rows[0]["payee"] == "Swiggy"
            assert rows[0]["suggested_account"] == "expenses:food:delivery"
        finally:
            conn.close()

    @patch("app.routes.sync.mark_as_processed")
    @patch("app.routes.sync.parse_email", return_value=None)
    @patch("app.routes.sync.fetch_emails")
    @patch("app.routes.sync.get_gmail_service")
    @patch("app.routes.sync.load_credentials")
    def test_sync_marks_unparseable_as_processed(
        self,
        mock_creds: MagicMock,
        mock_service: MagicMock,
        mock_fetch: MagicMock,
        mock_parse: MagicMock,
        mock_mark: MagicMock,
        client: TestClient,
    ) -> None:
        """Unparseable emails are marked as processed with source='none'."""
        from app.gmail.fetch import EmailMessage

        mock_creds.return_value = MagicMock()
        mock_fetch.return_value = [
            EmailMessage(
                message_id="msg-unparseable",
                date="Thu, 23 Feb 2026 10:00:00 +0530",
                sender="promo@example.com",
                subject="Special offer!",
                body="Buy now",
            )
        ]

        login(client)
        client.post("/sync")

        mock_mark.assert_called_once_with(
            client.app.state.db_path,  # type: ignore[union-attr]
            "msg-unparseable",
            "none",
            "default",
        )

    @patch("app.routes.sync.load_credentials")
    def test_sync_handles_fetch_error(
        self,
        mock_creds: MagicMock,
        client: TestClient,
    ) -> None:
        """Sync handles Gmail API errors gracefully."""
        mock_creds.return_value = MagicMock()
        with patch("app.routes.sync.get_gmail_service", side_effect=Exception("API error")):
            login(client)
            response = client.post("/sync")
            assert response.status_code == 200
            assert "Error during sync" in response.text
