"""Regex-based email parsers for Indian UPI payment providers."""

from app.parser.regex.bank import parse_bank
from app.parser.regex.gpay import parse_gpay
from app.parser.regex.paytm import parse_paytm
from app.parser.regex.phonepe import parse_phonepe

__all__ = ["parse_bank", "parse_gpay", "parse_paytm", "parse_phonepe"]
