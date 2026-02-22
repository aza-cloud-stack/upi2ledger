"""Tests for app/parser/registry.py — parser routing."""

from __future__ import annotations

from decimal import Decimal

from app.gmail.fetch import EmailMessage
from app.parser.registry import parse_email


def _email(
    sender: str,
    subject: str,
    body: str = "UPI Ref No: 402012345678",
    email_date: str = "Thu, 20 Feb 2026 14:30:00 +0530",
) -> EmailMessage:
    """Build an EmailMessage for testing."""
    return EmailMessage(
        message_id="test-registry-001",
        date=email_date,
        sender=sender,
        subject=subject,
        body=body,
    )


class TestParserRegistry:
    """Tests for parse_email sender routing and fallback."""

    def test_google_sender_routes_to_gpay(self) -> None:
        """Email from noreply@google.com routes to GPay parser."""
        email = _email("Google Pay <noreply@google.com>", "You paid ₹500 to Swiggy")
        result = parse_email(email)
        assert result is not None
        assert result.source == "gpay"
        assert result.amount == Decimal("500")

    def test_phonepe_sender_routes_to_phonepe(self) -> None:
        """Email from PhonePe routes to PhonePe parser."""
        email = _email("PhonePe <noreply@phonepe.com>", "Payment of ₹500 to Zomato successful")
        result = parse_email(email)
        assert result is not None
        assert result.source == "phonepe"

    def test_paytm_sender_routes_to_paytm(self) -> None:
        """Email from Paytm routes to Paytm parser."""
        email = _email("Paytm <noreply@paytm.com>", "Paid ₹500 to DMart")
        result = parse_email(email)
        assert result is not None
        assert result.source == "paytm"

    def test_bank_sender_falls_through_to_bank(self) -> None:
        """Email from SBI (no sender match) falls through to bank parser."""
        email = _email(
            "SBI <alerts@sbi.co.in>",
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_email(email)
        assert result is not None
        assert result.source == "bank"

    def test_unknown_sender_tries_all_parsers(self) -> None:
        """Email from unknown sender with GPay subject still matches."""
        email = _email("Unknown <noreply@example.com>", "You paid ₹500 to Swiggy")
        result = parse_email(email)
        assert result is not None
        assert result.source == "gpay"

    def test_unparseable_email_returns_none(self) -> None:
        """Email that no parser can handle returns None."""
        email = _email("Someone <noreply@example.com>", "Hello, how are you?")
        result = parse_email(email)
        assert result is None

    def test_sender_match_but_parse_fails_tries_all(self) -> None:
        """If sender matches Google but subject is non-payment, fallback is tried."""
        email = _email(
            "Google <noreply@google.com>",
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        # Subject doesn't match GPay patterns, but bank parser should catch it
        result = parse_email(email)
        assert result is not None
        assert result.source == "bank"

    def test_case_insensitive_sender_matching(self) -> None:
        """Sender matching is case-insensitive."""
        email = _email("GOOGLE PAY <NOREPLY@GOOGLE.COM>", "You paid ₹500 to Swiggy")
        result = parse_email(email)
        assert result is not None
        assert result.source == "gpay"
