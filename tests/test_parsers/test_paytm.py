"""Tests for app/parser/regex/paytm.py — Paytm parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.gmail.fetch import EmailMessage
from app.parser.regex.paytm import parse_paytm
from tests.conftest import load_fixture


def _paytm_email(
    subject: str,
    body: str = "Order ID: 402089012345",
    email_date: str = "Thu, 20 Feb 2026 16:45:00 +0530",
) -> EmailMessage:
    """Build a Paytm-like EmailMessage for testing."""
    return EmailMessage(
        message_id="test-paytm-001",
        date=email_date,
        sender="Paytm <noreply@paytm.com>",
        subject=subject,
        body=body,
    )


class TestPaytmParser:
    """Tests for the parse_paytm function."""

    def test_paid_to_merchant(self) -> None:
        """'Paid ₹500 to DMart' — sent, ₹500, DMart."""
        email = _paytm_email("Paid ₹500 to DMart")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "DMart"
        assert result.direction == "sent"

    def test_you_paid_on_paytm(self) -> None:
        """'You paid ₹300 to Flipkart on Paytm' — strips 'on Paytm'."""
        email = _paytm_email("You paid ₹300 to Flipkart on Paytm")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("300")
        assert result.payee == "Flipkart"
        assert result.direction == "sent"

    def test_received_via_paytm(self) -> None:
        """'₹1,000 received via Paytm' — received, default payee."""
        email = _paytm_email("₹1,000 received via Paytm")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.direction == "received"
        assert result.payee == "Paytm Transfer"

    def test_received_from_person(self) -> None:
        """'₹500 received from Amit via Paytm' — received with payee."""
        email = _paytm_email("₹500 received from Amit via Paytm")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "Amit"
        assert result.direction == "received"

    def test_received_from_person_no_via(self) -> None:
        """'₹500 received from Amit' — received without 'via Paytm'."""
        email = _paytm_email("₹500 received from Amit")
        result = parse_paytm(email)
        assert result is not None
        assert result.payee == "Amit"

    def test_source_is_paytm(self) -> None:
        """Parsed result has source='paytm'."""
        email = _paytm_email("Paid ₹500 to DMart")
        result = parse_paytm(email)
        assert result is not None
        assert result.source == "paytm"

    def test_rs_dot_variant(self) -> None:
        """'Paid Rs.500 to DMart' works."""
        email = _paytm_email("Paid Rs.500 to DMart")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_inr_variant(self) -> None:
        """'Paid INR 500 to DMart' works."""
        email = _paytm_email("Paid INR 500 to DMart")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("500")

    def test_upi_ref_extracted(self) -> None:
        """UPI ref from body is captured."""
        email = _paytm_email("Paid ₹500 to DMart", body="Order ID: 402089012345")
        result = parse_paytm(email)
        assert result is not None
        assert result.upi_ref == "402089012345"

    def test_no_upi_ref_reduces_confidence(self) -> None:
        """Missing UPI ref reduces confidence."""
        email = _paytm_email("Paid ₹500 to DMart", body="No ref here")
        result = parse_paytm(email)
        assert result is not None
        assert result.confidence == 0.9

    def test_date_parsed(self) -> None:
        """Date is parsed from email header."""
        email = _paytm_email("Paid ₹500 to DMart")
        result = parse_paytm(email)
        assert result is not None
        assert result.date == date(2026, 2, 20)

    def test_non_matching_returns_none(self) -> None:
        """Non-matching subject returns None."""
        email = _paytm_email("Paytm cashback offer!")
        result = parse_paytm(email)
        assert result is None

    def test_empty_subject_returns_none(self) -> None:
        """Empty subject returns None."""
        email = _paytm_email("")
        result = parse_paytm(email)
        assert result is None

    def test_fixture_paytm_sent(self) -> None:
        """Full fixture paytm_sent.txt parses correctly."""
        email = load_fixture("paytm_sent.txt")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("500")
        assert result.payee == "DMart"
        assert result.direction == "sent"

    def test_fixture_paytm_you_paid(self) -> None:
        """Full fixture paytm_you_paid.txt parses correctly."""
        email = load_fixture("paytm_you_paid.txt")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("300")
        assert result.payee == "Flipkart"

    def test_fixture_paytm_received(self) -> None:
        """Full fixture paytm_received.txt parses correctly."""
        email = load_fixture("paytm_received.txt")
        result = parse_paytm(email)
        assert result is not None
        assert result.amount == Decimal("1000")
        assert result.direction == "received"
