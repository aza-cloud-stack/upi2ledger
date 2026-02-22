"""Generic bank alert email parser.

Handles transaction alerts from Indian banks (SBI, HDFC, ICICI, Axis, etc.).

Subject/body patterns:
  - "UPI transaction of Rs.500.00 debited"
  - "Alert: INR 500.00 debited from a/c XX1234"
  - "Your a/c XX5678 credited with Rs 1000.00"
  - "UPI/P2M/123456789012/Merchant"
"""

from __future__ import annotations

import logging
import re

from app.gmail.fetch import EmailMessage
from app.parser.base import (
    ParsedTransaction,
    extract_upi_ref,
    parse_amount,
    parse_email_date,
    sanitize_payee,
)

logger = logging.getLogger(__name__)

# Debit patterns — searched in subject + body combined
_DEBIT_PATTERNS: list[re.Pattern[str]] = [
    # "UPI transaction of Rs.500.00 debited"
    re.compile(
        r"(?:UPI\s+)?(?:transaction|txn)\s+(?:of\s+)?(?:₹|Rs\.?|INR)\s*"
        r"([0-9,]+(?:\.[0-9]{1,2})?)\s+(?:debited|deducted)",
        re.IGNORECASE,
    ),
    # "INR 500.00 debited from a/c" / "Rs.500 debited"
    re.compile(
        r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+(?:debited|deducted)",
        re.IGNORECASE,
    ),
    # "debited by Rs.500.00"
    re.compile(
        r"(?:debited|deducted)\s+(?:by|with)\s+(?:₹|Rs\.?|INR)\s*" r"([0-9,]+(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    # "Rs.448.00 has been debited from account" (HDFC InstaAlerts)
    re.compile(
        r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+has\s+been\s+(?:debited|deducted)",
        re.IGNORECASE,
    ),
]

# Credit patterns
_CREDIT_PATTERNS: list[re.Pattern[str]] = [
    # "credited with Rs 1000.00"
    re.compile(
        r"credited\s+(?:with\s+)?(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    # "₹1000.00 credited"
    re.compile(
        r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+credited",
        re.IGNORECASE,
    ),
]

# Beneficiary / payee extraction from body
_BENEFICIARY_PATTERNS: list[re.Pattern[str]] = [
    # UPI/P2M/refno/MerchantName (stop at newline)
    re.compile(
        r"UPI/(?:P2M|P2P)/\d+/([A-Za-z0-9 .,&'()\-]{2,50})",
        re.IGNORECASE,
    ),
    # "To: Merchant" / "Beneficiary: Name" (stop at newline)
    re.compile(
        r"(?:to|beneficiary|payee|merchant)\s*[:]\s*([A-Za-z0-9 .,&'()\-]{2,50})",
        re.IGNORECASE,
    ),
    # "to VPA swiggyupi@axb Swiggy Ltd on 22-02-26" (HDFC InstaAlerts)
    re.compile(
        r"to\s+VPA\s+\S+\s+(.+?)\s+on\s+\d{2}-\d{2}-\d{2,4}",
        re.IGNORECASE,
    ),
]


def _extract_beneficiary(body: str, subject: str) -> str:
    """Extract beneficiary/merchant name from body or subject."""
    clean_body = re.sub(r"<[^>]+>", " ", body)
    search_text = f"{subject}\n{clean_body}"

    for pattern in _BENEFICIARY_PATTERNS:
        match = pattern.search(search_text)
        if match:
            name = sanitize_payee(match.group(1))
            if name and len(name) >= 2:
                return name

    return "Bank Transfer"


def parse_bank(email: EmailMessage) -> ParsedTransaction | None:
    """Parse a bank alert transaction email.

    Searches both subject and body for debit/credit patterns. Returns
    a ParsedTransaction or None if no patterns match.
    """
    subject = email.subject.strip()
    search_text = f"{subject}\n{email.body}"

    # Try debit patterns first (more common for UPI)
    for pattern in _DEBIT_PATTERNS:
        match = pattern.search(search_text)
        if match:
            raw_amount = match.group(1).replace(",", "")
            amount = parse_amount(f"₹{raw_amount}")
            if amount is None:
                continue

            payee = _extract_beneficiary(email.body, subject)
            tx_date, date_ok = parse_email_date(email.date)
            confidence = 1.0 if date_ok else 0.8

            upi_ref = extract_upi_ref(email.body)
            if upi_ref is None:
                confidence = min(confidence, 0.9)

            # Lower confidence when payee is generic
            if payee == "Bank Transfer":
                confidence = min(confidence, 0.8)

            logger.info("Parsed bank debit email %s", email.message_id)

            return ParsedTransaction(
                date=tx_date,
                amount=amount,
                payee=payee,
                direction="sent",
                source="bank",
                upi_ref=upi_ref,
                email_message_id=email.message_id,
                confidence=confidence,
                suggested_account=None,
            )

    # Try credit patterns
    for pattern in _CREDIT_PATTERNS:
        match = pattern.search(search_text)
        if match:
            raw_amount = match.group(1).replace(",", "")
            amount = parse_amount(f"₹{raw_amount}")
            if amount is None:
                continue

            payee = _extract_beneficiary(email.body, subject)
            tx_date, date_ok = parse_email_date(email.date)
            confidence = 1.0 if date_ok else 0.8

            upi_ref = extract_upi_ref(email.body)
            if upi_ref is None:
                confidence = min(confidence, 0.9)

            if payee == "Bank Transfer":
                confidence = min(confidence, 0.8)

            logger.info("Parsed bank credit email %s", email.message_id)

            return ParsedTransaction(
                date=tx_date,
                amount=amount,
                payee=payee,
                direction="received",
                source="bank",
                upi_ref=upi_ref,
                email_message_id=email.message_id,
                confidence=confidence,
                suggested_account=None,
            )

    return None
