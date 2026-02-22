"""PhonePe email parser.

Parses transaction emails from PhonePe (noreply@phonepe.com)
by extracting amount, payee, and direction from the subject line.

Subject patterns:
  - "Payment of ₹500 to Zomato successful"
  - "₹1,000 received from Priya Sharma"
  - "PhonePe: You paid ₹300 to Amazon"
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from app.gmail.fetch import EmailMessage
from app.parser.base import (
    ParsedTransaction,
    extract_upi_ref,
    parse_amount,
    parse_email_date,
    sanitize_payee,
)

logger = logging.getLogger(__name__)

Direction = Literal["sent", "received"]

_PATTERNS: list[tuple[re.Pattern[str], Direction]] = [
    # "Payment of ₹500 to Merchant successful"
    (
        re.compile(
            r"Payment\s+of\s+(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)"
            r"\s+to\s+(.+?)(?:\s+successful)?\s*$",
            re.IGNORECASE,
        ),
        "sent",
    ),
    # "PhonePe: You paid ₹300 to Amazon"
    (
        re.compile(
            r"(?:PhonePe\s*:\s*)?You\s+paid\s+(?:₹|Rs\.?|INR)\s*"
            r"([0-9,]+(?:\.[0-9]{1,2})?)\s+to\s+(.+)",
            re.IGNORECASE,
        ),
        "sent",
    ),
    # "₹1,000 received from Person"
    (
        re.compile(
            r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+received\s+from\s+(.+)",
            re.IGNORECASE,
        ),
        "received",
    ),
]


def parse_phonepe(email: EmailMessage) -> ParsedTransaction | None:
    """Parse a PhonePe transaction email.

    Returns a ParsedTransaction if the subject matches a known PhonePe pattern,
    or None if parsing fails.
    """
    subject = email.subject.strip()

    for pattern, direction in _PATTERNS:
        match = pattern.search(subject)
        if not match:
            continue

        raw_amount = match.group(1).replace(",", "")
        amount = parse_amount(f"₹{raw_amount}")
        if amount is None:
            continue

        raw_payee = match.group(2).strip()
        # Remove trailing "successful" if captured
        raw_payee = re.sub(r"\s+successful\s*$", "", raw_payee, flags=re.IGNORECASE)
        payee = sanitize_payee(raw_payee)
        if not payee:
            continue

        tx_date, date_ok = parse_email_date(email.date)
        confidence = 1.0 if date_ok else 0.8

        upi_ref = extract_upi_ref(email.body)
        if upi_ref is None:
            confidence = min(confidence, 0.9)

        logger.info("Parsed PhonePe email %s", email.message_id)

        return ParsedTransaction(
            date=tx_date,
            amount=amount,
            payee=payee,
            direction=direction,
            source="phonepe",
            upi_ref=upi_ref,
            email_message_id=email.message_id,
            confidence=confidence,
            suggested_account=None,
        )

    return None
