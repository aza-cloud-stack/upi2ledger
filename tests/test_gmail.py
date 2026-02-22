"""Tests for Gmail OAuth2 auth, email fetching, and routes."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.models import get_connection
from app.gmail.auth import (
    SCOPES,
    _write_token_secure,
    create_auth_flow,
    exchange_code_for_credentials,
    is_connected,
    load_credentials,
)
from app.gmail.fetch import (
    EmailMessage,
    _decode_body,
    _get_header,
    _get_processed_ids,
    fetch_emails,
    is_processed,
    mark_as_processed,
)
from tests.conftest import login

# ---------------------------------------------------------------------------
# TestGmailAuth
# ---------------------------------------------------------------------------


class TestGmailAuth:
    """Tests for app/gmail/auth.py — OAuth2 flow + token management."""

    def test_scopes_readonly_only(self) -> None:
        """SCOPES must only contain gmail.readonly."""
        assert SCOPES == ["https://www.googleapis.com/auth/gmail.readonly"]
        assert len(SCOPES) == 1

    def test_write_token_secure_permissions(self, tmp_path: Path) -> None:
        """Token file must be written with 0o600 permissions."""
        token_path = tmp_path / "token.json"
        mock_creds = MagicMock()
        mock_creds.token = "access_token"
        mock_creds.refresh_token = "refresh_token"
        mock_creds.token_uri = "https://oauth2.googleapis.com/token"
        mock_creds.client_id = "client_id"
        mock_creds.client_secret = "client_secret"
        mock_creds.scopes = set(SCOPES)

        _write_token_secure(token_path, mock_creds)

        assert token_path.exists()
        mode = stat.S_IMODE(os.stat(token_path).st_mode)
        assert mode == 0o600

        data = json.loads(token_path.read_text())
        assert data["token"] == "access_token"
        assert data["refresh_token"] == "refresh_token"

    def test_write_token_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Token write should create parent directories if missing."""
        token_path = tmp_path / "subdir" / "token.json"
        mock_creds = MagicMock()
        mock_creds.token = "t"
        mock_creds.refresh_token = "r"
        mock_creds.token_uri = "uri"
        mock_creds.client_id = "cid"
        mock_creds.client_secret = "cs"
        mock_creds.scopes = set(SCOPES)

        _write_token_secure(token_path, mock_creds)
        assert token_path.exists()

    def test_load_credentials_no_file(self, tmp_path: Path) -> None:
        """load_credentials returns None when token file doesn't exist."""
        result = load_credentials(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_credentials_invalid_json(self, tmp_path: Path) -> None:
        """load_credentials returns None for invalid JSON."""
        token_path = tmp_path / "token.json"
        token_path.write_text("not valid json")
        result = load_credentials(token_path)
        assert result is None
        # File should be cleaned up
        assert not token_path.exists()

    @patch("app.gmail.auth.Credentials.from_authorized_user_file")
    def test_load_credentials_valid(self, mock_from_file: MagicMock, tmp_path: Path) -> None:
        """load_credentials returns valid credentials."""
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_from_file.return_value = mock_creds

        result = load_credentials(token_path)
        assert result is mock_creds

    @patch("app.gmail.auth.GoogleAuthRequest")
    @patch("app.gmail.auth.Credentials.from_authorized_user_file")
    def test_load_credentials_refreshes_expired(
        self, mock_from_file: MagicMock, mock_request_cls: MagicMock, tmp_path: Path
    ) -> None:
        """load_credentials auto-refreshes expired tokens."""
        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"
        mock_creds.token = "new_token"
        mock_creds.token_uri = "uri"
        mock_creds.client_id = "cid"
        mock_creds.client_secret = "cs"
        mock_creds.scopes = set(SCOPES)
        mock_from_file.return_value = mock_creds

        result = load_credentials(token_path)
        assert result is mock_creds
        mock_creds.refresh.assert_called_once()

    @patch("app.gmail.auth.Credentials.from_authorized_user_file")
    def test_load_credentials_refresh_failure(
        self, mock_from_file: MagicMock, tmp_path: Path
    ) -> None:
        """load_credentials returns None when refresh fails."""
        from google.auth.exceptions import RefreshError

        token_path = tmp_path / "token.json"
        token_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_token"
        mock_creds.refresh.side_effect = RefreshError("fail")
        mock_from_file.return_value = mock_creds

        result = load_credentials(token_path)
        assert result is None
        assert not token_path.exists()

    def test_create_auth_flow_missing_credentials(self, tmp_path: Path) -> None:
        """create_auth_flow raises FileNotFoundError for missing credentials."""
        with pytest.raises(FileNotFoundError, match="Gmail credentials file not found"):
            create_auth_flow(tmp_path / "missing.json", "http://localhost/callback")

    @patch("app.gmail.auth.Flow.from_client_secrets_file")
    def test_create_auth_flow_success(self, mock_flow: MagicMock, tmp_path: Path) -> None:
        """create_auth_flow creates a Flow when credentials exist."""
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")

        create_auth_flow(creds_path, "http://localhost/callback")
        mock_flow.assert_called_once_with(
            str(creds_path), scopes=SCOPES, redirect_uri="http://localhost/callback"
        )

    def test_is_connected_false_no_file(self, tmp_path: Path) -> None:
        """is_connected returns False when no token file exists."""
        assert is_connected(tmp_path / "token.json") is False

    @patch("app.gmail.auth.load_credentials")
    def test_is_connected_true(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """is_connected returns True when valid credentials exist."""
        mock_load.return_value = MagicMock()
        assert is_connected(tmp_path / "token.json") is True

    @patch("app.gmail.auth.Flow.from_client_secrets_file")
    def test_exchange_code_saves_token(self, mock_flow_cls: MagicMock, tmp_path: Path) -> None:
        """exchange_code_for_credentials saves the token file securely."""
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.token = "access"
        mock_creds.refresh_token = "refresh"
        mock_creds.token_uri = "uri"
        mock_creds.client_id = "cid"
        mock_creds.client_secret = "cs"
        mock_creds.scopes = set(SCOPES)
        mock_flow.credentials = mock_creds

        token_path = tmp_path / "token.json"
        result = exchange_code_for_credentials(mock_flow, "auth_code", token_path)

        mock_flow.fetch_token.assert_called_once_with(code="auth_code")
        assert result is mock_creds
        assert token_path.exists()
        mode = stat.S_IMODE(os.stat(token_path).st_mode)
        assert mode == 0o600


# ---------------------------------------------------------------------------
# TestGmailFetch
# ---------------------------------------------------------------------------


class TestGmailFetch:
    """Tests for app/gmail/fetch.py — email fetcher + deduplication."""

    def test_email_message_model(self) -> None:
        """EmailMessage model validates correctly."""
        msg = EmailMessage(
            message_id="abc123",
            date="2026-01-15",
            sender="bank@example.com",
            subject="UPI payment",
            body="You sent ₹500",
        )
        assert msg.message_id == "abc123"
        assert msg.subject == "UPI payment"

    def test_get_header_found(self) -> None:
        """_get_header returns the header value when present."""
        headers = [
            {"name": "From", "value": "test@example.com"},
            {"name": "Subject", "value": "UPI Alert"},
        ]
        assert _get_header(headers, "Subject") == "UPI Alert"
        assert _get_header(headers, "from") == "test@example.com"  # case-insensitive

    def test_get_header_missing(self) -> None:
        """_get_header returns empty string for missing headers."""
        headers = [{"name": "From", "value": "test@example.com"}]
        assert _get_header(headers, "Date") == ""

    def test_decode_body_plain_text(self) -> None:
        """_decode_body decodes a plain text body."""
        body_data = base64.urlsafe_b64encode(b"Hello plain text").decode()
        payload: dict[str, object] = {
            "mimeType": "text/plain",
            "body": {"data": body_data},
        }
        assert _decode_body(payload) == "Hello plain text"

    def test_decode_body_multipart_prefers_plain(self) -> None:
        """_decode_body prefers text/plain over text/html in multipart."""
        plain_data = base64.urlsafe_b64encode(b"Plain content").decode()
        html_data = base64.urlsafe_b64encode(b"<b>HTML content</b>").decode()
        payload: dict[str, object] = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": plain_data}},
                {"mimeType": "text/html", "body": {"data": html_data}},
            ],
        }
        assert _decode_body(payload) == "Plain content"

    def test_decode_body_fallback_html(self) -> None:
        """_decode_body falls back to text/html when no text/plain."""
        html_data = base64.urlsafe_b64encode(b"<b>HTML only</b>").decode()
        payload: dict[str, object] = {
            "mimeType": "multipart/alternative",
            "parts": [
                {"mimeType": "text/html", "body": {"data": html_data}},
            ],
        }
        assert _decode_body(payload) == "<b>HTML only</b>"

    def test_decode_body_nested_multipart(self) -> None:
        """_decode_body handles nested multipart structures."""
        plain_data = base64.urlsafe_b64encode(b"Nested plain").decode()
        payload: dict[str, object] = {
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": plain_data}},
                    ],
                },
            ],
        }
        assert _decode_body(payload) == "Nested plain"

    def test_decode_body_empty(self) -> None:
        """_decode_body returns empty string for empty body."""
        payload: dict[str, object] = {"mimeType": "text/plain", "body": {"data": ""}}
        assert _decode_body(payload) == ""

    def test_get_processed_ids(self, test_db: Path) -> None:
        """_get_processed_ids returns set of processed message IDs."""
        conn = get_connection(test_db)
        try:
            conn.execute(
                "INSERT INTO processed_emails (message_id, processed_at, parser_source) "
                "VALUES (?, ?, ?)",
                ("msg1", "2026-01-01T00:00:00Z", "regex"),
            )
            conn.execute(
                "INSERT INTO processed_emails (message_id, processed_at, parser_source) "
                "VALUES (?, ?, ?)",
                ("msg2", "2026-01-01T00:00:00Z", "regex"),
            )
            conn.commit()
        finally:
            conn.close()

        ids = _get_processed_ids(test_db)
        assert ids == {"msg1", "msg2"}

    def test_get_processed_ids_filters_by_account(self, test_db: Path) -> None:
        """_get_processed_ids only returns IDs for the specified account."""
        conn = get_connection(test_db)
        try:
            conn.execute(
                "INSERT INTO processed_emails "
                "(message_id, processed_at, parser_source, account_id) VALUES (?, ?, ?, ?)",
                ("msg-a", "2026-01-01T00:00:00Z", "regex", "personal"),
            )
            conn.execute(
                "INSERT INTO processed_emails "
                "(message_id, processed_at, parser_source, account_id) VALUES (?, ?, ?, ?)",
                ("msg-b", "2026-01-01T00:00:00Z", "regex", "work"),
            )
            conn.commit()
        finally:
            conn.close()

        assert _get_processed_ids(test_db, "personal") == {"msg-a"}
        assert _get_processed_ids(test_db, "work") == {"msg-b"}

    def test_mark_as_processed(self, test_db: Path) -> None:
        """mark_as_processed inserts a row."""
        mark_as_processed(test_db, "msg_new", "regex")

        conn = get_connection(test_db)
        try:
            cursor = conn.execute(
                "SELECT message_id, parser_source FROM processed_emails WHERE message_id = ?",
                ("msg_new",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["message_id"] == "msg_new"
            assert row["parser_source"] == "regex"
        finally:
            conn.close()

    def test_mark_as_processed_with_account(self, test_db: Path) -> None:
        """mark_as_processed stores account_id."""
        mark_as_processed(test_db, "msg-acct", "regex", account_id="personal")

        conn = get_connection(test_db)
        try:
            row = conn.execute(
                "SELECT account_id FROM processed_emails WHERE message_id = ?",
                ("msg-acct",),
            ).fetchone()
            assert row is not None
            assert row["account_id"] == "personal"
        finally:
            conn.close()

    def test_mark_as_processed_ignores_duplicate(self, test_db: Path) -> None:
        """mark_as_processed ignores duplicates (INSERT OR IGNORE)."""
        mark_as_processed(test_db, "msg_dup", "regex")
        mark_as_processed(test_db, "msg_dup", "llm")  # Should not raise

        conn = get_connection(test_db)
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM processed_emails WHERE message_id = ?",
                ("msg_dup",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row["cnt"] == 1
        finally:
            conn.close()

    def test_is_processed_true(self, test_db: Path) -> None:
        """is_processed returns True for processed messages."""
        mark_as_processed(test_db, "msg_check", "regex")
        assert is_processed(test_db, "msg_check") is True

    def test_is_processed_false(self, test_db: Path) -> None:
        """is_processed returns False for unprocessed messages."""
        assert is_processed(test_db, "msg_unknown") is False

    def test_is_processed_account_scoped(self, test_db: Path) -> None:
        """is_processed is scoped to a specific account."""
        mark_as_processed(test_db, "msg-scope", "regex", account_id="personal")
        assert is_processed(test_db, "msg-scope", account_id="personal") is True
        assert is_processed(test_db, "msg-scope", account_id="work") is False

    def test_fetch_emails_skips_processed(self, test_db: Path) -> None:
        """fetch_emails skips already-processed message IDs."""
        mark_as_processed(test_db, "old_msg", "regex")

        mock_service = MagicMock()
        list_result = mock_service.users.return_value.messages.return_value.list.return_value
        list_result.execute.return_value = {
            "messages": [{"id": "old_msg"}, {"id": "new_msg"}],
        }

        plain_data = base64.urlsafe_b64encode(b"New email body").decode()
        get_result = mock_service.users.return_value.messages.return_value.get.return_value
        get_result.execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "Date", "value": "2026-01-15"},
                    {"name": "From", "value": "bank@test.com"},
                    {"name": "Subject", "value": "UPI Payment"},
                ],
                "mimeType": "text/plain",
                "body": {"data": plain_data},
            }
        }

        emails = fetch_emails(mock_service, "test query", test_db)
        assert len(emails) == 1
        assert emails[0].message_id == "new_msg"

    def test_fetch_emails_handles_pagination(self, test_db: Path) -> None:
        """fetch_emails follows nextPageToken for pagination."""
        mock_service = MagicMock()
        list_mock = mock_service.users.return_value.messages.return_value.list.return_value

        # First page with nextPageToken
        list_mock.execute.side_effect = [
            {"messages": [{"id": "msg1"}], "nextPageToken": "page2"},
            {"messages": [{"id": "msg2"}]},
        ]

        plain_data = base64.urlsafe_b64encode(b"body").decode()
        get_result = mock_service.users.return_value.messages.return_value.get.return_value
        get_result.execute.return_value = {
            "payload": {
                "headers": [
                    {"name": "Date", "value": "2026-01-15"},
                    {"name": "From", "value": "test@test.com"},
                    {"name": "Subject", "value": "Test"},
                ],
                "mimeType": "text/plain",
                "body": {"data": plain_data},
            }
        }

        emails = fetch_emails(mock_service, "test", test_db)
        assert len(emails) == 2

    def test_fetch_emails_handles_message_fetch_error(self, test_db: Path) -> None:
        """fetch_emails gracefully skips messages that fail to fetch."""
        mock_service = MagicMock()
        list_result = mock_service.users.return_value.messages.return_value.list.return_value
        list_result.execute.return_value = {
            "messages": [{"id": "bad_msg"}, {"id": "good_msg"}],
        }

        plain_data = base64.urlsafe_b64encode(b"body").decode()
        get_mock = mock_service.users.return_value.messages.return_value.get.return_value
        get_mock.execute.side_effect = [
            Exception("API error"),
            {
                "payload": {
                    "headers": [
                        {"name": "Date", "value": "2026-01-15"},
                        {"name": "From", "value": "test@test.com"},
                        {"name": "Subject", "value": "Test"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": plain_data},
                }
            },
        ]

        emails = fetch_emails(mock_service, "test", test_db)
        assert len(emails) == 1
        assert emails[0].message_id == "good_msg"


# ---------------------------------------------------------------------------
# TestGmailRoutes
# ---------------------------------------------------------------------------


class TestGmailRoutes:
    """Tests for app/routes/gmail.py — multi-account web routes."""

    def test_accounts_requires_auth(self, client: TestClient) -> None:
        """/gmail/accounts redirects to /login when unauthenticated."""
        response = client.get("/gmail/accounts", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_accounts_shows_account_list(self, client: TestClient) -> None:
        """/gmail/accounts shows the default account."""
        login(client)
        response = client.get("/gmail/accounts")
        assert response.status_code == 200
        assert "Gmail" in response.text  # default account label
        assert "Not connected" in response.text

    @patch("app.routes.gmail.is_connected", return_value=True)
    def test_accounts_shows_connected(self, mock_conn: MagicMock, client: TestClient) -> None:
        """/gmail/accounts shows 'Connected' when token exists."""
        login(client)
        response = client.get("/gmail/accounts")
        assert response.status_code == 200
        assert "Connected" in response.text
        assert "Disconnect" in response.text

    def test_connect_redirects_to_accounts(self, client: TestClient) -> None:
        """/gmail/connect redirects to /gmail/accounts (backward compat)."""
        login(client)
        response = client.get("/gmail/connect", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/gmail/accounts"

    def test_authorize_requires_auth(self, client: TestClient) -> None:
        """/gmail/{account_id}/authorize redirects to /login when unauthenticated."""
        response = client.get("/gmail/default/authorize", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_authorize_unknown_account(self, client: TestClient) -> None:
        """/gmail/{account_id}/authorize rejects unknown account."""
        login(client)
        response = client.get("/gmail/nonexistent/authorize", follow_redirects=False)
        assert response.status_code == 303
        assert "error=" in response.headers["location"]
        assert "Unknown" in response.headers["location"]

    def test_authorize_missing_credentials_shows_error(self, client: TestClient) -> None:
        """/gmail/{account_id}/authorize shows error when credentials.json is missing."""
        login(client)
        response = client.get("/gmail/default/authorize", follow_redirects=False)
        assert response.status_code == 303
        assert "error=" in response.headers["location"]
        assert "credentials" in response.headers["location"].lower()

    @patch("app.routes.gmail.create_auth_flow")
    def test_authorize_redirects_to_google(
        self, mock_flow_fn: MagicMock, client: TestClient
    ) -> None:
        """/gmail/{account_id}/authorize redirects to Google with JSON state cookie."""
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth?state=test_state",
            "test_state",
        )
        mock_flow_fn.return_value = mock_flow

        login(client)
        response = client.get("/gmail/default/authorize", follow_redirects=False)
        assert response.status_code == 303
        assert "accounts.google.com" in response.headers["location"]
        assert "oauth_state" in response.cookies

        # Verify cookie contains state|account_id
        cookie_value = response.cookies["oauth_state"]
        assert "test_state" in cookie_value
        assert "default" in cookie_value

    def test_callback_requires_auth(self, client: TestClient) -> None:
        """/gmail/callback redirects to /login when unauthenticated."""
        response = client.get("/gmail/callback", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_callback_validates_state_mismatch(self, client: TestClient) -> None:
        """/gmail/callback rejects state mismatch (CSRF protection)."""
        login(client)
        client.cookies.set("oauth_state", "expected_state|default")
        response = client.get(
            "/gmail/callback?state=wrong_state&code=auth_code",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "state+mismatch" in response.headers["location"]

    def test_callback_handles_invalid_state_cookie(self, client: TestClient) -> None:
        """/gmail/callback handles state cookie without pipe separator."""
        login(client)
        client.cookies.set("oauth_state", "no-pipe-separator")
        response = client.get(
            "/gmail/callback?state=test&code=auth_code",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "invalid+state" in response.headers["location"]

    def test_callback_handles_error_from_google(self, client: TestClient) -> None:
        """/gmail/callback handles error param from Google."""
        login(client)
        response = client.get(
            "/gmail/callback?error=access_denied",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "denied" in response.headers["location"].lower()

    @patch("app.routes.gmail.exchange_code_for_credentials")
    @patch("app.routes.gmail.create_auth_flow")
    def test_callback_success(
        self,
        mock_flow_fn: MagicMock,
        mock_exchange: MagicMock,
        client: TestClient,
    ) -> None:
        """/gmail/callback exchanges code and redirects with success."""
        mock_flow = MagicMock()
        mock_flow_fn.return_value = mock_flow
        mock_exchange.return_value = MagicMock()

        login(client)
        client.cookies.set("oauth_state", "valid_state|default")
        response = client.get(
            "/gmail/callback?state=valid_state&code=auth_code",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "success=" in response.headers["location"]
        mock_exchange.assert_called_once()

    def test_disconnect_requires_auth(self, client: TestClient) -> None:
        """/gmail/{account_id}/disconnect redirects to /login when unauthenticated."""
        response = client.get("/gmail/default/disconnect", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_disconnect_unknown_account(self, client: TestClient) -> None:
        """/gmail/{account_id}/disconnect rejects unknown account."""
        login(client)
        response = client.get("/gmail/nonexistent/disconnect", follow_redirects=False)
        assert response.status_code == 303
        assert "error=" in response.headers["location"]

    def test_disconnect_removes_token(self, client: TestClient) -> None:
        """/gmail/{account_id}/disconnect removes the token file."""
        settings = client.app.state.settings  # type: ignore[attr-defined]
        acct = settings.gmail.accounts[0]
        token_path = Path(acct.token_path)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("{}")

        login(client)
        response = client.get(f"/gmail/{acct.id}/disconnect", follow_redirects=False)
        assert response.status_code == 303
        assert "success=" in response.headers["location"]
        assert not token_path.exists()
