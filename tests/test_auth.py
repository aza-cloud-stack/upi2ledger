"""Tests for auth routes — login, logout, protected routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD


class TestLoginPage:
    """Test GET /login."""

    def test_renders_form(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.status_code == 200
        assert "Login" in response.text
        assert '<input type="text"' in response.text
        assert '<input type="password"' in response.text


class TestLoginSubmit:
    """Test POST /login."""

    def test_valid_credentials_redirects(self, client: TestClient) -> None:
        response = client.post(
            "/login",
            data={"username": "admin", "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "session" in response.cookies

    def test_invalid_password_returns_error(self, client: TestClient) -> None:
        response = client.post(
            "/login",
            data={"username": "admin", "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.text

    def test_invalid_username_returns_error(self, client: TestClient) -> None:
        response = client.post(
            "/login",
            data={"username": "hacker", "password": TEST_PASSWORD},
        )
        assert response.status_code == 401
        assert "Invalid credentials" in response.text

    def test_rate_limited_after_attempts(self, client: TestClient) -> None:
        for _ in range(5):
            client.post("/login", data={"username": "x", "password": "x"})
        response = client.post("/login", data={"username": "x", "password": "x"})
        assert response.status_code == 429
        assert "Too many login attempts" in response.text


class TestProtectedRoutes:
    """Test that protected routes require authentication."""

    def test_index_redirects_without_session(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_index_accessible_with_session(self, client: TestClient) -> None:
        # Login first — follow redirect to establish session cookie in client
        login_resp = client.post(
            "/login",
            data={"username": "admin", "password": TEST_PASSWORD},
            follow_redirects=False,
        )
        assert login_resp.status_code == 303
        # Set the session cookie on the client
        session_cookie = login_resp.cookies.get("session")
        assert session_cookie is not None
        client.cookies.set("session", session_cookie)

        response = client.get("/")
        assert response.status_code == 200
        assert "Welcome to upi2ledger" in response.text
        assert "admin" in response.text


class TestLogout:
    """Test GET /logout."""

    def test_clears_cookie_and_redirects(self, client: TestClient) -> None:
        # Login first
        client.post(
            "/login",
            data={"username": "admin", "password": TEST_PASSWORD},
        )
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_after_logout_index_requires_login(self, client: TestClient) -> None:
        # Login
        client.post(
            "/login",
            data={"username": "admin", "password": TEST_PASSWORD},
        )
        # Logout
        client.get("/logout")
        # Try accessing index
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
