"""Tests for app.security — middleware, rate limiter, sessions, passwords."""

from __future__ import annotations

import bcrypt
from fastapi.testclient import TestClient

from app.security import (
    RateLimiter,
    create_session_token,
    verify_password,
    verify_session_token,
)


class TestSecurityHeaders:
    """Test that security headers are set on all responses."""

    def test_csp_header(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.headers["Content-Security-Policy"] == "default-src 'self'"

    def test_x_content_type_options(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.headers["X-Frame-Options"] == "DENY"

    def test_referrer_policy(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.headers["Referrer-Policy"] == "no-referrer"

    def test_permissions_policy(self, client: TestClient) -> None:
        response = client.get("/login")
        assert "camera=()" in response.headers["Permissions-Policy"]


class TestRateLimiter:
    """Test the in-memory rate limiter."""

    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        assert limiter.check("ip1") is True
        limiter.record("ip1")
        limiter.record("ip1")
        assert limiter.check("ip1") is True

    def test_blocks_at_limit(self) -> None:
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            limiter.record("ip1")
        assert limiter.check("ip1") is False

    def test_different_keys_independent(self) -> None:
        limiter = RateLimiter(max_attempts=1, window_seconds=60)
        limiter.record("ip1")
        assert limiter.check("ip1") is False
        assert limiter.check("ip2") is True

    def test_reset_clears_attempts(self) -> None:
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.record("ip1")
        limiter.record("ip1")
        assert limiter.check("ip1") is False
        limiter.reset("ip1")
        assert limiter.check("ip1") is True

    def test_expired_attempts_cleaned(self) -> None:
        limiter = RateLimiter(max_attempts=1, window_seconds=0)
        limiter.record("ip1")
        # With window_seconds=0, all attempts are immediately expired
        assert limiter.check("ip1") is True


class TestSessionTokens:
    """Test session token creation and verification."""

    def test_round_trip(self) -> None:
        token = create_session_token("admin", "secret123")
        username = verify_session_token(token, "secret123")
        assert username == "admin"

    def test_wrong_secret_rejected(self) -> None:
        token = create_session_token("admin", "secret123")
        username = verify_session_token(token, "wrong-secret")
        assert username is None

    def test_tampered_token_rejected(self) -> None:
        token = create_session_token("admin", "secret123")
        tampered = token[:-3] + "XXX"
        username = verify_session_token(tampered, "secret123")
        assert username is None

    def test_expired_token_rejected(self) -> None:
        token = create_session_token("admin", "secret123")
        # Negative max_age ensures token is treated as expired
        username = verify_session_token(token, "secret123", max_age=-1)
        assert username is None


class TestPasswordVerification:
    """Test bcrypt password verification."""

    def test_correct_password(self) -> None:
        hashed = bcrypt.hashpw(b"mypassword", bcrypt.gensalt()).decode()
        assert verify_password("mypassword", hashed) is True

    def test_wrong_password(self) -> None:
        hashed = bcrypt.hashpw(b"mypassword", bcrypt.gensalt()).decode()
        assert verify_password("wrongpassword", hashed) is False
