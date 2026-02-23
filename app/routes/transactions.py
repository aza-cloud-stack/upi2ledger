"""Transaction review routes — approve, reject, and list pending transactions.

All routes require authentication. Approval writes to the hledger journal
and optionally saves the merchant mapping for future auto-classification.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db.models import (
    get_connection,
    get_pending_transactions,
    get_transaction_by_id,
    update_transaction_status,
)
from app.ledger.mapper import save_merchant_mapping
from app.ledger.writer import format_transaction, write_entries
from app.security import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["transactions"])
templates = Jinja2Templates(directory="templates", autoescape=True)


@router.get("", response_class=HTMLResponse)
async def list_transactions(
    request: Request,
    username: str = Depends(require_auth),
) -> HTMLResponse:
    """Show pending transactions for review."""
    db_path = request.app.state.db_path
    conn = get_connection(db_path)
    try:
        pending = get_pending_transactions(conn, status="pending")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "username": username,
            "transactions": pending,
        },
    )


@router.post("/{transaction_id}/approve", response_model=None)
async def approve_transaction(
    request: Request,
    transaction_id: int,
    username: str = Depends(require_auth),
) -> RedirectResponse:
    """Approve a pending transaction — write to hledger journal."""
    settings = request.app.state.settings
    db_path = request.app.state.db_path

    form = await request.form()
    account_override = form.get("account", "")
    save_mapping = form.get("save_mapping", "")

    conn = get_connection(db_path)
    try:
        txn = get_transaction_by_id(conn, transaction_id)
        if txn is None:
            return RedirectResponse(
                url="/transactions?error=Transaction+not+found", status_code=303
            )

        if txn["status"] != "pending":
            return RedirectResponse(
                url="/transactions?error=Transaction+already+processed", status_code=303
            )

        # Determine the expense/income account
        if isinstance(account_override, str) and account_override.strip():
            expense_account = account_override.strip()
        elif txn["suggested_account"]:
            expense_account = txn["suggested_account"]
        else:
            expense_account = (
                "expenses:miscellaneous" if txn["direction"] == "sent" else "income:miscellaneous"
            )

        try:
            amount = Decimal(txn["amount"])
        except (InvalidOperation, TypeError):
            return RedirectResponse(
                url="/transactions?error=Invalid+transaction+amount", status_code=303
            )

        payment_account = settings.journal.default_payment_account
        try:
            entry = format_transaction(
                date=txn["date"],
                payee=txn["payee"],
                amount=amount,
                direction=txn["direction"],
                expense_account=expense_account,
                payment_account=payment_account,
                upi_ref=txn["upi_ref"],
            )
        except ValueError:
            return RedirectResponse(url="/transactions?error=Invalid+account+name", status_code=303)

        write_entries([entry], settings.journal.path)

        update_transaction_status(conn, transaction_id, "approved", expense_account)
        conn.commit()

        if save_mapping == "on":
            save_merchant_mapping(db_path, txn["payee"], expense_account)

    finally:
        conn.close()

    logger.info("Transaction approved and written to journal")
    return RedirectResponse(url="/transactions?success=Transaction+approved", status_code=303)


@router.post("/{transaction_id}/reject")
async def reject_transaction(
    request: Request,
    transaction_id: int,
    username: str = Depends(require_auth),
) -> RedirectResponse:
    """Reject a pending transaction."""
    db_path = request.app.state.db_path

    conn = get_connection(db_path)
    try:
        txn = get_transaction_by_id(conn, transaction_id)
        if txn is None:
            return RedirectResponse(
                url="/transactions?error=Transaction+not+found", status_code=303
            )

        update_transaction_status(conn, transaction_id, "rejected")
        conn.commit()
    finally:
        conn.close()

    logger.info("Transaction rejected")
    return RedirectResponse(url="/transactions?success=Transaction+rejected", status_code=303)
