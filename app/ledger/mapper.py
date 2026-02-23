"""Merchant-to-hledger-account mapper.

Resolves a payee name + direction to an hledger account string.
Priority:
  1. SQLite merchant_mappings table (exact match, case-insensitive)
  2. Substring containment (longest pattern wins)
  3. Direction-based default (sent -> expenses, received -> income)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.db.models import get_connection

logger = logging.getLogger(__name__)


def map_merchant(payee: str, direction: str, db_path: Path) -> str:
    """Resolve a payee to an hledger account.

    Checks merchant_mappings table first (case-insensitive), then
    falls back to direction-based default accounts.

    Args:
        payee: The sanitized payee/merchant name.
        direction: "sent" or "received".
        db_path: Path to the SQLite database.

    Returns:
        An hledger account string (e.g. "expenses:food:delivery").
    """
    conn = get_connection(db_path)
    try:
        # Exact case-insensitive match first
        row = conn.execute(
            "SELECT account FROM merchant_mappings "
            "WHERE LOWER(merchant_pattern) = LOWER(?) LIMIT 1",
            (payee,),
        ).fetchone()
        if row is not None:
            logger.info("Merchant mapping matched (exact)")
            return str(row["account"])

        # Substring pattern match (merchant_pattern contained in payee)
        row = conn.execute(
            "SELECT account FROM merchant_mappings "
            "WHERE INSTR(LOWER(?), LOWER(merchant_pattern)) > 0 "
            "ORDER BY LENGTH(merchant_pattern) DESC LIMIT 1",
            (payee,),
        ).fetchone()
        if row is not None:
            logger.info("Merchant mapping matched (substring)")
            return str(row["account"])
    finally:
        conn.close()

    if direction == "received":
        return "income:miscellaneous"
    return "expenses:miscellaneous"


def save_merchant_mapping(
    db_path: Path,
    merchant_pattern: str,
    account: str,
) -> None:
    """Save or update a merchant -> account mapping.

    Uses INSERT OR REPLACE so re-mapping a known merchant overwrites
    the previous account assignment.
    """
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO merchant_mappings "
            "(merchant_pattern, account, created_at) VALUES (?, ?, ?)",
            (merchant_pattern, account, datetime.now(tz=UTC).isoformat()),
        )
        conn.commit()
        logger.info("Merchant mapping saved")
    finally:
        conn.close()
