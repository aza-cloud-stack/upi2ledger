"""Tests for app.config — Pydantic config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, load_settings

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
