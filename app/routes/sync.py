"""Sync route — fetches emails, parses transactions, stores pending.

POST /sync chains:
  1. Iterate connected Gmail accounts
  2. fetch_emails() per account
  3. parse_email() on each fetched email
  4. map_merchant() for suggested_account
  5. Insert into pending_transactions
  6. mark_as_processed()
  7. Return summary
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db.models import get_connection, insert_pending_transaction
from app.gmail.auth import get_gmail_service, load_credentials
from app.gmail.fetch import fetch_emails, mark_as_processed
from app.ledger.mapper import map_merchant
from app.parser import parse_email
from app.security import RateLimiter, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sync"])
templates = Jinja2Templates(directory="templates", autoescape=True)

# Rate limit sync to prevent abuse — max 10 syncs per 15 minutes
_sync_limiter = RateLimiter(max_attempts=10, window_seconds=900)


@router.post("/sync", response_class=HTMLResponse)
async def sync_emails(
    request: Request,
    username: str = Depends(require_auth),
) -> HTMLResponse:
    """Fetch new emails from all connected accounts, parse, and store."""
    settings = request.app.state.settings
    db_path = request.app.state.db_path

    ip = request.client.host if request.client else "unknown"
    if not _sync_limiter.check(ip):
        return templates.TemplateResponse(
            request,
            "sync_results.html",
            {"error": "Too many sync requests. Please wait a few minutes."},
            status_code=429,
        )
    _sync_limiter.record(ip)

    results: list[dict[str, object]] = []
    total_fetched = 0
    total_parsed = 0
    total_skipped = 0

    for acct in settings.gmail.accounts:
        token_path = Path(acct.token_path)
        creds = load_credentials(token_path)
        if creds is None:
            results.append(
                {
                    "account": acct.label,
                    "status": "disconnected",
                    "fetched": 0,
                    "parsed": 0,
                }
            )
            continue

        try:
            service = get_gmail_service(creds)
            query = settings.gmail.get_query_for_account(acct.id)
            emails = fetch_emails(service, query, db_path, account_id=acct.id)
        except Exception:
            logger.info("Sync failed for account %s", acct.id)
            results.append(
                {
                    "account": acct.label,
                    "status": "error",
                    "fetched": 0,
                    "parsed": 0,
                }
            )
            continue

        account_fetched = len(emails)
        account_parsed = 0

        conn = get_connection(db_path)
        try:
            for email in emails:
                txn = parse_email(email)
                if txn is None:
                    total_skipped += 1
                    # Mark as processed so we don't re-fetch unparseable emails
                    mark_as_processed(db_path, email.message_id, "none", acct.id)
                    continue

                suggested = map_merchant(txn.payee, txn.direction, db_path)

                insert_pending_transaction(
                    conn,
                    date=txn.date.isoformat(),
                    amount=str(txn.amount),
                    payee=txn.payee,
                    direction=txn.direction,
                    source=txn.source,
                    upi_ref=txn.upi_ref,
                    email_message_id=txn.email_message_id,
                    confidence=txn.confidence,
                    suggested_account=suggested,
                    account_id=acct.id,
                )

                mark_as_processed(db_path, email.message_id, txn.source, acct.id)
                account_parsed += 1

            conn.commit()
        except Exception:
            conn.rollback()
            logger.info("Error storing transactions for account %s", acct.id)
            results.append(
                {
                    "account": acct.label,
                    "status": "error",
                    "fetched": account_fetched,
                    "parsed": 0,
                }
            )
            continue
        finally:
            conn.close()

        total_fetched += account_fetched
        total_parsed += account_parsed

        results.append(
            {
                "account": acct.label,
                "status": "ok",
                "fetched": account_fetched,
                "parsed": account_parsed,
            }
        )

    logger.info(
        "Sync complete: %d fetched, %d parsed, %d skipped",
        total_fetched,
        total_parsed,
        total_skipped,
    )

    return templates.TemplateResponse(
        request,
        "sync_results.html",
        {
            "results": results,
            "total_fetched": total_fetched,
            "total_parsed": total_parsed,
            "total_skipped": total_skipped,
            "error": None,
        },
    )
