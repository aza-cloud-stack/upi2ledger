"""Tests for app.config — Pydantic config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import GmailAccountConfig, GmailConfig, Settings, load_settings

from .conftest import make_test_config


class TestSettingsValidation:
    """Test Pydantic validation on Settings model."""

    def test_valid_config_loads(self, valid_config_dict: dict[str, object]) -> None:
        settings = Settings(**valid_config_dict)  # type: ignore[arg-type]
        assert settings.app.secret_key == "test-secret-key-not-default"
        assert settings.app.auth.username == "admin"
        assert settings.app.debug is True

    def test_default_secret_key_rejected(self) -> None:
        config = make_test_config(secret_key="CHANGE-ME")
        with pytest.raises(ValueError, match="secret_key must be changed"):
            Settings(**config)  # type: ignore[arg-type]

    def test_empty_password_hash_rejected(self) -> None:
        config = make_test_config(password_hash="")
        with pytest.raises(ValueError, match="password_hash must not be empty"):
            Settings(**config)  # type: ignore[arg-type]

    def test_whitespace_password_hash_rejected(self) -> None:
        config = make_test_config(password_hash="   ")
        with pytest.raises(ValueError, match="password_hash must not be empty"):
            Settings(**config)  # type: ignore[arg-type]

    def test_non_localhost_llm_url_rejected(self) -> None:
        config = make_test_config()
        assert isinstance(config["llm"], dict)
        config["llm"]["url"] = "http://remote-server.com:11434"  # type: ignore[index]
        with pytest.raises(ValueError, match="localhost"):
            Settings(**config)  # type: ignore[arg-type]

    def test_localhost_llm_url_accepted(self) -> None:
        config = make_test_config()
        assert isinstance(config["llm"], dict)
        config["llm"]["url"] = "http://127.0.0.1:11434"  # type: ignore[index]
        settings = Settings(**config)  # type: ignore[arg-type]
        assert settings.llm.url == "http://127.0.0.1:11434"

    def test_ipv6_localhost_llm_url_accepted(self) -> None:
        config = make_test_config()
        assert isinstance(config["llm"], dict)
        config["llm"]["url"] = "http://[::1]:11434"  # type: ignore[index]
        settings = Settings(**config)  # type: ignore[arg-type]
        assert settings.llm.url == "http://[::1]:11434"

    def test_defaults_applied(self) -> None:
        config = make_test_config()
        settings = Settings(**config)  # type: ignore[arg-type]
        assert settings.sync.interval_hours == 6
        assert settings.llm.enabled is False
        assert settings.llm.provider == "ollama"


class TestGmailMultiAccount:
    """Test multi-account Gmail configuration."""

    def test_multi_account_config_parses(self) -> None:
        """Gmail config with explicit accounts list parses correctly."""
        config = GmailConfig(
            credentials_path="data/creds.json",
            accounts=[
                GmailAccountConfig(id="personal", label="Personal", token_path="data/t1.json"),
                GmailAccountConfig(id="work", label="Work", token_path="data/t2.json"),
            ],
        )
        assert len(config.accounts) == 2
        assert config.accounts[0].id == "personal"
        assert config.accounts[1].id == "work"

    def test_old_config_auto_migrates(self) -> None:
        """Old-style token_path auto-migrates to accounts[0] with id 'default'."""
        config = GmailConfig(token_path="data/gmail_token.json")
        assert len(config.accounts) == 1
        assert config.accounts[0].id == "default"
        assert config.accounts[0].label == "Gmail"
        assert config.accounts[0].token_path == "data/gmail_token.json"

    def test_empty_config_gets_default_account(self) -> None:
        """GmailConfig with no token_path and no accounts gets a default."""
        config = GmailConfig()
        assert len(config.accounts) == 1
        assert config.accounts[0].id == "default"

    def test_duplicate_account_ids_rejected(self) -> None:
        """Duplicate account IDs are rejected."""
        with pytest.raises(ValueError, match="unique"):
            GmailConfig(
                accounts=[
                    GmailAccountConfig(id="same", label="A", token_path="a.json"),
                    GmailAccountConfig(id="same", label="B", token_path="b.json"),
                ],
            )

    def test_invalid_account_id_rejected(self) -> None:
        """Account ID must be a lowercase slug."""
        with pytest.raises(ValueError, match="lowercase slug"):
            GmailAccountConfig(id="UPPER", label="Bad", token_path="t.json")

    def test_account_id_with_numbers_accepted(self) -> None:
        """Account ID with numbers and dashes is valid."""
        acct = GmailAccountConfig(id="gmail-2", label="Gmail 2", token_path="t.json")
        assert acct.id == "gmail-2"

    def test_get_account_found(self) -> None:
        """get_account returns the matching account."""
        config = GmailConfig(
            accounts=[
                GmailAccountConfig(id="personal", label="P", token_path="p.json"),
                GmailAccountConfig(id="work", label="W", token_path="w.json"),
            ],
        )
        acct = config.get_account("work")
        assert acct is not None
        assert acct.label == "W"

    def test_get_account_not_found(self) -> None:
        """get_account returns None for unknown ID."""
        config = GmailConfig()
        assert config.get_account("nonexistent") is None

    def test_get_query_default(self) -> None:
        """get_query_for_account returns top-level query when account has no override."""
        config = GmailConfig(
            query="default query",
            accounts=[GmailAccountConfig(id="personal", label="P", token_path="p.json")],
        )
        assert config.get_query_for_account("personal") == "default query"

    def test_get_query_per_account_override(self) -> None:
        """get_query_for_account returns per-account query when set."""
        config = GmailConfig(
            query="default query",
            accounts=[
                GmailAccountConfig(
                    id="work", label="W", token_path="w.json", query="work query",
                ),
            ],
        )
        assert config.get_query_for_account("work") == "work query"

    def test_old_config_in_full_settings(self) -> None:
        """Full Settings with old-style gmail.token_path auto-migrates."""
        config = make_test_config()
        settings = Settings(**config)  # type: ignore[arg-type]
        assert len(settings.gmail.accounts) == 1
        assert settings.gmail.accounts[0].id == "default"
        assert settings.gmail.accounts[0].token_path == "data/gmail_token.json"


class TestLoadSettings:
    """Test the load_settings file reader."""

    def test_load_from_file(self, config_file: Path) -> None:
        settings = load_settings(config_file)
        assert settings.app.secret_key == "test-secret-key-not-default"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_settings(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("just a string, not a mapping")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_settings(bad_file)
