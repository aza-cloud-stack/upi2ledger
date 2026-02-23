"""Merchant-to-hledger-account mapper.

Resolves a payee name + direction to an hledger account string.
Priority:
  1. SQLite merchant_mappings table (exact match, case-insensitive)
  2. SQLite substring containment (longest pattern wins)
  3. Built-in rules for common Indian merchants (longest key wins)
  4. Direction-based default (sent -> expenses, received -> income)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.db.models import get_connection, get_pending_transactions
from app.ledger.rules import BUILTIN_RULES

logger = logging.getLogger(__name__)


def _match_builtin_rules(payee: str) -> str | None:
    """Match payee against built-in merchant rules.

    Finds all rules where the key is a substring of the payee (case-insensitive),
    then returns the account for the longest matching key. Returns None if no match.
    """
    payee_lower = payee.lower()
    best_match: str | None = None
    best_length = 0

    for pattern, account in BUILTIN_RULES.items():
        if pattern in payee_lower and len(pattern) > best_length:
            best_match = account
            best_length = len(pattern)

    return best_match


def map_merchant(payee: str, direction: str, db_path: Path) -> str:
    """Resolve a payee to an hledger account.

    Checks merchant_mappings table first (case-insensitive), then
    built-in rules for common Indian merchants, then falls back to
    direction-based default accounts.

    Args:
        payee: The sanitized payee/merchant name.
        direction: "sent" or "received".
        db_path: Path to the SQLite database.

    Returns:
        An hledger account string (e.g. "expenses:food:delivery").
    """
    conn = get_connection(db_path)
    try:
        # 1. Exact case-insensitive match (user-saved mappings)
        row = conn.execute(
            "SELECT account FROM merchant_mappings "
            "WHERE LOWER(merchant_pattern) = LOWER(?) LIMIT 1",
            (payee,),
        ).fetchone()
        if row is not None:
            logger.info("Merchant mapping matched (exact)")
            return str(row["account"])

        # 2. Substring pattern match (merchant_pattern contained in payee)
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

    # 3. Built-in rules for common Indian merchants
    builtin = _match_builtin_rules(payee)
    if builtin is not None:
        logger.info("Merchant matched built-in rule")
        return builtin

    # 4. Direction-based fallback
    if direction == "received":
        return "income:miscellaneous"
    return "expenses:miscellaneous"


def remap_pending_transactions(db_path: Path) -> int:
    """Re-evaluate suggested_account for all pending transactions.

    Reads all pending transactions, runs map_merchant() on each, and
    updates any whose suggested_account has changed. This picks up
    newly saved DB mappings and built-in rules.

    Returns:
        Number of transactions whose suggested_account was updated.
    """
    conn = get_connection(db_path)
    try:
        rows = get_pending_transactions(conn, status="pending", limit=10000)
    finally:
        conn.close()

    updated = 0
    update_conn = get_connection(db_path)
    try:
        for row in rows:
            new_account = map_merchant(row["payee"], row["direction"], db_path)
            if new_account != row["suggested_account"]:
                update_conn.execute(
                    "UPDATE pending_transactions SET suggested_account = ? " "WHERE id = ?",
                    (new_account, row["id"]),
                )
                updated += 1
        if updated > 0:
            update_conn.commit()
            logger.info("Remapped %d pending transactions", updated)
    finally:
        update_conn.close()

    return updated


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
