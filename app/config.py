"""Configuration loader — reads and validates config.yaml via Pydantic."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, field_validator


class AuthConfig(BaseModel):
    """Authentication credentials configuration."""

    username: str
    password_hash: str

    @field_validator("password_hash")
    @classmethod
    def password_hash_not_empty(cls, v: str) -> str:
        if not v.strip():
            msg = (
                "password_hash must not be empty — generate with: "
                'python -c "import bcrypt; '
                "print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())\""
            )
            raise ValueError(msg)
        return v


class AppConfig(BaseModel):
    """Core application configuration."""

    secret_key: str
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    auth: AuthConfig

    @field_validator("secret_key")
    @classmethod
    def secret_key_not_default(cls, v: str) -> str:
        if v == "CHANGE-ME":
            msg = (
                "secret_key must be changed from default — "
                'generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
            raise ValueError(msg)
        return v


class JournalConfig(BaseModel):
    """hledger journal file configuration."""

    path: str
    default_payment_account: str = "assets:bank:sbi:savings"


class GmailConfig(BaseModel):
    """Gmail API query configuration."""

    query: str = "subject:(UPI OR GPay OR PhonePe OR Paytm) newer_than:7d"
    labels: list[str] = []
    credentials_path: str = "data/gmail_credentials.json"
    token_path: str = "data/gmail_token.json"  # noqa: S105


class SyncConfig(BaseModel):
    """Email sync scheduling configuration."""

    interval_hours: int = 6
    auto_approve_known: bool = False


class LLMConfig(BaseModel):
    """Local LLM (Ollama) configuration."""

    enabled: bool = False
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    url: str = "http://localhost:11434"

    @field_validator("url")
    @classmethod
    def url_must_be_localhost(cls, v: str) -> str:
        parsed = urlparse(v)
        hostname = parsed.hostname or ""
        if hostname not in ("localhost", "127.0.0.1", "::1"):
            msg = "LLM url must point to localhost — remote LLM endpoints are not allowed"
            raise ValueError(msg)
        return v


class Settings(BaseModel):
    """Top-level application settings."""

    app: AppConfig
    journal: JournalConfig
    gmail: GmailConfig = GmailConfig()
    sync: SyncConfig = SyncConfig()
    llm: LLMConfig = LLMConfig()


def load_settings(path: Path = Path("config.yaml")) -> Settings:
    """Load and validate settings from a YAML config file.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If config values fail validation.
    """
    if not path.exists():
        msg = (
            f"Config file not found: {path} — "
            "copy config.example.yaml to config.yaml and fill in your values"
        )
        raise FileNotFoundError(msg)

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        msg = "Config file must be a YAML mapping"
        raise ValueError(msg)

    return Settings(**raw)
