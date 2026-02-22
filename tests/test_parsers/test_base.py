"""Tests for app/parser/base.py — ParsedTransaction model and helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.parser.base import (
    ParsedTransaction,
    extract_upi_ref,
    parse_amount,
    parse_email_date,
    sanitize_payee,
)


def _make_transaction(**overrides: object) -> ParsedTransaction:
    """Build a valid ParsedTransaction with defaults, overriding specified fields."""
    defaults: dict[str, object] = {
        "date": date(2026, 2, 20),
        "amount": Decimal("500"),
        "payee": "Swiggy",
        "direction": "sent",
        "source": "gpay",
        "upi_ref": "402012345678",
        "email_message_id": "msg-001",
        "confidence": 1.0,
        "suggested_account": None,
    }
    defaults.update(overrides)
    return ParsedTransaction(**defaults)  # type: ignore[arg-type]


class TestParsedTransaction:
    """Validation tests for the ParsedTransaction Pydantic model."""

    def test_valid_transaction(self) -> None:
        """A well-formed transaction passes validation."""
        tx = _make_transaction()
        assert tx.amount == Decimal("500")
        assert tx.payee == "Swiggy"
        assert tx.direction == "sent"

    def test_negative_amount_rejected(self) -> None:
        """Negative amounts are rejected."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            _make_transaction(amount=Decimal("-100"))

    def test_zero_amount_rejected(self) -> None:
        """Zero amount is rejected."""
        with pytest.raises(ValueError, match="Amount must be positive"):
            _make_transaction(amount=Decimal("0"))

    def test_amount_exceeds_max_rejected(self) -> None:
        """Amount over 10,00,000 is rejected."""
        with pytest.raises(ValueError, match="Amount exceeds maximum"):
            _make_transaction(amount=Decimal("1000001"))

    def test_amount_at_max_accepted(self) -> None:
        """Exactly ₹10,00,000 is accepted."""
        tx = _make_transaction(amount=Decimal("1000000"))
        assert tx.amount == Decimal("1000000")

    def test_small_amount_accepted(self) -> None:
        """₹0.50 (50 paise) is valid."""
        tx = _make_transaction(amount=Decimal("0.50"))
        assert tx.amount == Decimal("0.50")

    def test_empty_payee_rejected(self) -> None:
        """Empty payee string is rejected."""
        with pytest.raises(ValueError, match="Payee must not be empty"):
            _make_transaction(payee="")

    def test_whitespace_only_payee_rejected(self) -> None:
        """Whitespace-only payee is rejected."""
        with pytest.raises(ValueError, match="Payee must not be empty"):
            _make_transaction(payee="   ")

    def test_payee_truncated_at_200(self) -> None:
        """Payee longer than 200 chars is truncated."""
        long_name = "A" * 250
        tx = _make_transaction(payee=long_name)
        assert len(tx.payee) == 200

    def test_confidence_below_zero_rejected(self) -> None:
        """Confidence < 0.0 is rejected."""
        with pytest.raises(ValueError, match="Confidence must be between"):
            _make_transaction(confidence=-0.1)

    def test_confidence_above_one_rejected(self) -> None:
        """Confidence > 1.0 is rejected."""
        with pytest.raises(ValueError, match="Confidence must be between"):
            _make_transaction(confidence=1.1)

    def test_confidence_boundary_values(self) -> None:
        """Confidence 0.0 and 1.0 are accepted."""
        tx_zero = _make_transaction(confidence=0.0)
        assert tx_zero.confidence == 0.0
        tx_one = _make_transaction(confidence=1.0)
        assert tx_one.confidence == 1.0

    def test_invalid_account_name_rejected(self) -> None:
        """Account name with spaces or uppercase is rejected."""
        with pytest.raises(ValueError, match="Account name must be"):
            _make_transaction(suggested_account="Expenses:Food")

    def test_account_name_with_spaces_rejected(self) -> None:
        """Account name with spaces is rejected."""
        with pytest.raises(ValueError, match="Account name must be"):
            _make_transaction(suggested_account="expenses food")

    def test_valid_account_name_accepted(self) -> None:
        """Account name like 'expenses:food:delivery' passes."""
        tx = _make_transaction(suggested_account="expenses:food:delivery")
        assert tx.suggested_account == "expenses:food:delivery"

    def test_account_name_with_dash_accepted(self) -> None:
        """Account name with dashes passes."""
        tx = _make_transaction(suggested_account="assets:bank:hdfc-savings")
        assert tx.suggested_account == "assets:bank:hdfc-savings"

    def test_none_account_name_accepted(self) -> None:
        """None suggested_account is accepted."""
        tx = _make_transaction(suggested_account=None)
        assert tx.suggested_account is None

    def test_invalid_direction_rejected(self) -> None:
        """Direction other than 'sent'/'received' is rejected."""
        with pytest.raises(ValueError):
            _make_transaction(direction="refund")

    def test_invalid_source_rejected(self) -> None:
        """Source other than allowed literals is rejected."""
        with pytest.raises(ValueError):
            _make_transaction(source="unknown")


class TestParseAmount:
    """Tests for the parse_amount helper."""

    def test_rupee_symbol(self) -> None:
        """'₹500' parses to Decimal('500')."""
        assert parse_amount("₹500") == Decimal("500")

    def test_rupee_with_decimals(self) -> None:
        """'₹500.50' parses correctly."""
        assert parse_amount("₹500.50") == Decimal("500.50")

    def test_rs_dot(self) -> None:
        """'Rs.500.00' parses correctly."""
        assert parse_amount("Rs.500.00") == Decimal("500.00")

    def test_rs_space(self) -> None:
        """'Rs 500' parses correctly."""
        assert parse_amount("Rs 500") == Decimal("500")

    def test_rs_no_dot(self) -> None:
        """'Rs500' parses correctly."""
        assert parse_amount("Rs500") == Decimal("500")

    def test_inr_prefix(self) -> None:
        """'INR 500.00' parses correctly."""
        assert parse_amount("INR 500.00") == Decimal("500.00")

    def test_indian_numbering(self) -> None:
        """'₹5,00,000' (Indian format) parses to 500000."""
        assert parse_amount("₹5,00,000") == Decimal("500000")

    def test_western_numbering(self) -> None:
        """'₹500,000' (Western format) also parses to 500000."""
        assert parse_amount("₹500,000") == Decimal("500000")

    def test_amount_with_commas_and_decimals(self) -> None:
        """'₹5,00,000.50' parses correctly."""
        assert parse_amount("₹5,00,000.50") == Decimal("500000.50")

    def test_amount_in_sentence(self) -> None:
        """Amount embedded in text is extracted."""
        assert parse_amount("You paid ₹250 to Merchant") == Decimal("250")

    def test_no_match_returns_none(self) -> None:
        """String without amount returns None."""
        assert parse_amount("no amount here") is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        assert parse_amount("") is None

    def test_zero_returns_none(self) -> None:
        """'₹0' returns None (must be positive)."""
        assert parse_amount("₹0") is None

    def test_exceeds_max_returns_none(self) -> None:
        """'₹99,99,999' returns None (exceeds max)."""
        assert parse_amount("₹99,99,999") is None


class TestParseEmailDate:
    """Tests for the parse_email_date helper."""

    def test_rfc2822_date(self) -> None:
        """Standard email date header parses correctly."""
        result, ok = parse_email_date("Thu, 20 Feb 2026 14:30:00 +0530")
        assert ok is True
        assert result == date(2026, 2, 20)

    def test_rfc2822_without_day_name(self) -> None:
        """Date without day name parses correctly."""
        result, ok = parse_email_date("20 Feb 2026 14:30:00 +0530")
        assert ok is True
        assert result == date(2026, 2, 20)

    def test_empty_date_returns_today(self) -> None:
        """Empty date string returns today with success=False."""
        result, ok = parse_email_date("")
        assert ok is False
        assert result == date.today()

    def test_whitespace_date_returns_today(self) -> None:
        """Whitespace-only date returns today with success=False."""
        result, ok = parse_email_date("   ")
        assert ok is False
        assert result == date.today()

    def test_invalid_date_returns_today(self) -> None:
        """Garbage date string returns today with success=False."""
        result, ok = parse_email_date("not-a-date")
        assert ok is False
        assert result == date.today()

    def test_timezone_handled(self) -> None:
        """Date with +0530 offset parses to correct local date."""
        # Late night UTC but next day in IST
        result, ok = parse_email_date("Fri, 21 Feb 2026 23:30:00 +0530")
        assert ok is True
        assert result == date(2026, 2, 21)


class TestSanitizePayee:
    """Tests for the sanitize_payee helper."""

    def test_normal_name_unchanged(self) -> None:
        """'Swiggy' stays 'Swiggy'."""
        assert sanitize_payee("Swiggy") == "Swiggy"

    def test_name_with_punctuation(self) -> None:
        """Normal punctuation is preserved."""
        assert sanitize_payee("McDonald's") == "McDonald's"

    def test_strips_unsafe_chars(self) -> None:
        """HTML-like characters are stripped."""
        assert sanitize_payee("Merchant<script>alert</script>") == "Merchantscriptalertscript"

    def test_collapses_whitespace(self) -> None:
        """Multiple spaces become single space."""
        assert sanitize_payee("Big   Basket") == "Big Basket"

    def test_truncates_at_200(self) -> None:
        """Long name is truncated to 200 characters."""
        long_name = "A" * 250
        assert len(sanitize_payee(long_name)) == 200

    def test_strips_leading_trailing_whitespace(self) -> None:
        """Leading and trailing whitespace is stripped."""
        assert sanitize_payee("  Swiggy  ") == "Swiggy"

    def test_empty_after_sanitize(self) -> None:
        """Returns empty string if all chars are unsafe."""
        assert sanitize_payee("₹₹₹") == ""


class TestExtractUpiRef:
    """Tests for the extract_upi_ref helper."""

    def test_upi_ref_no_pattern(self) -> None:
        """'UPI Ref No: 402012345678' extracts correctly."""
        assert extract_upi_ref("UPI Ref No: 402012345678") == "402012345678"

    def test_upi_reference_pattern(self) -> None:
        """'UPI Reference: 402012345678' extracts correctly."""
        assert extract_upi_ref("UPI Reference: 402012345678") == "402012345678"

    def test_transaction_id_pattern(self) -> None:
        """'Transaction ID: 402012345678' extracts correctly."""
        assert extract_upi_ref("Transaction ID: 402012345678") == "402012345678"

    def test_txn_id_pattern(self) -> None:
        """'Txn ID 402012345678' extracts correctly."""
        assert extract_upi_ref("Txn ID 402012345678") == "402012345678"

    def test_order_id_pattern(self) -> None:
        """'Order ID: 402012345678' extracts correctly."""
        assert extract_upi_ref("Order ID: 402012345678") == "402012345678"

    def test_no_ref_returns_none(self) -> None:
        """Body without UPI ref returns None."""
        assert extract_upi_ref("No reference here") is None

    def test_empty_body_returns_none(self) -> None:
        """Empty body returns None."""
        assert extract_upi_ref("") is None

    def test_html_body_stripped(self) -> None:
        """HTML tags are stripped before searching."""
        html = "<p>UPI Ref No: <b>402012345678</b></p>"
        assert extract_upi_ref(html) == "402012345678"

    def test_short_number_not_matched(self) -> None:
        """11-digit numbers are not matched (must be 12+)."""
        assert extract_upi_ref("UPI Ref No: 12345678901") is None

    def test_long_number_matched(self) -> None:
        """Numbers longer than 12 digits are still matched."""
        assert extract_upi_ref("UPI Ref No: 4020123456789") == "4020123456789"

    def test_ref_in_multiline_body(self) -> None:
        """UPI ref found in multiline email body."""
        body = "Payment successful.\n\nUPI Ref No: 402012345678\n\nThank you."
        assert extract_upi_ref(body) == "402012345678"

    def test_hdfc_instaalerts_reference_number_is(self) -> None:
        """'Your UPI transaction reference number is 456363376702' — HDFC format."""
        body = (
            "Dear Customer, Rs.448.00 has been debited from account 0792 "
            "to VPA swiggyupi@axb Swiggy Ltd on 22-02-26. "
            "Your UPI transaction reference number is 456363376702."
        )
        assert extract_upi_ref(body) == "456363376702"
