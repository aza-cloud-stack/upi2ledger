"""Google Pay email parser.

Parses transaction emails from Google Pay (noreply@google.com)
by extracting amount, payee, and direction from the subject line.

Subject patterns:
  - "You paid ₹500 to Swiggy"
  - "You received ₹1,000 from John"
  - "₹200.00 paid to BigBasket"
  - "₹500.50 received from Alice"
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

# Subject line patterns for Google Pay — checked in order, first match wins.
_PATTERNS: list[tuple[re.Pattern[str], Direction]] = [
    # "You paid ₹500 to Merchant"
    (
        re.compile(
            r"You\s+paid\s+(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+to\s+(.+)",
            re.IGNORECASE,
        ),
        "sent",
    ),
    # "You received ₹1,000 from Person"
    (
        re.compile(
            r"You\s+received\s+(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+from\s+(.+)",
            re.IGNORECASE,
        ),
        "received",
    ),
    # "₹200.00 paid to Merchant"
    (
        re.compile(
            r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+paid\s+to\s+(.+)",
            re.IGNORECASE,
        ),
        "sent",
    ),
    # "₹500.50 received from Person"
    (
        re.compile(
            r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+received\s+from\s+(.+)",
            re.IGNORECASE,
        ),
        "received",
    ),
]


def parse_gpay(email: EmailMessage) -> ParsedTransaction | None:
    """Parse a Google Pay transaction email.

    Returns a ParsedTransaction if the subject matches a known GPay pattern,
    or None if parsing fails.
    """
    subject = email.subject.strip()

    for pattern, direction in _PATTERNS:
        match = pattern.search(subject)
        if not match:
            continue

        # Extract amount from regex group
        raw_amount = match.group(1).replace(",", "")
        amount = parse_amount(f"₹{raw_amount}")
        if amount is None:
            continue

        # Extract and sanitize payee
        raw_payee = match.group(2).strip()
        payee = sanitize_payee(raw_payee)
        if not payee:
            continue

        # Parse date from header
        tx_date, date_ok = parse_email_date(email.date)
        confidence = 1.0 if date_ok else 0.8

        # Try to extract UPI ref from body
        upi_ref = extract_upi_ref(email.body)
        if upi_ref is None:
            confidence = min(confidence, 0.9)

        logger.info("Parsed GPay email %s", email.message_id)

        return ParsedTransaction(
            date=tx_date,
            amount=amount,
            payee=payee,
            direction=direction,
            source="gpay",
            upi_ref=upi_ref,
            email_message_id=email.message_id,
            confidence=confidence,
            suggested_account=None,
        )

    return None
