"""Parser registry — routes emails to the correct parser by sender.

The registry is the single public entry point for parsing emails.
It examines the From: header to determine which parser to try first,
with fallback to trying all parsers in sequence.
"""

from __future__ import annotations

import logging
import re

from app.gmail.fetch import EmailMessage
from app.parser.base import EmailParser, ParsedTransaction
from app.parser.regex.bank import parse_bank
from app.parser.regex.gpay import parse_gpay
from app.parser.regex.paytm import parse_paytm
from app.parser.regex.phonepe import parse_phonepe

logger = logging.getLogger(__name__)

# Sender patterns mapped to their primary parser.
# Checked in order; first match wins.
_SENDER_ROUTES: list[tuple[re.Pattern[str], EmailParser]] = [
    (re.compile(r"google\.com", re.IGNORECASE), parse_gpay),
    (re.compile(r"phonepe", re.IGNORECASE), parse_phonepe),
    (re.compile(r"paytm", re.IGNORECASE), parse_paytm),
]

# All parsers in priority order for fallback
_ALL_PARSERS: list[EmailParser] = [
    parse_gpay,
    parse_phonepe,
    parse_paytm,
    parse_bank,
]


def parse_email(email: EmailMessage) -> ParsedTransaction | None:
    """Parse an email into a transaction using the appropriate parser.

    First tries to match the sender to a known parser. If that fails
    (or no sender match), tries all parsers in order. Returns None
    if no parser can handle the email.
    """
    sender = email.sender.lower()

    # Try sender-matched parser first
    for pattern, parser in _SENDER_ROUTES:
        if pattern.search(sender):
            result = parser(email)
            if result is not None:
                return result
            # Sender matched but parser failed — fall through to try all
            break

    # Fallback: try all parsers in order
    for parser in _ALL_PARSERS:
        result = parser(email)
        if result is not None:
            return result

    logger.info("No parser matched email %s", email.message_id)
    return None
