"""Gmail connection and OAuth2 callback routes.

All routes require authentication via the session cookie.
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


@router.get("/connect", response_class=HTMLResponse)
async def gmail_connect(request: Request, username: str = Depends(require_auth)) -> HTMLResponse:
    """Show Gmail connection status page."""
    settings = request.app.state.settings
    token_path = Path(settings.gmail.token_path)
    connected = is_connected(token_path)

    error = request.query_params.get("error")
    success = request.query_params.get("success")

    return templates.TemplateResponse(
        request,
        "gmail_connect.html",
        {
            "username": username,
            "connected": connected,
            "error": error,
            "success": success,
        },
    )


@router.get("/authorize")
async def gmail_authorize(
    request: Request, username: str = Depends(require_auth)
) -> RedirectResponse:
    """Start OAuth2 flow — redirect to Google consent screen."""
    settings = request.app.state.settings
    credentials_path = Path(settings.gmail.credentials_path)

    # Build redirect URI for the callback
    redirect_uri = str(request.url_for("gmail_callback"))

    try:
        flow = create_auth_flow(credentials_path, redirect_uri)
    except FileNotFoundError:
        logger.info("Gmail credentials file not found")
        return RedirectResponse(
            url="/gmail/connect?error=Gmail+credentials+file+not+found.+Download+OAuth2+credentials+from+GCP+Console+and+save+as+data/gmail_credentials.json",
            status_code=303,
        )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )

    # Store state in httponly cookie for CSRF protection
    response = RedirectResponse(url=authorization_url, status_code=303)
    response.set_cookie(
        key="oauth_state",
        value=state,
        httponly=True,
        samesite="lax",  # Must be Lax for cross-site redirect from Google
        secure=not settings.app.debug,
        max_age=600,  # 10 minutes
    )

    logger.info("Gmail OAuth2 flow started")
    return response


@router.get("/callback")
async def gmail_callback(
    request: Request, username: str = Depends(require_auth)
) -> RedirectResponse:
    """Handle Google's OAuth2 redirect — exchange code for tokens."""
    settings = request.app.state.settings

    # Check for error from Google
    error = request.query_params.get("error")
    if error:
        logger.info("Gmail OAuth2 error from Google: %s", error)
        return RedirectResponse(
            url="/gmail/connect?error=Google+authorization+was+denied+or+failed",
            status_code=303,
        )

    # Validate state (CSRF protection)
    state_param = request.query_params.get("state", "")
    state_cookie = request.cookies.get("oauth_state", "")

    if not state_param or not state_cookie or state_param != state_cookie:
        logger.info("Gmail OAuth2 state mismatch — possible CSRF")
        return RedirectResponse(
            url="/gmail/connect?error=Authorization+failed+—+state+mismatch.+Please+try+again",
            status_code=303,
        )

    # Exchange authorization code for tokens
    code = request.query_params.get("code", "")
    credentials_path = Path(settings.gmail.credentials_path)
    token_path = Path(settings.gmail.token_path)
    redirect_uri = str(request.url_for("gmail_callback"))

    try:
        flow = create_auth_flow(credentials_path, redirect_uri)
        exchange_code_for_credentials(flow, code, token_path)
    except Exception:
        logger.info("Gmail OAuth2 token exchange failed")
        return RedirectResponse(
            url="/gmail/connect?error=Failed+to+complete+authorization.+Please+try+again",
            status_code=303,
        )

    # Clear the state cookie
    success_url = "/gmail/connect?success=Gmail+connected+successfully"
    response = RedirectResponse(url=success_url, status_code=303)
    response.delete_cookie(key="oauth_state")

    logger.info("Gmail OAuth2 callback completed successfully")
    return response


@router.get("/disconnect")
async def gmail_disconnect(
    request: Request, username: str = Depends(require_auth)
) -> RedirectResponse:
    """Remove Gmail token and disconnect."""
    settings = request.app.state.settings
    token_path = Path(settings.gmail.token_path)

    if token_path.exists():
        token_path.unlink()
        logger.info("Gmail token removed")

    return RedirectResponse(
        url="/gmail/connect?success=Gmail+disconnected",
        status_code=303,
    )
