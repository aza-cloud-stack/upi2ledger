"""Email parser subsystem.

Public API:
    parse_email(email) -> ParsedTransaction | None
    ParsedTransaction — Pydantic model for parsed transactions
"""

from app.parser.base import ParsedTransaction
from app.parser.registry import parse_email

__all__ = ["ParsedTransaction", "parse_email"]
