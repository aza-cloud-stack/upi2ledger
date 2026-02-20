"""Login and logout routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.security import RateLimiter, create_session_token, verify_password

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates", autoescape=True)

# Module-level rate limiter instance (5 attempts / 15 min)
login_limiter = RateLimiter(max_attempts=5, window_seconds=900)


def _client_ip(request: Request) -> str:
    """Extract client IP for rate limiting."""
    if request.client:
        return request.client.host
    return "unknown"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_model=None)
async def login_submit(request: Request) -> HTMLResponse | RedirectResponse:
    """Validate credentials, set session cookie, or re-render with error."""
    settings = request.app.state.settings
    ip = _client_ip(request)

    # Rate limit check
    if not login_limiter.check(ip):
        logger.info("Login rate limited for IP")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Too many login attempts. Please try again later."},
            status_code=429,
        )

    form = await request.form()
    username = form.get("username", "")
    password = form.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        login_limiter.record(ip)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials."}, status_code=401
        )

    # Validate credentials
    if username == settings.app.auth.username and verify_password(
        password, settings.app.auth.password_hash
    ):
        login_limiter.reset(ip)
        token = create_session_token(username, settings.app.secret_key)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            samesite="lax",
            secure=not settings.app.debug,
            max_age=86400,
        )
        logger.info("Login successful for user")
        return response

    # Failed login
    login_limiter.record(ip)
    logger.info("Login failed attempt")
    return templates.TemplateResponse(
        request, "login.html", {"error": "Invalid credentials."}, status_code=401
    )


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="session")
    logger.info("User logged out")
    return response
