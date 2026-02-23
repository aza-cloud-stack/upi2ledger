"""Tests for app.ledger.rules — built-in merchant rule validation."""

from __future__ import annotations

import re

from app.ledger.rules import BUILTIN_RULES

# Valid hledger account pattern (same as writer.py)
_ACCOUNT_RE = re.compile(r"^[a-z][a-z0-9:_-]*$")


class TestBuiltinRulesStructure:
    """Validate the BUILTIN_RULES dictionary is well-formed."""

    def test_not_empty(self) -> None:
        """Rules dict should have entries."""
        assert len(BUILTIN_RULES) > 0

    def test_keys_are_lowercase(self) -> None:
        """All keys must be lowercase for case-insensitive matching."""
        for key in BUILTIN_RULES:
            assert key == key.lower(), f"Key {key!r} is not lowercase"

    def test_values_are_valid_account_names(self) -> None:
        """All values must be valid hledger account names."""
        for key, account in BUILTIN_RULES.items():
            assert _ACCOUNT_RE.match(
                account
            ), f"Account {account!r} for key {key!r} is not a valid hledger account"

    def test_no_empty_keys_or_values(self) -> None:
        """No empty strings in keys or values."""
        for key, value in BUILTIN_RULES.items():
            assert key.strip(), "Found empty key"
            assert value.strip(), f"Found empty value for key {key!r}"
