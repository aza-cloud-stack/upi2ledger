"""Gmail email fetcher with deduplication.

Fetches UPI transaction emails via the Gmail API, skipping messages
that have already been processed (tracked in SQLite).
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.db.models import fetch_all, get_connection

logger = logging.getLogger(__name__)


class EmailMessage(BaseModel):
    """A fetched email message with decoded content."""

    message_id: str
    date: str
    sender: str
    subject: str
    body: str


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    """Extract a header value from Gmail message headers by name."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def _decode_body(payload: dict[str, object]) -> str:
    """Decode the email body from a Gmail message payload.

    Prefers text/plain, falls back to text/html, handles nested multipart.
    """
    mime_type = payload.get("mimeType", "")

    # Direct body (non-multipart)
    if isinstance(mime_type, str) and not mime_type.startswith("multipart/"):
        body = payload.get("body", {})
        if isinstance(body, dict):
            data = body.get("data", "")
            if isinstance(data, str) and data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    # Multipart — recurse into parts
    parts = payload.get("parts", [])
    if not isinstance(parts, list):
        return ""

    plain_text = ""
    html_text = ""

    for part in parts:
        if not isinstance(part, dict):
            continue
        part_mime = part.get("mimeType", "")

        if isinstance(part_mime, str) and part_mime.startswith("multipart/"):
            # Nested multipart — recurse
            result = _decode_body(part)
            if result:
                return result
        elif part_mime == "text/plain":
            body = part.get("body", {})
            if isinstance(body, dict):
                data = body.get("data", "")
                if isinstance(data, str) and data:
                    plain_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif part_mime == "text/html":
            body = part.get("body", {})
            if isinstance(body, dict):
                data = body.get("data", "")
                if isinstance(data, str) and data:
                    html_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return plain_text or html_text


def _get_processed_ids(db_path: Path, account_id: str = "default") -> set[str]:
    """Fetch processed message IDs for a specific account from the database."""
    conn = get_connection(db_path)
    try:
        rows = fetch_all(
            conn,
            "SELECT message_id FROM processed_emails WHERE account_id = ?",
            (account_id,),
        )
        return {row["message_id"] for row in rows}
    finally:
        conn.close()


def fetch_emails(
    service: Any,
    query: str,
    db_path: Path,
    account_id: str = "default",
    max_results: int = 500,
) -> list[EmailMessage]:
    """Fetch emails matching query, skipping already-processed messages.

    Args:
        service: Authenticated Gmail API service.
        query: Gmail search query string.
        db_path: Path to the SQLite database.
        account_id: Gmail account identifier for dedup scoping.
        max_results: Maximum number of messages to fetch.

    Returns:
        List of new (unprocessed) EmailMessage objects.
    """
    processed_ids = _get_processed_ids(db_path, account_id)
    messages: list[EmailMessage] = []
    page_token: str | None = None

    while len(messages) < max_results:
        # List message IDs
        list_kwargs: dict[str, object] = {
            "userId": "me",
            "q": query,
            "maxResults": min(100, max_results - len(messages)),
        }
        if page_token:
            list_kwargs["pageToken"] = page_token

        results = service.users().messages().list(**list_kwargs).execute()

        message_refs = results.get("messages", [])
        if not message_refs:
            break

        for ref in message_refs:
            msg_id = ref["id"]

            # Skip already-processed
            if msg_id in processed_ids:
                continue

            # Fetch full message
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg_id, format="full")
                    .execute()
                )
            except Exception:
                logger.info("Failed to fetch message %s, skipping", msg_id)
                continue

            headers = msg.get("payload", {}).get("headers", [])
            payload = msg.get("payload", {})

            email = EmailMessage(
                message_id=msg_id,
                date=_get_header(headers, "Date"),
                sender=_get_header(headers, "From"),
                subject=_get_header(headers, "Subject"),
                body=_decode_body(payload),
            )
            messages.append(email)

            if len(messages) >= max_results:
                break

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    logger.info("Fetched %d new emails", len(messages))
    return messages


def mark_as_processed(
    db_path: Path, message_id: str, parser_source: str, account_id: str = "default",
) -> None:
    """Mark an email as processed in the database (INSERT OR IGNORE for dedup)."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO processed_emails "
            "(message_id, processed_at, parser_source, account_id) VALUES (?, ?, ?, ?)",
            (message_id, datetime.now(tz=UTC).isoformat(), parser_source, account_id),
        )
        conn.commit()
    finally:
        conn.close()


def is_processed(db_path: Path, message_id: str, account_id: str = "default") -> bool:
    """Check if a message ID has already been processed for a specific account."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT 1 FROM processed_emails WHERE message_id = ? AND account_id = ?",
            (message_id, account_id),
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()
