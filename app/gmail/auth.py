"""Gmail OAuth2 flow and token management.

Handles the Google OAuth2 authorization flow, secure token storage,
credential refresh, and Gmail API service construction.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Only request read-only access to Gmail — hardcoded, never configurable.
SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]


def _write_token_secure(token_path: Path, creds: Credentials) -> None:
    """Write OAuth2 token JSON with restricted file permissions (0o600).

    Uses os.open to set permissions atomically — no race condition window
    where the file exists with broader permissions.
    """
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else list(SCOPES),
    }
    token_json = json.dumps(token_data)

    token_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(token_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token_json.encode("utf-8"))
    finally:
        os.close(fd)

    logger.info("Gmail token saved securely")


def load_credentials(token_path: Path) -> Credentials | None:
    """Load saved OAuth2 credentials from disk.

    Auto-refreshes if expired. Returns None if no token file exists,
    the token is invalid, or refresh fails.
    """
    if not token_path.exists():
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except (json.JSONDecodeError, ValueError, KeyError):
        logger.info("Gmail token file invalid, removing")
        token_path.unlink(missing_ok=True)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
            _write_token_secure(token_path, creds)
            logger.info("Gmail token refreshed")
            return creds
        except RefreshError:
            logger.info("Gmail token refresh failed")
            token_path.unlink(missing_ok=True)
            return None

    return None


def create_auth_flow(credentials_path: Path, redirect_uri: str) -> Flow:
    """Create an OAuth2 flow for web-based authorization.

    Raises:
        FileNotFoundError: If credentials_path does not exist.
    """
    if not credentials_path.exists():
        msg = (
            f"Gmail credentials file not found: {credentials_path} — "
            "download OAuth2 credentials from GCP Console"
        )
        raise FileNotFoundError(msg)

    flow = Flow.from_client_secrets_file(
        str(credentials_path),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    return flow


def exchange_code_for_credentials(flow: Flow, code: str, token_path: Path) -> Credentials:
    """Exchange the authorization code for credentials and save them securely."""
    flow.fetch_token(code=code)
    creds = flow.credentials
    _write_token_secure(token_path, creds)
    logger.info("Gmail authorization completed")
    return creds


def get_gmail_service(creds: Credentials) -> Any:
    """Build an authenticated Gmail API service."""
    return build("gmail", "v1", credentials=creds)


def is_connected(token_path: Path) -> bool:
    """Return True if a valid Gmail token exists."""
    return load_credentials(token_path) is not None
