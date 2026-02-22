"""Tests for app/parser/regex/gpay.py — Google Pay parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.gmail.fetch import EmailMessage
from app.parser.regex.gpay import parse_gpay
from tests.conftest import load_fixture


def _gpay_email(
    subject: str,
    body: str = "UPI Ref No: 402012345678",
    email_date: str = "Thu, 20 Feb 2026 14:30:00 +0530",
) -> EmailMessage:
    """Build a GPay-like EmailMessage for testing."""
    return EmailMessage(
        message_id="test-gpay-001",
        date=email_date,
        sender="Google Pay <noreply@google.com>",
        subject=subject,
        body=body,
    )


class TestGPayParser:
    """Tests for the parse_gpay function."""

    def test_you_paid_subject(self) -> None:
        """'You paid ₹500 to Swiggy' — sent, ₹500, Swiggy."""
        email = _gpay_email("You paid ₹500 to Swiggy")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "Swiggy"
        assert result.direction == "sent"

    def test_you_received_subject(self) -> None:
        """'You received ₹1,000 from John' — received, ₹1000, John."""
        email = _gpay_email("You received ₹1,000 from John")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.payee == "John"
        assert result.direction == "received"

    def test_amount_paid_prefix(self) -> None:
        """'₹200.00 paid to BigBasket' — sent, ₹200, BigBasket."""
        email = _gpay_email("₹200.00 paid to BigBasket")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("200.00")
        assert result.payee == "BigBasket"
        assert result.direction == "sent"

    def test_amount_received_prefix(self) -> None:
        """'₹500.50 received from Alice' — received, ₹500.50, Alice."""
        email = _gpay_email("₹500.50 received from Alice")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("500.50")
        assert result.payee == "Alice"
        assert result.direction == "received"

    def test_indian_numbering_amount(self) -> None:
        """'You paid ₹1,50,000 to Merchant' — large amount works."""
        email = _gpay_email("You paid ₹1,50,000 to Merchant")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("150000")

    def test_rs_dot_variant(self) -> None:
        """'You paid Rs.500 to Merchant' — Rs. prefix works."""
        email = _gpay_email("You paid Rs.500 to Merchant")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_inr_variant(self) -> None:
        """'You paid INR 500 to Merchant' — INR prefix works."""
        email = _gpay_email("You paid INR 500 to Merchant")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_source_is_gpay(self) -> None:
        """Parsed result has source='gpay'."""
        email = _gpay_email("You paid ₹500 to Swiggy")
        result = parse_gpay(email)
        assert result is not None
        assert result.source == "gpay"

    def test_upi_ref_extracted_from_body(self) -> None:
        """UPI ref in body is captured, confidence 1.0."""
        email = _gpay_email("You paid ₹500 to Swiggy", body="UPI Ref No: 402012345678")
        result = parse_gpay(email)
        assert result is not None
        assert result.upi_ref == "402012345678"
        assert result.confidence == 1.0

    def test_no_upi_ref_reduces_confidence(self) -> None:
        """Missing UPI ref in body reduces confidence to 0.9."""
        email = _gpay_email("You paid ₹500 to Swiggy", body="No ref here")
        result = parse_gpay(email)
        assert result is not None
        assert result.upi_ref is None
        assert result.confidence == 0.9

    def test_invalid_date_reduces_confidence(self) -> None:
        """Bad date header reduces confidence to 0.8."""
        email = _gpay_email("You paid ₹500 to Swiggy", email_date="invalid-date")
        result = parse_gpay(email)
        assert result is not None
        assert result.confidence <= 0.8

    def test_date_parsed_correctly(self) -> None:
        """Date is parsed from email header."""
        email = _gpay_email("You paid ₹500 to Swiggy")
        result = parse_gpay(email)
        assert result is not None
        assert result.date == date(2026, 2, 20)

    def test_non_gpay_email_returns_none(self) -> None:
        """Non-matching subject returns None."""
        email = _gpay_email("Your Google account security alert")
        result = parse_gpay(email)
        assert result is None

    def test_empty_subject_returns_none(self) -> None:
        """Empty subject returns None."""
        email = _gpay_email("")
        result = parse_gpay(email)
        assert result is None

    def test_message_id_preserved(self) -> None:
        """email_message_id is set from the input email."""
        email = _gpay_email("You paid ₹500 to Swiggy")
        result = parse_gpay(email)
        assert result is not None
        assert result.email_message_id == "test-gpay-001"

    def test_fixture_gpay_sent(self) -> None:
        """Full fixture file gpay_sent.txt parses correctly."""
        email = load_fixture("gpay_sent.txt")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "Swiggy"
        assert result.direction == "sent"
        assert result.upi_ref == "402012345678"
        assert result.confidence == 1.0

    def test_fixture_gpay_received(self) -> None:
        """Full fixture file gpay_received.txt parses correctly."""
        email = load_fixture("gpay_received.txt")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.payee == "Rahul Kumar"
        assert result.direction == "received"
        assert result.upi_ref == "402198765432"

    def test_fixture_gpay_paid_prefix(self) -> None:
        """Full fixture file gpay_paid_prefix.txt parses correctly."""
        email = load_fixture("gpay_paid_prefix.txt")
        result = parse_gpay(email)
        assert result is not None
        assert result.amount == Decimal("200.00")
        assert result.payee == "BigBasket"
        assert result.direction == "sent"
        assert result.upi_ref == "402234567890"
