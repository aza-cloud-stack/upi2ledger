"""Configuration loader — reads and validates config.yaml via Pydantic."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, field_validator, model_validator


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


class GmailAccountConfig(BaseModel):
    """A single Gmail account configuration."""

    id: str
    label: str
    token_path: str
    query: str = ""  # per-account override; empty = use top-level default

    @field_validator("id")
    @classmethod
    def id_must_be_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_-]{0,29}$", v):
            msg = (
                "Account id must be a lowercase slug (a-z, 0-9, -, _), "
                "start with a letter, max 30 chars"
            )
            raise ValueError(msg)
        return v


class GmailConfig(BaseModel):
    """Gmail API configuration with multi-account support."""

    query: str = "subject:(UPI OR GPay OR PhonePe OR Paytm) newer_than:7d"
    labels: list[str] = []
    credentials_path: str = "data/gmail_credentials.json"
    accounts: list[GmailAccountConfig] = []

    # Backward-compatible field (deprecated, single-account)
    token_path: str | None = None

    @model_validator(mode="after")
    def migrate_single_account(self) -> GmailConfig:
        """If old-style token_path is set and no accounts, auto-create one."""
        if self.token_path and not self.accounts:
            self.accounts = [
                GmailAccountConfig(
                    id="default",
                    label="Gmail",
                    token_path=self.token_path,
                )
            ]
        if not self.accounts:
            self.accounts = [
                GmailAccountConfig(
                    id="default",
                    label="Gmail",
                    token_path="data/gmail_token.json",  # noqa: S106
                )
            ]
        return self

    @field_validator("accounts")
    @classmethod
    def accounts_ids_must_be_unique(
        cls, v: list[GmailAccountConfig],
    ) -> list[GmailAccountConfig]:
        ids = [a.id for a in v]
        if len(ids) != len(set(ids)):
            msg = "Gmail account IDs must be unique"
            raise ValueError(msg)
        return v

    def get_account(self, account_id: str) -> GmailAccountConfig | None:
        """Look up an account by id."""
        for acct in self.accounts:
            if acct.id == account_id:
                return acct
        return None

    def get_query_for_account(self, account_id: str) -> str:
        """Return the effective query for an account (per-account or top-level default)."""
        acct = self.get_account(account_id)
        if acct and acct.query:
            return acct.query
        return self.query


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
