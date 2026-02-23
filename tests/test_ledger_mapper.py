"""Tests for app.ledger.mapper — merchant-to-account mapping."""

from __future__ import annotations

from pathlib import Path

from app.db.models import get_connection
from app.ledger.mapper import map_merchant, save_merchant_mapping


class TestMapMerchant:
    """Tests for map_merchant lookup logic."""

    def test_exact_match(self, test_db: Path) -> None:
        """Exact payee match returns correct account."""
        save_merchant_mapping(test_db, "Swiggy", "expenses:food:delivery")
        assert map_merchant("Swiggy", "sent", test_db) == "expenses:food:delivery"

    def test_case_insensitive_match(self, test_db: Path) -> None:
        """Matching is case-insensitive."""
        save_merchant_mapping(test_db, "Swiggy", "expenses:food:delivery")
        assert map_merchant("swiggy", "sent", test_db) == "expenses:food:delivery"

    def test_substring_match(self, test_db: Path) -> None:
        """Substring pattern match works for longer payee names."""
        save_merchant_mapping(test_db, "Swiggy", "expenses:food:delivery")
        assert map_merchant("Swiggy Ltd", "sent", test_db) == "expenses:food:delivery"

    def test_longest_pattern_wins(self, test_db: Path) -> None:
        """When multiple patterns match, the longest one wins."""
        save_merchant_mapping(test_db, "Amazon", "expenses:shopping")
        save_merchant_mapping(test_db, "Amazon Prime", "expenses:entertainment:subscriptions")
        result = map_merchant("Amazon Prime Video", "sent", test_db)
        assert result == "expenses:entertainment:subscriptions"

    def test_default_sent_no_match(self, test_db: Path) -> None:
        """No match with direction=sent returns expenses:miscellaneous."""
        assert map_merchant("Unknown Merchant", "sent", test_db) == "expenses:miscellaneous"

    def test_default_received_no_match(self, test_db: Path) -> None:
        """No match with direction=received returns income:miscellaneous."""
        assert map_merchant("Unknown Sender", "received", test_db) == "income:miscellaneous"


class TestSaveMerchantMapping:
    """Tests for save_merchant_mapping."""

    def test_saves_new_mapping(self, test_db: Path) -> None:
        """save_merchant_mapping creates a new row."""
        save_merchant_mapping(test_db, "Zomato", "expenses:food:delivery")
        conn = get_connection(test_db)
        try:
            row = conn.execute(
                "SELECT account FROM merchant_mappings WHERE merchant_pattern = ?",
                ("Zomato",),
            ).fetchone()
            assert row is not None
            assert row["account"] == "expenses:food:delivery"
        finally:
            conn.close()

    def test_replaces_existing_mapping(self, test_db: Path) -> None:
        """save_merchant_mapping overwrites existing mapping for same pattern."""
        save_merchant_mapping(test_db, "Zomato", "expenses:food:delivery")
        save_merchant_mapping(test_db, "Zomato", "expenses:food:dining")
        conn = get_connection(test_db)
        try:
            rows = conn.execute(
                "SELECT account FROM merchant_mappings WHERE merchant_pattern = ?",
                ("Zomato",),
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["account"] == "expenses:food:dining"
        finally:
            conn.close()
