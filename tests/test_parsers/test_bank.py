"""Tests for app/parser/regex/bank.py — Generic bank alert parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.gmail.fetch import EmailMessage
from app.parser.regex.bank import parse_bank
from tests.conftest import load_fixture


def _bank_email(
    subject: str,
    body: str = "",
    sender: str = "SBI <alerts@sbi.co.in>",
    email_date: str = "Thu, 20 Feb 2026 14:35:00 +0530",
) -> EmailMessage:
    """Build a bank alert EmailMessage for testing."""
    return EmailMessage(
        message_id="test-bank-001",
        date=email_date,
        sender=sender,
        subject=subject,
        body=body,
    )


class TestBankParser:
    """Tests for the parse_bank function."""

    def test_upi_transaction_debited(self) -> None:
        """'UPI transaction of Rs.500.00 debited' — sent, ₹500."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited from your a/c",
            body="UPI/P2M/402012345678/Swiggy\nUPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("500.00")
        assert result.direction == "sent"

    def test_inr_debited(self) -> None:
        """'Alert: INR 500.00 debited from a/c' — sent."""
        email = _bank_email(
            "Alert: INR 500.00 debited from a/c XX9012",
            body="Transaction ID: 402234567890\nTo: BigBasket",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("500.00")
        assert result.direction == "sent"

    def test_rs_debited(self) -> None:
        """'Rs.500.00 debited' from body parses."""
        email = _bank_email(
            "Bank alert",
            body="Your a/c XX1234 has been debited by Rs.500.00 on 20-02-2026",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("500.00")
        assert result.direction == "sent"

    def test_credited_with_rs(self) -> None:
        """'credited with Rs 1000.00' — received."""
        email = _bank_email(
            "Your a/c XX5678 credited with Rs 1000.00",
            body="UPI Ref No: 402198765432\nBeneficiary: Rahul Kumar",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("1000.00")
        assert result.direction == "received"

    def test_amount_credited(self) -> None:
        """'₹1000.00 credited' — received."""
        email = _bank_email(
            "₹1000.00 credited to your a/c",
            body="UPI Ref No: 402198765432",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("1000.00")
        assert result.direction == "received"

    def test_source_is_bank(self) -> None:
        """Parsed result has source='bank'."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.source == "bank"

    def test_beneficiary_extracted_from_upi_p2m(self) -> None:
        """Beneficiary extracted from UPI/P2M/ pattern."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI/P2M/402012345678/Swiggy\nUPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.payee == "Swiggy"

    def test_beneficiary_extracted_from_to_field(self) -> None:
        """Beneficiary extracted from 'To:' in body."""
        email = _bank_email(
            "INR 500.00 debited from a/c XX9012",
            body="Transaction ID: 402234567890\nTo: BigBasket",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.payee == "BigBasket"

    def test_default_payee_when_no_beneficiary(self) -> None:
        """Falls back to 'Bank Transfer' when no beneficiary found."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.payee == "Bank Transfer"

    def test_generic_payee_reduces_confidence(self) -> None:
        """'Bank Transfer' payee reduces confidence to 0.8."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.confidence == 0.8

    def test_upi_ref_extracted(self) -> None:
        """UPI ref from body is captured."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI/P2M/402012345678/Swiggy\nUPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.upi_ref == "402012345678"

    def test_no_upi_ref_reduces_confidence(self) -> None:
        """Missing UPI ref reduces confidence."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="No reference number here",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.confidence == 0.8  # both no ref and generic payee

    def test_date_parsed(self) -> None:
        """Date is parsed from email header."""
        email = _bank_email(
            "UPI transaction of Rs.500.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.date == date(2026, 2, 20)

    def test_indian_numbering(self) -> None:
        """'Rs.1,50,000.00 debited' — Indian numbering works."""
        email = _bank_email(
            "UPI transaction of Rs.1,50,000.00 debited",
            body="UPI Ref No: 402012345678",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("150000.00")

    def test_non_matching_returns_none(self) -> None:
        """Non-matching subject/body returns None."""
        email = _bank_email("Your credit card statement is ready")
        result = parse_bank(email)
        assert result is None

    def test_empty_subject_and_body_returns_none(self) -> None:
        """Empty subject and body returns None."""
        email = _bank_email("", body="")
        result = parse_bank(email)
        assert result is None

    def test_fixture_bank_debit_sbi(self) -> None:
        """Full fixture bank_debit_sbi.txt parses correctly."""
        email = load_fixture("bank_debit_sbi.txt")
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("500.00")
        assert result.direction == "sent"
        assert result.payee == "Swiggy"
        assert result.upi_ref == "402012345678"

    def test_fixture_bank_credit_hdfc(self) -> None:
        """Full fixture bank_credit_hdfc.txt parses correctly."""
        email = load_fixture("bank_credit_hdfc.txt")
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("1000.00")
        assert result.direction == "received"

    def test_fixture_bank_debit_icici(self) -> None:
        """Full fixture bank_debit_icici.txt parses correctly."""
        email = load_fixture("bank_debit_icici.txt")
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("500.00")
        assert result.direction == "sent"

    def test_hdfc_instaalerts_has_been_debited(self) -> None:
        """'Rs.448.00 has been debited from account' — HDFC InstaAlerts format."""
        email = _bank_email(
            "You have done a UPI txn. Check details!",
            body=(
                "Dear Customer, Rs.448.00 has been debited from account 0792 "
                "to VPA swiggyupi@axb Swiggy Ltd on 22-02-26. "
                "Your UPI transaction reference number is 456363376702."
            ),
            sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("448.00")
        assert result.direction == "sent"
        assert result.payee == "Swiggy Ltd"
        assert result.upi_ref == "456363376702"
        assert result.confidence == 1.0

    def test_hdfc_instaalerts_vpa_payee_extraction(self) -> None:
        """Payee extracted from 'to VPA handle@bank MerchantName on DD-MM-YY'."""
        email = _bank_email(
            "You have done a UPI txn. Check details!",
            body=(
                "Dear Customer, Rs.150.00 has been debited from account 0792 "
                "to VPA zomato@paytm Zomato Ltd on 22-02-26. "
                "Your UPI transaction reference number is 789012345678."
            ),
            sender="HDFC Bank InstaAlerts <alerts@hdfcbank.bank.in>",
        )
        result = parse_bank(email)
        assert result is not None
        assert result.payee == "Zomato Ltd"

    def test_fixture_bank_debit_hdfc_instaalerts(self) -> None:
        """Full fixture bank_debit_hdfc_instaalerts.txt parses correctly."""
        email = load_fixture("bank_debit_hdfc_instaalerts.txt")
        result = parse_bank(email)
        assert result is not None
        assert result.amount == Decimal("448.00")
        assert result.direction == "sent"
        assert result.payee == "Swiggy Ltd"
        assert result.upi_ref == "456363376702"
        assert result.confidence == 1.0
