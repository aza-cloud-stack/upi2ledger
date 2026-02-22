"""Tests for app/parser/regex/phonepe.py — PhonePe parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.gmail.fetch import EmailMessage
from app.parser.regex.phonepe import parse_phonepe
from tests.conftest import load_fixture


def _phonepe_email(
    subject: str,
    body: str = "Transaction ID: 402056789012",
    email_date: str = "Thu, 20 Feb 2026 19:00:00 +0530",
) -> EmailMessage:
    """Build a PhonePe-like EmailMessage for testing."""
    return EmailMessage(
        message_id="test-phonepe-001",
        date=email_date,
        sender="PhonePe <noreply@phonepe.com>",
        subject=subject,
        body=body,
    )


class TestPhonePeParser:
    """Tests for the parse_phonepe function."""

    def test_payment_successful(self) -> None:
        """'Payment of ₹500 to Zomato successful' — sent, ₹500, Zomato."""
        email = _phonepe_email("Payment of ₹500 to Zomato successful")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "Zomato"
        assert result.direction == "sent"

    def test_payment_without_successful(self) -> None:
        """'Payment of ₹500 to Zomato' — also works without 'successful'."""
        email = _phonepe_email("Payment of ₹500 to Zomato")
        result = parse_phonepe(email)
        assert result is not None
        assert result.payee == "Zomato"

    def test_phonepe_prefix_you_paid(self) -> None:
        """'PhonePe: You paid ₹300 to Amazon' — sent, ₹300, Amazon."""
        email = _phonepe_email("PhonePe: You paid ₹300 to Amazon")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("300")
        assert result.payee == "Amazon"
        assert result.direction == "sent"

    def test_you_paid_without_prefix(self) -> None:
        """'You paid ₹300 to Amazon' — PhonePe prefix is optional."""
        email = _phonepe_email("You paid ₹300 to Amazon")
        result = parse_phonepe(email)
        assert result is not None
        assert result.payee == "Amazon"

    def test_received_from(self) -> None:
        """'₹1,000 received from Priya' — received, ₹1000, Priya."""
        email = _phonepe_email("₹1,000 received from Priya Sharma")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.payee == "Priya Sharma"
        assert result.direction == "received"

    def test_source_is_phonepe(self) -> None:
        """Parsed result has source='phonepe'."""
        email = _phonepe_email("Payment of ₹500 to Zomato successful")
        result = parse_phonepe(email)
        assert result is not None
        assert result.source == "phonepe"

    def test_rs_dot_variant(self) -> None:
        """'Payment of Rs.500 to Zomato successful' works."""
        email = _phonepe_email("Payment of Rs.500 to Zomato successful")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_inr_variant(self) -> None:
        """'Payment of INR 500 to Zomato successful' works."""
        email = _phonepe_email("Payment of INR 500 to Zomato successful")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_upi_ref_extracted(self) -> None:
        """UPI ref from body is captured."""
        email = _phonepe_email(
            "Payment of ₹500 to Zomato successful",
            body="Transaction ID: 402056789012",
        )
        result = parse_phonepe(email)
        assert result is not None
        assert result.upi_ref == "402056789012"
        assert result.confidence == 1.0

    def test_no_upi_ref_reduces_confidence(self) -> None:
        """Missing UPI ref reduces confidence to 0.9."""
        email = _phonepe_email("Payment of ₹500 to Zomato successful", body="No ref")
        result = parse_phonepe(email)
        assert result is not None
        assert result.confidence == 0.9

    def test_date_parsed(self) -> None:
        """Date is parsed from email header."""
        email = _phonepe_email("Payment of ₹500 to Zomato successful")
        result = parse_phonepe(email)
        assert result is not None
        assert result.date == date(2026, 2, 20)

    def test_non_matching_returns_none(self) -> None:
        """Non-matching subject returns None."""
        email = _phonepe_email("Welcome to PhonePe!")
        result = parse_phonepe(email)
        assert result is None

    def test_empty_subject_returns_none(self) -> None:
        """Empty subject returns None."""
        email = _phonepe_email("")
        result = parse_phonepe(email)
        assert result is None

    def test_fixture_phonepe_sent(self) -> None:
        """Full fixture phonepe_sent.txt parses correctly."""
        email = load_fixture("phonepe_sent.txt")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "Zomato"
        assert result.direction == "sent"

    def test_fixture_phonepe_received(self) -> None:
        """Full fixture phonepe_received.txt parses correctly."""
        email = load_fixture("phonepe_received.txt")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.payee == "Priya Sharma"
        assert result.direction == "received"

    def test_fixture_phonepe_prefix(self) -> None:
        """Full fixture phonepe_prefix.txt parses correctly."""
        email = load_fixture("phonepe_prefix.txt")
        result = parse_phonepe(email)
        assert result is not None
        assert result.amount == Decimal("300")
        assert result.payee == "Amazon"
        assert result.direction == "sent"
