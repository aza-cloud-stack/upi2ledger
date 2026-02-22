"""Gmail connection and OAuth2 callback routes.

All routes require authentication via the session cookie.
Supports multiple Gmail accounts — each with its own OAuth token.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.gmail.auth import (
    create_auth_flow,
    exchange_code_for_credentials,
    is_connected,
)
from app.security import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])
templates = Jinja2Templates(directory="templates", autoescape=True)


@router.get("/accounts", response_class=HTMLResponse)
async def gmail_accounts(
    request: Request, username: str = Depends(require_auth),
) -> HTMLResponse:
    """Show all Gmail account connection statuses."""
    settings = request.app.state.settings
    accounts_status = []
    for acct in settings.gmail.accounts:
        token_path = Path(acct.token_path)
        connected = is_connected(token_path)
        accounts_status.append({
            "id": acct.id,
            "label": acct.label,
            "connected": connected,
        })

    error = request.query_params.get("error")
    success = request.query_params.get("success")

    return templates.TemplateResponse(
        request,
        "gmail_accounts.html",
        {
            "username": username,
            "accounts": accounts_status,
            "error": error,
            "success": success,
        },
    )


@router.get("/connect")
async def gmail_connect_redirect(
    request: Request, username: str = Depends(require_auth),
) -> RedirectResponse:
    """Redirect old connect URL to new accounts page."""
    return RedirectResponse(url="/gmail/accounts", status_code=301)


@router.get("/{account_id}/authorize")
async def gmail_authorize(
    request: Request, account_id: str, username: str = Depends(require_auth),
) -> RedirectResponse:
    """Start OAuth2 flow for a specific Gmail account."""
    settings = request.app.state.settings
    acct = settings.gmail.get_account(account_id)
    if acct is None:
        return RedirectResponse(
            url="/gmail/accounts?error=Unknown+account",
            status_code=303,
        )

    credentials_path = Path(settings.gmail.credentials_path)
    redirect_uri = str(request.url_for("gmail_callback"))

    try:
        flow = create_auth_flow(credentials_path, redirect_uri)
    except FileNotFoundError:
        logger.info("Gmail credentials file not found")
        return RedirectResponse(
            url="/gmail/accounts?error=Gmail+credentials+file+not+found.+Download+OAuth2+credentials+from+GCP+Console+and+save+as+data/gmail_credentials.json",
            status_code=303,
        )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    # Store state AND account_id in httponly cookie for CSRF protection.
    # Use pipe separator (not JSON) to avoid cookie escaping issues.
    cookie_value = f"{state}|{account_id}"
    response = RedirectResponse(url=authorization_url, status_code=303)
    response.set_cookie(
        key="oauth_state",
        value=cookie_value,
        httponly=True,
        samesite="lax",  # Must be Lax for cross-site redirect from Google
        secure=not settings.app.debug,
        max_age=600,  # 10 minutes
    )

    logger.info("Gmail OAuth2 flow started for account %s", account_id)
    return response


@router.get("/callback")
async def gmail_callback(
    request: Request, username: str = Depends(require_auth),
) -> RedirectResponse:
    """Handle Google's OAuth2 redirect — exchange code for tokens."""
    settings = request.app.state.settings

    # Check for error from Google
    error = request.query_params.get("error")
    if error:
        logger.info("Gmail OAuth2 error from Google: %s", error)
        return RedirectResponse(
            url="/gmail/accounts?error=Google+authorization+was+denied+or+failed",
            status_code=303,
        )

    # Parse state cookie (format: "state|account_id")
    state_cookie_raw = request.cookies.get("oauth_state", "")
    state_param = request.query_params.get("state", "")

    if "|" not in state_cookie_raw:
        logger.info("Gmail OAuth2 state cookie invalid")
        return RedirectResponse(
            url="/gmail/accounts?error=Authorization+failed+—+invalid+state.+Please+try+again",
            status_code=303,
        )

    expected_state, account_id = state_cookie_raw.rsplit("|", 1)

    if not state_param or state_param != expected_state:
        logger.info("Gmail OAuth2 state mismatch — possible CSRF")
        return RedirectResponse(
            url="/gmail/accounts?error=Authorization+failed+—+state+mismatch.+Please+try+again",
            status_code=303,
        )

    acct = settings.gmail.get_account(account_id)
    if acct is None:
        return RedirectResponse(
            url="/gmail/accounts?error=Unknown+account",
            status_code=303,
        )

    # Exchange authorization code for tokens
    code = request.query_params.get("code", "")
    credentials_path = Path(settings.gmail.credentials_path)
    token_path = Path(acct.token_path)
    redirect_uri = str(request.url_for("gmail_callback"))

    try:
        flow = create_auth_flow(credentials_path, redirect_uri)
        exchange_code_for_credentials(flow, code, token_path)
    except Exception:
        logger.info("Gmail OAuth2 token exchange failed")
        return RedirectResponse(
            url="/gmail/accounts?error=Failed+to+complete+authorization.+Please+try+again",
            status_code=303,
        )

    # Clear the state cookie
    response = RedirectResponse(
        url="/gmail/accounts?success=Gmail+account+connected+successfully",
        status_code=303,
    )
    response.delete_cookie(key="oauth_state")

    logger.info("Gmail OAuth2 callback completed for account %s", account_id)
    return response


@router.get("/{account_id}/disconnect")
async def gmail_disconnect(
    request: Request, account_id: str, username: str = Depends(require_auth),
) -> RedirectResponse:
    """Remove Gmail token and disconnect a specific account."""
    settings = request.app.state.settings
    acct = settings.gmail.get_account(account_id)
    if acct is None:
        return RedirectResponse(
            url="/gmail/accounts?error=Unknown+account",
            status_code=303,
        )

    token_path = Path(acct.token_path)
    if token_path.exists():
        token_path.unlink()
        logger.info("Gmail token removed for account %s", account_id)

    return RedirectResponse(
        url="/gmail/accounts?success=Gmail+account+disconnected",
        status_code=303,
    )
