"""Security middleware, rate limiting, session management, and auth helpers."""

from __future__ import annotations

import logging
import time
from typing import Any

import bcrypt
from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, dict-based)
# ---------------------------------------------------------------------------


class RateLimiter:
    """Simple in-memory rate limiter keyed by arbitrary string (e.g. client IP)."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 900) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = {}

    def _cleanup(self, key: str) -> None:
        """Remove expired entries for a key."""
        now = time.monotonic()
        if key in self._attempts:
            self._attempts[key] = [t for t in self._attempts[key] if now - t < self.window_seconds]
            if not self._attempts[key]:
                del self._attempts[key]

    def check(self, key: str) -> bool:
        """Return True if the key is within the rate limit, False if blocked."""
        self._cleanup(key)
        attempts = self._attempts.get(key, [])
        return len(attempts) < self.max_attempts

    def record(self, key: str) -> None:
        """Record an attempt for the given key."""
        self._cleanup(key)
        self._attempts.setdefault(key, []).append(time.monotonic())

    def reset(self, key: str) -> None:
        """Clear all attempts for a key (e.g. on successful login)."""
        self._attempts.pop(key, None)


# ---------------------------------------------------------------------------
# Session token helpers (itsdangerous)
# ---------------------------------------------------------------------------


def create_session_token(username: str, secret_key: str) -> str:
    """Create a signed, timestamped session token for the given username."""
    serializer = URLSafeTimedSerializer(secret_key)
    return serializer.dumps(username, salt="session")  # type: ignore[return-value]


def verify_session_token(token: str, secret_key: str, max_age: int = 86400) -> str | None:
    """Verify a session token and return the username, or None if invalid/expired."""
    serializer = URLSafeTimedSerializer(secret_key)
    try:
        username: Any = serializer.loads(token, salt="session", max_age=max_age)
        if isinstance(username, str):
            return username
        return None  # pragma: no cover
    except (BadSignature, SignatureExpired):
        return None


# ---------------------------------------------------------------------------
# Password verification (bcrypt)
# ---------------------------------------------------------------------------


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# Auth exception + dependency for FastAPI
# ---------------------------------------------------------------------------


class AuthRequired(Exception):
    """Raised when a request lacks valid authentication."""


async def require_auth(request: Request) -> str:
    """FastAPI dependency — returns the authenticated username or raises AuthRequired."""
    settings = request.app.state.settings
    token = request.cookies.get("session")
    if token:
        username = verify_session_token(token, settings.app.secret_key)
        if username is not None:
            return username

    raise AuthRequired
