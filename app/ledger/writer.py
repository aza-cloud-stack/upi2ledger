"""hledger journal entry generator and file writer.

Generates valid hledger journal entries from approved transactions
and appends them to the configured journal file.
"""

from __future__ import annotations

import logging
import os
import re
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

# Valid hledger account name: lowercase alphanumeric, colon, dash, underscore
_ACCOUNT_PATTERN = re.compile(r"^[a-z][a-z0-9:_-]*$")


def format_inr(amount: Decimal) -> str:
    """Format an INR amount with Indian numbering and rupee symbol.

    Uses hledger convention: "₹ " with a space after the symbol.

    Examples:
        Decimal("500") -> "₹ 500.00"
        Decimal("1000") -> "₹ 1,000.00"
        Decimal("100000") -> "₹ 1,00,000.00"
        Decimal("1234567.89") -> "₹ 12,34,567.89"
    """
    amount = amount.quantize(Decimal("0.01"))
    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)

    parts = str(abs_amount).split(".")
    integer_part = parts[0]
    decimal_part = parts[1] if len(parts) > 1 else "00"

    # Indian numbering: first group of 3 from right, then groups of 2
    if len(integer_part) <= 3:
        formatted_int = integer_part
    else:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        groups: list[str] = []
        while remaining:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        groups.reverse()
        formatted_int = ",".join(groups) + "," + last_three

    return f"{sign}₹ {formatted_int}.{decimal_part}"


def format_transaction(
    *,
    date: str,
    payee: str,
    amount: Decimal,
    direction: str,
    expense_account: str,
    payment_account: str,
    upi_ref: str | None = None,
) -> str:
    """Generate an hledger journal entry string.

    Args:
        date: Transaction date in YYYY-MM-DD format.
        payee: Sanitized payee/merchant name.
        amount: Transaction amount as Decimal.
        direction: "sent" or "received".
        expense_account: The expense/income account.
        payment_account: The payment/bank account.
        upi_ref: Optional UPI reference number (added as comment).

    Returns:
        A valid hledger journal entry string with trailing newline.

    Raises:
        ValueError: If account names are invalid.
    """
    if not _ACCOUNT_PATTERN.match(expense_account):
        msg = f"Invalid expense account name: {expense_account}"
        raise ValueError(msg)
    if not _ACCOUNT_PATTERN.match(payment_account):
        msg = f"Invalid payment account name: {payment_account}"
        raise ValueError(msg)

    formatted_amount = format_inr(amount)

    lines: list[str] = []

    header = f"{date} * {payee}"
    if upi_ref:
        header += f"  ; UPI Ref: {upi_ref}"
    lines.append(header)

    if direction == "sent":
        lines.append(f"    {expense_account}    {formatted_amount}")
        lines.append(f"    {payment_account}")
    else:
        lines.append(f"    {payment_account}    {formatted_amount}")
        lines.append(f"    {expense_account}")

    # Trailing blank line (hledger convention between entries)
    lines.append("")

    return "\n".join(lines) + "\n"


def write_entries(entries: list[str], journal_path: str) -> int:
    """Append journal entries to the hledger journal file.

    Creates parent directories if needed. Expands ~ in path.
    Sets file permissions to 0o600 (owner read/write only).

    Args:
        entries: List of formatted journal entry strings.
        journal_path: Path to the journal file (may contain ~).

    Returns:
        Number of entries written.
    """
    if not entries:
        return 0

    path = Path(journal_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    content = "\n".join(entries)

    if path.exists():
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    else:
        # Create with restricted permissions using os.open
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, content.encode("utf-8"))
        finally:
            os.close(fd)

    os.chmod(path, 0o600)

    logger.info("Wrote %d entries to journal", len(entries))
    return len(entries)
