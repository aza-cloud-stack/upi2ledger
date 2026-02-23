"""Tests for app.ledger.mapper — merchant-to-account mapping."""

from __future__ import annotations

from pathlib import Path

from app.db.models import get_connection, insert_pending_transaction
from app.ledger.mapper import (
    _match_builtin_rules,
    map_merchant,
    remap_pending_transactions,
    save_merchant_mapping,
)


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


class TestBuiltinRules:
    """Tests for built-in rule matching in map_merchant."""

    def test_builtin_rule_matches(self, test_db: Path) -> None:
        """Known merchant matches built-in rule when no DB mapping exists."""
        assert map_merchant("Swiggy Ltd", "sent", test_db) == "expenses:food:delivery"

    def test_builtin_case_insensitive(self, test_db: Path) -> None:
        """Built-in rules match case-insensitively."""
        assert map_merchant("AIRTEL BHARTI", "sent", test_db) == "expenses:telecom"

    def test_builtin_longest_key_wins(self, test_db: Path) -> None:
        """When multiple built-in rules match, the longest key wins."""
        # "bharat petroleum" (17 chars) should beat shorter matches
        result = _match_builtin_rules("Bharat Petroleum Corp")
        assert result == "expenses:transport:fuel"

    def test_db_mapping_overrides_builtin(self, test_db: Path) -> None:
        """User-saved DB mapping takes priority over built-in rules."""
        # Built-in maps "swiggy" to expenses:food:delivery
        save_merchant_mapping(test_db, "Swiggy", "expenses:food:dining")
        assert map_merchant("Swiggy", "sent", test_db) == "expenses:food:dining"

    def test_unknown_merchant_still_falls_back(self, test_db: Path) -> None:
        """Merchant not in DB or built-in rules falls back to direction default."""
        assert map_merchant("Some Random Shop XYZ", "sent", test_db) == "expenses:miscellaneous"

    def test_match_builtin_returns_none_for_unknown(self) -> None:
        """_match_builtin_rules returns None for unknown merchant."""
        assert _match_builtin_rules("Totally Unknown Corp") is None


class TestRemapPendingTransactions:
    """Tests for remap_pending_transactions bulk update."""

    def _insert(self, test_db: Path, payee: str, suggested: str) -> int:
        """Insert a pending transaction and return its ID."""
        conn = get_connection(test_db)
        try:
            row_id = insert_pending_transaction(
                conn,
                date="2026-02-23",
                amount="500.00",
                payee=payee,
                direction="sent",
                source="gpay",
                upi_ref="402012345678",
                email_message_id=f"msg-{payee.lower().replace(' ', '-')}",
                confidence=1.0,
                suggested_account=suggested,
            )
            conn.commit()
            return row_id
        finally:
            conn.close()

    def test_remap_updates_miscellaneous_to_builtin(self, test_db: Path) -> None:
        """Remap updates transactions with fallback accounts to built-in rules."""
        self._insert(test_db, "Swiggy Ltd", "expenses:miscellaneous")
        updated = remap_pending_transactions(test_db)
        assert updated == 1

        conn = get_connection(test_db)
        try:
            row = conn.execute(
                "SELECT suggested_account FROM pending_transactions WHERE payee = ?",
                ("Swiggy Ltd",),
            ).fetchone()
            assert row is not None
            assert row["suggested_account"] == "expenses:food:delivery"
        finally:
            conn.close()

    def test_remap_uses_db_mapping_over_builtin(self, test_db: Path) -> None:
        """Remap picks up newly saved DB mappings."""
        self._insert(test_db, "Swiggy", "expenses:miscellaneous")
        save_merchant_mapping(test_db, "Swiggy", "expenses:food:dining")
        updated = remap_pending_transactions(test_db)
        assert updated == 1

        conn = get_connection(test_db)
        try:
            row = conn.execute(
                "SELECT suggested_account FROM pending_transactions WHERE payee = ?",
                ("Swiggy",),
            ).fetchone()
            assert row is not None
            assert row["suggested_account"] == "expenses:food:dining"
        finally:
            conn.close()

    def test_remap_skips_already_correct(self, test_db: Path) -> None:
        """Remap does not update transactions that already have the correct account."""
        self._insert(test_db, "Swiggy", "expenses:food:delivery")
        updated = remap_pending_transactions(test_db)
        assert updated == 0

    def test_remap_returns_count(self, test_db: Path) -> None:
        """Remap returns the number of updated transactions."""
        self._insert(test_db, "Swiggy", "expenses:miscellaneous")
        self._insert(test_db, "Zomato Order", "expenses:miscellaneous")
        self._insert(test_db, "Unknown Vendor", "expenses:miscellaneous")
        updated = remap_pending_transactions(test_db)
        # Swiggy and Zomato match built-in rules, Unknown does not
        assert updated == 2
