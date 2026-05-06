"""Tests for Zerodha login helper logic.

All tests use fake Kite clients — no real Zerodha API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from trading_engine.broker.zerodha.login import (
    exchange_request_token,
    get_login_url,
    update_env_file,
    validate_credentials,
)
from trading_engine.common.exceptions import ConfigurationError

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


def _make_settings(api_key: str = "fake_key", api_secret: str = "fake_secret") -> MagicMock:
    settings = MagicMock()
    settings.zerodha_api_key.get_secret_value.return_value = api_key
    settings.zerodha_api_secret.get_secret_value.return_value = api_secret
    settings.zerodha_access_token.get_secret_value.return_value = ""
    return settings


def _make_kite_client(
    login_url: str = "https://kite.zerodha.com/connect/login?api_key=fake",
) -> MagicMock:
    kite = MagicMock()
    kite.login_url.return_value = login_url
    kite.generate_session.return_value = {"access_token": "test_access_token_xyz"}
    return kite


# ---------------------------------------------------------------------------
# Tests: get_login_url
# ---------------------------------------------------------------------------


class TestGetLoginUrl:
    def test_returns_url_from_kite_client(self):
        settings = _make_settings()
        kite = _make_kite_client("https://example.com/login")
        url = get_login_url(settings, kite)
        assert url == "https://example.com/login"

    def test_calls_kite_login_url(self):
        settings = _make_settings()
        kite = _make_kite_client()
        get_login_url(settings, kite)
        kite.login_url.assert_called_once()

    def test_empty_api_key_raises_configuration_error(self):
        settings = _make_settings(api_key="")
        kite = _make_kite_client()
        with pytest.raises(ConfigurationError):
            get_login_url(settings, kite)

    def test_url_not_empty(self):
        settings = _make_settings()
        kite = _make_kite_client("https://kite.zerodha.com/connect/login?v=3&api_key=abc")
        url = get_login_url(settings, kite)
        assert url


# ---------------------------------------------------------------------------
# Tests: exchange_request_token
# ---------------------------------------------------------------------------


class TestExchangeRequestToken:
    def test_returns_access_token(self):
        settings = _make_settings()
        kite = _make_kite_client()
        token = exchange_request_token(settings, kite, "valid_request_token")
        assert token == "test_access_token_xyz"

    def test_calls_generate_session_with_api_secret(self):
        settings = _make_settings(api_secret="my_secret")
        kite = _make_kite_client()
        exchange_request_token(settings, kite, "req_token")
        kite.generate_session.assert_called_once_with("req_token", api_secret="my_secret")

    def test_empty_request_token_raises(self):
        settings = _make_settings()
        kite = _make_kite_client()
        with pytest.raises(ConfigurationError):
            exchange_request_token(settings, kite, "")

    def test_whitespace_only_request_token_raises(self):
        settings = _make_settings()
        kite = _make_kite_client()
        with pytest.raises(ConfigurationError):
            exchange_request_token(settings, kite, "   ")

    def test_token_is_set_on_kite_client(self):
        settings = _make_settings()
        kite = _make_kite_client()
        exchange_request_token(settings, kite, "req_token")
        kite.set_access_token.assert_called_once_with("test_access_token_xyz")

    def test_missing_api_key_raises(self):
        settings = _make_settings(api_key="")
        kite = _make_kite_client()
        with pytest.raises(ConfigurationError):
            exchange_request_token(settings, kite, "valid_token")

    def test_missing_api_secret_raises(self):
        settings = _make_settings(api_secret="")
        kite = _make_kite_client()
        with pytest.raises(ConfigurationError):
            exchange_request_token(settings, kite, "valid_token")


# ---------------------------------------------------------------------------
# Tests: validate_credentials
# ---------------------------------------------------------------------------


class TestValidateCredentials:
    def test_both_present_returns_empty_list(self):
        settings = _make_settings(api_key="real_key", api_secret="real_secret")
        missing = validate_credentials(settings)
        assert missing == []

    def test_missing_api_key_reported(self):
        settings = _make_settings(api_key="")
        missing = validate_credentials(settings)
        assert "ZERODHA_API_KEY" in missing

    def test_missing_api_secret_reported(self):
        settings = _make_settings(api_secret="")
        missing = validate_credentials(settings)
        assert "ZERODHA_API_SECRET" in missing

    def test_placeholder_value_treated_as_missing(self):
        settings = _make_settings(api_key="replace_me")
        missing = validate_credentials(settings)
        assert "ZERODHA_API_KEY" in missing

    def test_both_missing_reports_both(self):
        settings = _make_settings(api_key="", api_secret="")
        missing = validate_credentials(settings)
        assert "ZERODHA_API_KEY" in missing
        assert "ZERODHA_API_SECRET" in missing


# ---------------------------------------------------------------------------
# Tests: update_env_file
# ---------------------------------------------------------------------------


class TestUpdateEnvFile:
    def test_updates_existing_line(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ZERODHA_ACCESS_TOKEN=old_token\nOTHER=value\n")
        update_env_file(env, "new_token_abc")
        content = env.read_text()
        assert "ZERODHA_ACCESS_TOKEN=new_token_abc" in content
        assert "old_token" not in content
        assert "OTHER=value" in content  # other lines untouched

    def test_appends_when_line_missing(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=value\n")
        update_env_file(env, "new_token_abc")
        content = env.read_text()
        assert "ZERODHA_ACCESS_TOKEN=new_token_abc" in content
        assert "OTHER=value" in content

    def test_does_not_log_token(self, tmp_path, caplog):
        import logging

        env = tmp_path / ".env"
        env.write_text("ZERODHA_ACCESS_TOKEN=old\n")
        with caplog.at_level(logging.DEBUG):
            update_env_file(env, "secret_token_value")
        assert "secret_token_value" not in caplog.text

    def test_raises_if_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            update_env_file(tmp_path / "nonexistent.env", "token")

    def test_overwrites_with_equals_variants(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ZERODHA_ACCESS_TOKEN = old_token\nOTHER=x\n")
        update_env_file(env, "fresh_token")
        content = env.read_text()
        assert "fresh_token" in content
        assert "old_token" not in content

    def test_accepts_string_path(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ZERODHA_ACCESS_TOKEN=old\n")
        update_env_file(str(env), "string_path_token")
        content = env.read_text()
        assert "string_path_token" in content


# ---------------------------------------------------------------------------
# Tests: login helper script entry point
# ---------------------------------------------------------------------------


class TestLoginHelperMain:
    """Test the script entry point using fake Kite client injection."""

    def test_missing_credentials_returns_nonzero(self):
        from scripts.zerodha_login_helper import main

        # Monkeypatch settings to have empty credentials
        import trading_engine.common.config as cfg_mod

        original = cfg_mod.load_settings

        class _EmptySettings:
            zerodha_api_key = MagicMock(get_secret_value=lambda: "")
            zerodha_api_secret = MagicMock(get_secret_value=lambda: "")
            zerodha_access_token = MagicMock(get_secret_value=lambda: "")
            live_trading_enabled = False

        cfg_mod.load_settings = lambda **kw: _EmptySettings()
        try:
            result = main(argv=[], kite_client=_make_kite_client())
        finally:
            cfg_mod.load_settings = original
        assert result != 0

    def test_api_secret_never_printed(self, capsys):
        """Validate that the secret is not in stdout output during error path."""
        from scripts.zerodha_login_helper import main

        import trading_engine.common.config as cfg_mod

        original = cfg_mod.load_settings

        class _EmptySettings:
            zerodha_api_key = MagicMock(get_secret_value=lambda: "")
            zerodha_api_secret = MagicMock(get_secret_value=lambda: "my_super_secret")
            zerodha_access_token = MagicMock(get_secret_value=lambda: "")
            live_trading_enabled = False

        cfg_mod.load_settings = lambda **kw: _EmptySettings()
        try:
            main(argv=[], kite_client=_make_kite_client())
        finally:
            cfg_mod.load_settings = original

        captured = capsys.readouterr()
        assert "my_super_secret" not in captured.out
        assert "my_super_secret" not in captured.err
