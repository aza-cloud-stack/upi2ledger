"""Tests for app.ledger.writer — journal formatting and file writing."""

from __future__ import annotations

import os
import stat
from decimal import Decimal
from pathlib import Path

import pytest

from app.ledger.writer import format_inr, format_transaction, write_entries


class TestFormatInr:
    """Tests for Indian numbering format."""

    def test_small_amount(self) -> None:
        assert format_inr(Decimal("500")) == "₹ 500.00"

    def test_thousands(self) -> None:
        assert format_inr(Decimal("1000")) == "₹ 1,000.00"

    def test_ten_thousand(self) -> None:
        assert format_inr(Decimal("10000")) == "₹ 10,000.00"

    def test_lakhs(self) -> None:
        assert format_inr(Decimal("100000")) == "₹ 1,00,000.00"

    def test_ten_lakhs(self) -> None:
        assert format_inr(Decimal("1000000")) == "₹ 10,00,000.00"

    def test_with_decimals(self) -> None:
        assert format_inr(Decimal("1234567.89")) == "₹ 12,34,567.89"

    def test_small_with_paise(self) -> None:
        assert format_inr(Decimal("99.50")) == "₹ 99.50"

    def test_exact_hundred(self) -> None:
        assert format_inr(Decimal("100")) == "₹ 100.00"

    def test_under_ten(self) -> None:
        assert format_inr(Decimal("5")) == "₹ 5.00"

    def test_rounds_to_two_decimals(self) -> None:
        assert format_inr(Decimal("500.999")) == "₹ 501.00"

    def test_single_rupee(self) -> None:
        assert format_inr(Decimal("1")) == "₹ 1.00"


class TestFormatTransaction:
    """Tests for hledger journal entry formatting."""

    def test_expense_entry(self) -> None:
        """Sent transaction generates expense entry."""
        entry = format_transaction(
            date="2026-02-23",
            payee="Swiggy",
            amount=Decimal("500"),
            direction="sent",
            expense_account="expenses:food:delivery",
            payment_account="assets:bank:sbi:savings",
        )
        assert "2026-02-23 * Swiggy" in entry
        assert "    expenses:food:delivery    ₹ 500.00" in entry
        assert "    assets:bank:sbi:savings" in entry

    def test_income_entry(self) -> None:
        """Received transaction generates income entry."""
        entry = format_transaction(
            date="2026-02-23",
            payee="John",
            amount=Decimal("1000"),
            direction="received",
            expense_account="income:miscellaneous",
            payment_account="assets:bank:sbi:savings",
        )
        assert "2026-02-23 * John" in entry
        assert "    assets:bank:sbi:savings    ₹ 1,000.00" in entry
        assert "    income:miscellaneous" in entry

    def test_upi_ref_as_comment(self) -> None:
        """UPI ref is added as a comment on the header line."""
        entry = format_transaction(
            date="2026-02-23",
            payee="Swiggy",
            amount=Decimal("500"),
            direction="sent",
            expense_account="expenses:food:delivery",
            payment_account="assets:bank:sbi:savings",
            upi_ref="402012345678",
        )
        assert "; UPI Ref: 402012345678" in entry

    def test_no_upi_ref_no_comment(self) -> None:
        """No UPI ref means no comment on header."""
        entry = format_transaction(
            date="2026-02-23",
            payee="Swiggy",
            amount=Decimal("500"),
            direction="sent",
            expense_account="expenses:food:delivery",
            payment_account="assets:bank:sbi:savings",
        )
        assert ";" not in entry

    def test_invalid_expense_account_raises(self) -> None:
        """Invalid account name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid expense account"):
            format_transaction(
                date="2026-02-23",
                payee="Test",
                amount=Decimal("100"),
                direction="sent",
                expense_account="INVALID ACCOUNT",
                payment_account="assets:bank:sbi:savings",
            )

    def test_invalid_payment_account_raises(self) -> None:
        """Invalid payment account raises ValueError."""
        with pytest.raises(ValueError, match="Invalid payment account"):
            format_transaction(
                date="2026-02-23",
                payee="Test",
                amount=Decimal("100"),
                direction="sent",
                expense_account="expenses:food",
                payment_account="INVALID",
            )

    def test_trailing_newline(self) -> None:
        """Entry ends with trailing newline for hledger convention."""
        entry = format_transaction(
            date="2026-02-23",
            payee="Test",
            amount=Decimal("100"),
            direction="sent",
            expense_account="expenses:miscellaneous",
            payment_account="assets:bank:sbi:savings",
        )
        assert entry.endswith("\n")

    def test_blank_line_between_entries(self) -> None:
        """Entry ends with blank line + newline (hledger convention)."""
        entry = format_transaction(
            date="2026-02-23",
            payee="Test",
            amount=Decimal("100"),
            direction="sent",
            expense_account="expenses:miscellaneous",
            payment_account="assets:bank:sbi:savings",
        )
        # Should end with an empty line (for spacing between entries)
        assert entry.endswith("\n\n")


class TestWriteEntries:
    """Tests for journal file writing."""

    def test_creates_new_file(self, tmp_path: Path) -> None:
        """write_entries creates a new journal file."""
        journal_path = str(tmp_path / "test.journal")
        count = write_entries(["entry1\n", "entry2\n"], journal_path)
        assert count == 2
        path = Path(journal_path)
        assert path.exists()
        content = path.read_text()
        assert "entry1" in content
        assert "entry2" in content

    def test_file_permissions_600(self, tmp_path: Path) -> None:
        """New journal file has 0o600 permissions."""
        journal_path = str(tmp_path / "test.journal")
        write_entries(["entry\n"], journal_path)
        mode = stat.S_IMODE(os.stat(journal_path).st_mode)
        assert mode == 0o600

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        """write_entries appends to an existing journal file."""
        journal_path = str(tmp_path / "test.journal")
        write_entries(["first\n"], journal_path)
        write_entries(["second\n"], journal_path)
        content = Path(journal_path).read_text()
        assert "first" in content
        assert "second" in content

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """write_entries creates parent directories if missing."""
        journal_path = str(tmp_path / "sub" / "dir" / "test.journal")
        write_entries(["entry\n"], journal_path)
        assert Path(journal_path).exists()

    def test_expands_tilde(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """write_entries expands ~ in the path."""
        monkeypatch.setenv("HOME", str(tmp_path))
        write_entries(["entry\n"], "~/test.journal")
        assert (tmp_path / "test.journal").exists()

    def test_empty_entries_returns_zero(self, tmp_path: Path) -> None:
        """write_entries returns 0 for empty list."""
        assert write_entries([], str(tmp_path / "nope.journal")) == 0
