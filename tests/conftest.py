"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import bcrypt
import pytest
import yaml
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models import init_db
from app.gmail.fetch import EmailMessage
from app.main import create_app
from app.routes.auth import login_limiter

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# A known bcrypt hash for the password "testpass123"
TEST_PASSWORD = "testpass123"
TEST_PASSWORD_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()


def make_test_config(
    secret_key: str = "test-secret-key-not-default",
    password_hash: str | None = None,
    debug: bool = True,
    **overrides: object,
) -> dict[str, object]:
    """Build a valid config dict for testing."""
    if password_hash is None:
        password_hash = TEST_PASSWORD_HASH
    config: dict[str, object] = {
        "app": {
            "secret_key": secret_key,
            "debug": debug,
            "host": "127.0.0.1",
            "port": 8000,
            "allowed_hosts": ["127.0.0.1", "localhost"],
            "auth": {
                "username": "admin",
                "password_hash": password_hash,
            },
        },
        "journal": {
            "path": "test.journal",
            "default_payment_account": "assets:bank:sbi:savings",
        },
        "gmail": {
            "query": "test query",
            "credentials_path": "data/gmail_credentials.json",
            "token_path": "data/gmail_token.json",
        },
        "sync": {
            "interval_hours": 6,
        },
        "llm": {
            "enabled": False,
            "url": "http://localhost:11434",
        },
    }
    config.update(overrides)
    return config


@pytest.fixture
def valid_config_dict() -> dict[str, object]:
    """A valid configuration dictionary."""
    return make_test_config()


@pytest.fixture
def valid_settings(valid_config_dict: dict[str, object]) -> Settings:
    """A valid Settings instance."""
    return Settings(**valid_config_dict)  # type: ignore[arg-type]


@pytest.fixture
def config_file(valid_config_dict: dict[str, object], tmp_path: Path) -> Path:
    """Write a valid config.yaml to a temp directory and return its path."""
    config_path = tmp_path / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(valid_config_dict, f)
    return config_path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def test_db(db_path: Path) -> Path:
    """Initialize a test database and return its path."""
    init_db(db_path)
    return db_path


@pytest.fixture
def client(
    valid_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """Create a FastAPI TestClient with valid settings."""
    # Use temp db path
    monkeypatch.setattr("app.db.models.get_db_path", lambda: tmp_path / "test.db")
    monkeypatch.chdir(Path(__file__).parent.parent)

    # Reset rate limiter between tests
    login_limiter._attempts.clear()

    app = create_app(settings=valid_settings)
    with TestClient(app) as tc:
        yield tc


def login(client: TestClient) -> TestClient:
    """Log in to the test client and return it with session cookie set."""
    client.post("/login", data={"username": "admin", "password": TEST_PASSWORD})
    return client


def load_fixture(name: str) -> EmailMessage:
    """Load a test fixture file into an EmailMessage.

    Fixture format: headers (From, Subject, Date) followed by a blank line
    then the body text.
    """
    path = FIXTURES_DIR / name
    text = path.read_text(encoding="utf-8")
    headers_section, _, body = text.partition("\n\n")

    headers: dict[str, str] = {}
    for line in headers_section.strip().splitlines():
        key, _, value = line.partition(": ")
        headers[key.strip()] = value.strip()

    return EmailMessage(
        message_id=f"fixture-{name}",
        date=headers.get("Date", ""),
        sender=headers.get("From", ""),
        subject=headers.get("Subject", ""),
        body=body.strip(),
    )
