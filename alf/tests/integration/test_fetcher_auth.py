"""
Integration tests for Fetcher authentication injection.

Verifies that each auth type reads the correct env vars, sets the right
session headers, and handles OAuth2 token refresh properly.
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from src.fetcher import Fetcher


GLOBAL_RETRY = {"max_attempts": 1, "backoff_factor": 1.0, "retry_on_status": []}


def _token_resp(token="access-token-123", expires_in=3600):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"access_token": token, "expires_in": expires_in}
    return resp


def _api_key_config(header="X-API-Key", env_var="TEST_API_KEY"):
    return {
        "name": "test_site",
        "base_url": "https://api.example.com",
        "endpoints": {"auctions": "/v1/lots"},
        "auth": {"type": "api_key", "header": header, "env_var": env_var},
        "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
        "retry": {},
    }


def _bearer_config(env_var="TEST_BEARER_TOKEN"):
    return {
        "name": "test_site",
        "base_url": "https://api.example.com",
        "endpoints": {"auctions": "/v1/lots"},
        "auth": {"type": "bearer", "env_var": env_var},
        "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
        "retry": {},
    }


def _oauth2_config(token_url="https://auth.example.com/token"):
    return {
        "name": "test_site",
        "base_url": "https://api.example.com",
        "endpoints": {"auctions": "/v1/lots"},
        "auth": {
            "type": "oauth2_client_credentials",
            "token_url": token_url,
            "client_id_env_var": "TEST_CLIENT_ID",
            "client_secret_env_var": "TEST_CLIENT_SECRET",
            "scope": "read:data",
        },
        "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
        "retry": {},
    }


def _none_config():
    return {
        "name": "test_site",
        "base_url": "https://api.example.com",
        "endpoints": {"auctions": "/v1/lots"},
        "auth": {"type": "none"},
        "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
        "retry": {},
    }


# ---------------------------------------------------------------------------
# API key auth
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    def test_api_key_header_set_on_session(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "secret-key-abc")
        fetcher = Fetcher(_api_key_config(), GLOBAL_RETRY)
        assert fetcher._session.headers.get("X-API-Key") == "secret-key-abc"

    def test_custom_header_name(self, monkeypatch):
        monkeypatch.setenv("MOTORS_KEY", "motors-secret")
        config = _api_key_config(header="X-Motors-API-Key", env_var="MOTORS_KEY")
        fetcher = Fetcher(config, GLOBAL_RETRY)
        assert fetcher._session.headers.get("X-Motors-API-Key") == "motors-secret"

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("TEST_API_KEY", raising=False)
        with pytest.raises(KeyError):
            Fetcher(_api_key_config(), GLOBAL_RETRY)


# ---------------------------------------------------------------------------
# Bearer auth
# ---------------------------------------------------------------------------

class TestBearerAuth:
    def test_bearer_authorization_header_set(self, monkeypatch):
        monkeypatch.setenv("TEST_BEARER_TOKEN", "tok-xyz")
        fetcher = Fetcher(_bearer_config(), GLOBAL_RETRY)
        assert fetcher._session.headers.get("Authorization") == "Bearer tok-xyz"

    def test_missing_bearer_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("TEST_BEARER_TOKEN", raising=False)
        with pytest.raises(KeyError):
            Fetcher(_bearer_config(), GLOBAL_RETRY)


# ---------------------------------------------------------------------------
# No-auth
# ---------------------------------------------------------------------------

class TestNoAuth:
    def test_none_auth_sets_no_auth_headers(self):
        fetcher = Fetcher(_none_config(), GLOBAL_RETRY)
        assert "Authorization" not in fetcher._session.headers
        assert "X-API-Key" not in fetcher._session.headers

    def test_unknown_auth_type_raises(self):
        config = {**_none_config(), "auth": {"type": "magic_token"}}
        with pytest.raises(ValueError, match="Unknown auth type"):
            Fetcher(config, GLOBAL_RETRY)


# ---------------------------------------------------------------------------
# OAuth2 client credentials
# ---------------------------------------------------------------------------

class TestOAuth2Auth:
    def test_token_fetched_at_init(self, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "client-id")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "client-secret")
        with patch("requests.post", return_value=_token_resp("my-token")) as mock_post:
            fetcher = Fetcher(_oauth2_config(), GLOBAL_RETRY)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == "https://auth.example.com/token"
        data = call_kwargs[1]["data"]
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "client-id"
        assert data["client_secret"] == "client-secret"
        assert data["scope"] == "read:data"

    def test_bearer_token_set_on_session(self, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "cid")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "csec")
        with patch("requests.post", return_value=_token_resp("the-token")):
            fetcher = Fetcher(_oauth2_config(), GLOBAL_RETRY)
        assert fetcher._session.headers.get("Authorization") == "Bearer the-token"

    def test_token_expiry_stored_with_60s_margin(self, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "cid")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "csec")
        with patch("requests.post", return_value=_token_resp(expires_in=3600)):
            t_before = time.monotonic()
            fetcher = Fetcher(_oauth2_config(), GLOBAL_RETRY)
            t_after = time.monotonic()
        # expires_at should be ~3540s from now (3600 - 60 margin)
        assert t_before + 3539 <= fetcher._oauth2_expires_at <= t_after + 3541

    def test_expired_token_refreshed_before_get(self, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "cid")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "csec")

        token_calls = {"n": 0}

        def fake_post(*args, **kwargs):
            token_calls["n"] += 1
            return _token_resp(f"token-{token_calls['n']}")

        with patch("requests.post", side_effect=fake_post):
            fetcher = Fetcher(_oauth2_config(), GLOBAL_RETRY)

        # Force expiry
        fetcher._oauth2_expires_at = time.monotonic() - 1

        api_resp = MagicMock()
        api_resp.raise_for_status = MagicMock()
        api_resp.json.return_value = {"lots": []}

        with patch("requests.post", side_effect=fake_post):
            fetcher._session.get = MagicMock(return_value=api_resp)
            fetcher.get("https://api.example.com/v1/lots")

        assert token_calls["n"] == 2  # initial + refresh
        assert "Bearer token-2" == fetcher._session.headers.get("Authorization")

    def test_non_expired_token_not_refreshed(self, monkeypatch):
        monkeypatch.setenv("TEST_CLIENT_ID", "cid")
        monkeypatch.setenv("TEST_CLIENT_SECRET", "csec")

        token_calls = {"n": 0}

        def fake_post(*args, **kwargs):
            token_calls["n"] += 1
            return _token_resp(expires_in=3600)

        with patch("requests.post", side_effect=fake_post):
            fetcher = Fetcher(_oauth2_config(), GLOBAL_RETRY)

        api_resp = MagicMock()
        api_resp.raise_for_status = MagicMock()
        api_resp.json.return_value = {}
        fetcher._session.get = MagicMock(return_value=api_resp)

        fetcher.get("https://api.example.com/v1/lots")
        fetcher.get("https://api.example.com/v1/lots")

        assert token_calls["n"] == 1  # only initial fetch

    def test_missing_client_id_raises(self, monkeypatch):
        monkeypatch.delenv("TEST_CLIENT_ID", raising=False)
        monkeypatch.setenv("TEST_CLIENT_SECRET", "csec")
        with pytest.raises(KeyError):
            with patch("requests.post", return_value=_token_resp()):
                Fetcher(_oauth2_config(), GLOBAL_RETRY)
