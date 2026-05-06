"""Tests for KiteAuthManager.

A fake Kite client and fake Settings are injected.
No real Zerodha API calls are made. No credentials appear in the code.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from trading_engine.broker.zerodha.auth import KiteAuthManager
from trading_engine.common.exceptions import ConfigurationError


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------

class FakeKiteClient:
    """Simulates the KiteConnect auth-related API surface."""

    def __init__(self) -> None:
        self._access_token: str | None = None

    def login_url(self) -> str:
        return "https://kite.trade/connect/login?api_key=test_key"

    def generate_session(self, request_token: str, api_secret: str) -> dict:
        # Simulate a successful session response.
        return {
            "access_token": "fake_access_token_from_zerodha",
            "user_id": "AB1234",
            "user_name": "Test User",
        }

    def set_access_token(self, token: str) -> None:
        self._access_token = token


class FakeSettings:
    """Minimal settings with the three Zerodha SecretStr fields."""

    def __init__(
        self,
        api_key: str = "test_api_key",
        api_secret: str = "test_api_secret",
        access_token: str = "",
    ) -> None:
        self.zerodha_api_key = SecretStr(api_key)
        self.zerodha_api_secret = SecretStr(api_secret)
        self.zerodha_access_token = SecretStr(access_token)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_kite() -> FakeKiteClient:
    return FakeKiteClient()


@pytest.fixture
def settings() -> FakeSettings:
    return FakeSettings()


@pytest.fixture
def auth(fake_kite: FakeKiteClient, settings: FakeSettings) -> KiteAuthManager:
    return KiteAuthManager(kite_client=fake_kite, settings=settings)


# ---------------------------------------------------------------------------
# Construction and repr
# ---------------------------------------------------------------------------

class TestKiteAuthManagerConstruction:
    def test_instantiates(self, auth: KiteAuthManager) -> None:
        assert auth is not None

    def test_repr_does_not_expose_secrets(self, auth: KiteAuthManager) -> None:
        r = repr(auth)
        assert "test_api_key" not in r
        assert "test_api_secret" not in r

    def test_repr_shows_connection_state(self, auth: KiteAuthManager) -> None:
        r = repr(auth)
        assert "api_key_set=True" in r
        assert "token_valid=False" in r  # No token yet


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------

class TestValidateToken:
    def test_token_invalid_when_empty(self, auth: KiteAuthManager) -> None:
        assert auth.validate_token() is False

    def test_token_valid_when_pre_set(self, fake_kite: FakeKiteClient) -> None:
        settings = FakeSettings(access_token="pre_existing_token")
        auth = KiteAuthManager(kite_client=fake_kite, settings=settings)
        assert auth.validate_token() is True

    def test_token_valid_after_generate_session(self, auth: KiteAuthManager) -> None:
        auth.generate_session("some_request_token")
        assert auth.validate_token() is True


# ---------------------------------------------------------------------------
# get_login_url
# ---------------------------------------------------------------------------

class TestGetLoginUrl:
    def test_returns_url_from_fake_client(self, auth: KiteAuthManager) -> None:
        url = auth.get_login_url()
        assert url.startswith("https://")
        assert "kite.trade" in url

    def test_raises_if_api_key_missing(self, fake_kite: FakeKiteClient) -> None:
        settings = FakeSettings(api_key="")
        auth = KiteAuthManager(kite_client=fake_kite, settings=settings)
        with pytest.raises(ConfigurationError, match="ZERODHA_API_KEY"):
            auth.get_login_url()


# ---------------------------------------------------------------------------
# generate_session
# ---------------------------------------------------------------------------

class TestGenerateSession:
    def test_sets_token_on_kite_client(
        self, auth: KiteAuthManager, fake_kite: FakeKiteClient
    ) -> None:
        auth.generate_session("req_token_xyz")
        assert fake_kite._access_token == "fake_access_token_from_zerodha"

    def test_validate_token_true_after_generate(self, auth: KiteAuthManager) -> None:
        auth.generate_session("req_token_xyz")
        assert auth.validate_token() is True

    def test_raises_if_api_key_missing(self, fake_kite: FakeKiteClient) -> None:
        settings = FakeSettings(api_key="")
        auth = KiteAuthManager(kite_client=fake_kite, settings=settings)
        with pytest.raises(ConfigurationError, match="ZERODHA_API_KEY"):
            auth.generate_session("req_token")

    def test_raises_if_api_secret_missing(self, fake_kite: FakeKiteClient) -> None:
        settings = FakeSettings(api_secret="")
        auth = KiteAuthManager(kite_client=fake_kite, settings=settings)
        with pytest.raises(ConfigurationError, match="ZERODHA_API_SECRET"):
            auth.generate_session("req_token")

    def test_raises_if_request_token_empty(self, auth: KiteAuthManager) -> None:
        with pytest.raises(ConfigurationError, match="request_token"):
            auth.generate_session("")


# ---------------------------------------------------------------------------
# get_access_token_value
# ---------------------------------------------------------------------------

class TestGetAccessTokenValue:
    def test_returns_empty_string_when_no_token(self, auth: KiteAuthManager) -> None:
        assert auth.get_access_token_value() == ""

    def test_returns_token_after_generate_session(self, auth: KiteAuthManager) -> None:
        auth.generate_session("req_token")
        token = auth.get_access_token_value()
        assert token == "fake_access_token_from_zerodha"

    def test_raw_secret_not_in_repr(self, auth: KiteAuthManager) -> None:
        auth.generate_session("req_token")
        # The token itself must not leak via repr
        assert "fake_access_token_from_zerodha" not in repr(auth)
