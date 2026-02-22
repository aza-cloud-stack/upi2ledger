"""Base parser types and shared utilities for email parsing.

Provides the ParsedTransaction model (output of all parsers),
the EmailParser protocol, and helper functions for parsing amounts,
dates, and sanitizing payee names.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol

from pydantic import BaseModel, field_validator

from app.gmail.fetch import EmailMessage

# Maximum transaction amount: ₹10,00,000 (10 lakh INR)
MAX_AMOUNT = Decimal("1000000")

# Allowed characters in account names: lowercase alphanumeric, colon, dash
ACCOUNT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9:_-]*$")

# Amount extraction: matches ₹, Rs., Rs, INR followed by digits
# with optional commas and decimal point
AMOUNT_PATTERN = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)")

# Characters allowed in payee names
PAYEE_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9\s.,&'()\-]")


class ParsedTransaction(BaseModel):
    """A parsed UPI transaction ready for review.

    All fields are validated via Pydantic before database insertion.
    """

    date: date
    amount: Decimal
    payee: str
    direction: Literal["sent", "received"]
    source: Literal["gpay", "phonepe", "paytm", "bank"]
    upi_ref: str | None = None
    email_message_id: str
    confidence: float
    suggested_account: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive_and_bounded(cls, v: Decimal) -> Decimal:
        """Validate amount is positive and within bounds."""
        if v <= 0:
            msg = "Amount must be positive"
            raise ValueError(msg)
        if v > MAX_AMOUNT:
            msg = f"Amount exceeds maximum ({MAX_AMOUNT})"
            raise ValueError(msg)
        return v

    @field_validator("payee")
    @classmethod
    def payee_must_be_sanitized(cls, v: str) -> str:
        """Validate and truncate payee name."""
        v = v.strip()
        if not v:
            msg = "Payee must not be empty"
            raise ValueError(msg)
        if len(v) > 200:
            v = v[:200]
        return v

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_in_range(cls, v: float) -> float:
        """Validate confidence is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            msg = "Confidence must be between 0.0 and 1.0"
            raise ValueError(msg)
        return v

    @field_validator("suggested_account")
    @classmethod
    def account_name_must_be_valid(cls, v: str | None) -> str | None:
        """Validate account name format if provided."""
        if v is not None and not ACCOUNT_NAME_PATTERN.match(v):
            msg = "Account name must be lowercase alphanumeric with colons/dashes only"
            raise ValueError(msg)
        return v


class EmailParser(Protocol):
    """Protocol for email parsers.

    Each parser takes an EmailMessage and returns a ParsedTransaction
    if it can parse the email, or None if it cannot.
    """

    def __call__(self, email: EmailMessage) -> ParsedTransaction | None: ...


def parse_amount(text: str) -> Decimal | None:
    """Extract and parse a currency amount from text.

    Handles: ₹500, ₹5,00,000, Rs.500.00, Rs 500, INR 500.00
    Returns None if no valid amount found.
    """
    match = AMOUNT_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    if amount <= 0 or amount > MAX_AMOUNT:
        return None
    return amount


def parse_email_date(date_header: str) -> tuple[date, bool]:
    """Parse the email Date header (RFC 2822) into a date object.

    Returns (date, success_flag). If parsing fails, returns
    (today's date, False) so callers can reduce confidence.
    """
    if not date_header.strip():
        return date.today(), False
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.date(), True
    except (ValueError, TypeError):
        return date.today(), False


def sanitize_payee(raw: str) -> str:
    """Sanitize a payee/merchant name.

    Strips unsafe characters, collapses whitespace, truncates to 200 chars.
    """
    cleaned = PAYEE_SAFE_PATTERN.sub("", raw)
    cleaned = " ".join(cleaned.split())
    return cleaned[:200].strip()


def extract_upi_ref(body: str) -> str | None:
    """Extract UPI reference number from email body text.

    UPI refs are typically 12-digit numbers, sometimes prefixed with
    identifiers like 'UPI Ref', 'Transaction ID', 'Txn ID', etc.
    """
    # Strip HTML tags if body contains them (fallback from HTML decode)
    clean_body = re.sub(r"<[^>]+>", " ", body)

    patterns = [
        r"(?:UPI\s*(?:Ref|Reference|Txn)\s*(?:No\.?|ID|:)?)\s*[:.]?\s*(\d{12,})",
        # "Your UPI transaction reference number is 456363376702" (HDFC InstaAlerts)
        r"(?:UPI\s+transaction\s+reference\s+number\s+is)\s+(\d{12,})",
        r"(?:Transaction\s*(?:ID|No\.?|Ref)\s*[:.]?)\s*(\d{12,})",
        r"(?:Txn\s*(?:ID|No\.?|Ref)\s*[:.]?)\s*(\d{12,})",
        r"(?:Order\s*ID\s*[:.]?)\s*(\d{12,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, clean_body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None
