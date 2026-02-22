"""Paytm email parser.

Parses transaction emails from Paytm (noreply@paytm.com)
by extracting amount, payee, and direction from the subject line.

Subject patterns:
  - "Paid ₹500 to DMart"
  - "You paid ₹300 to Flipkart on Paytm"
  - "₹1,000 received via Paytm"
  - "₹500 received from Person via Paytm"
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

_PATTERNS: list[tuple[re.Pattern[str], Direction, bool]] = [
    # "Paid ₹500 to Merchant" / "You paid ₹300 to Flipkart on Paytm"
    (
        re.compile(
            r"(?:You\s+)?Paid\s+(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)"
            r"\s+to\s+(.+?)(?:\s+on\s+Paytm)?\s*$",
            re.IGNORECASE,
        ),
        "sent",
        True,  # has payee in group(2)
    ),
    # "₹1,000 received from Person via Paytm"
    (
        re.compile(
            r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)"
            r"\s+received\s+from\s+(.+?)(?:\s+via\s+Paytm)?\s*$",
            re.IGNORECASE,
        ),
        "received",
        True,  # has payee in group(2)
    ),
    # "₹1,000 received via Paytm" (no sender name)
    (
        re.compile(
            r"(?:₹|Rs\.?|INR)\s*([0-9,]+(?:\.[0-9]{1,2})?)\s+received\s+via\s+Paytm",
            re.IGNORECASE,
        ),
        "received",
        False,  # no payee — use default
    ),
]


def parse_paytm(email: EmailMessage) -> ParsedTransaction | None:
    """Parse a Paytm transaction email.

    Returns a ParsedTransaction if the subject matches a known Paytm pattern,
    or None if parsing fails.
    """
    subject = email.subject.strip()

    for pattern, direction, has_payee in _PATTERNS:
        match = pattern.search(subject)
        if not match:
            continue

        raw_amount = match.group(1).replace(",", "")
        amount = parse_amount(f"₹{raw_amount}")
        if amount is None:
            continue

        if has_payee and match.lastindex is not None and match.lastindex >= 2:
            raw_payee = match.group(2).strip()
            raw_payee = re.sub(r"\s+on\s+Paytm\s*$", "", raw_payee, flags=re.IGNORECASE)
            payee = sanitize_payee(raw_payee)
        else:
            payee = "Paytm Transfer"

        if not payee:
            payee = "Paytm Transfer"

        tx_date, date_ok = parse_email_date(email.date)
        confidence = 1.0 if date_ok else 0.8

        upi_ref = extract_upi_ref(email.body)
        if upi_ref is None:
            confidence = min(confidence, 0.9)

        logger.info("Parsed Paytm email %s", email.message_id)

        return ParsedTransaction(
            date=tx_date,
            amount=amount,
            payee=payee,
            direction=direction,
            source="paytm",
            upi_ref=upi_ref,
            email_message_id=email.message_id,
            confidence=confidence,
            suggested_account=None,
        )

    return None
