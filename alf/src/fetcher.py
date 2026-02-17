import logging
import os
import time
from threading import Lock
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class TokenBucket:
    """
    Thread-safe token bucket for rate limiting.

    Allows up to `burst` tokens initially; refills at `rate` tokens/second.
    Calling consume() blocks until a token is available.
    """

    def __init__(self, rate: float, burst: int = 1) -> None:
        self._rate   = rate
        self._burst  = burst
        self._tokens = float(burst)
        self._last   = time.monotonic()
        self._lock   = Lock()

    def consume(self) -> None:
        """Block until one token is available, then consume it."""
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last
            self._last   = now
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rate

        # Sleep outside the lock so other threads can manage their own buckets
        time.sleep(wait)
        with self._lock:
            self._tokens = 0.0


class Fetcher:
    """
    HTTP client for a single auction site.

    Wraps a requests.Session with:
      - Auth injection from site config (api_key / bearer / basic /
        oauth2_client_credentials / none)
      - Rate limiting via TokenBucket
      - Automatic retry with exponential backoff via urllib3 Retry
      - OAuth2 token refresh when tokens are near expiry

    One Fetcher instance is created per enabled site in client.py.
    Fetcher instances are NOT shared across sites.
    """

    def __init__(self, site_config: dict[str, Any], global_retry: dict[str, Any]) -> None:
        self._config  = site_config
        self._session = requests.Session()

        # Merge retry config: site takes precedence over global defaults
        retry_cfg = {**global_retry, **site_config.get("retry", {})}
        self._configure_retry(retry_cfg)

        # OAuth2 state (used only when auth type is oauth2_client_credentials)
        self._oauth2_token:      Optional[str]   = None
        self._oauth2_expires_at: float           = 0.0

        self._inject_auth(site_config.get("auth", {}))

        rl = site_config.get("rate_limit", {})
        self._bucket = TokenBucket(
            rate  = float(rl.get("requests_per_second", 1.0)),
            burst = int(rl.get("burst", 1)),
        )

    # ------------------------------------------------------------------
    # Public HTTP interface
    # ------------------------------------------------------------------

    def get(self, url: str, params: Optional[dict] = None, **kwargs: Any) -> Any:
        """Rate-limited, retrying GET. Returns parsed JSON."""
        self._refresh_oauth2_if_needed()
        self._bucket.consume()
        log.debug("[%s] GET %s params=%s", self._config["name"], url, params)
        response = self._session.get(url, params=params, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    def post(self, url: str, **kwargs: Any) -> Any:
        """Rate-limited, retrying POST. Returns parsed JSON."""
        self._refresh_oauth2_if_needed()
        self._bucket.consume()
        log.debug("[%s] POST %s", self._config["name"], url)
        response = self._session.post(url, timeout=30, **kwargs)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _configure_retry(self, retry_cfg: dict[str, Any]) -> None:
        retry = Retry(
            total            = retry_cfg.get("max_attempts", 3),
            backoff_factor   = retry_cfg.get("backoff_factor", 2.0),
            status_forcelist = retry_cfg.get("retry_on_status", [429, 500, 502, 503, 504]),
            allowed_methods  = ["GET", "POST"],
            raise_on_status  = False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def _inject_auth(self, auth_config: dict[str, Any]) -> None:
        """
        Inject authentication into the session.

        Credentials are read from environment variables at Fetcher
        construction time so that missing env vars surface early as
        KeyError during startup rather than silently mid-batch.
        """
        auth_type = auth_config.get("type", "none")

        if auth_type == "api_key":
            header  = auth_config["header"]
            env_var = auth_config["env_var"]
            self._session.headers[header] = os.environ[env_var]

        elif auth_type == "bearer":
            token = os.environ[auth_config["env_var"]]
            self._session.headers["Authorization"] = f"Bearer {token}"

        elif auth_type == "basic":
            username = os.environ[auth_config["username_env_var"]]
            password = os.environ[auth_config["password_env_var"]]
            self._session.auth = (username, password)

        elif auth_type == "oauth2_client_credentials":
            self._fetch_oauth2_token(auth_config)

        elif auth_type == "none":
            pass

        else:
            raise ValueError(f"Unknown auth type: {auth_type!r}")

    # ------------------------------------------------------------------
    # OAuth2 helpers
    # ------------------------------------------------------------------

    def _fetch_oauth2_token(self, auth_config: Optional[dict[str, Any]] = None) -> None:
        """
        Obtain an OAuth2 client credentials token and set it on the session.
        Stores expiry time so _refresh_oauth2_if_needed() can check it.
        """
        if auth_config is None:
            auth_config = self._config.get("auth", {})

        token_url     = auth_config["token_url"]
        client_id     = os.environ[auth_config["client_id_env_var"]]
        client_secret = os.environ[auth_config["client_secret_env_var"]]
        scope         = auth_config.get("scope", "")

        payload: dict[str, str] = {
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        }
        if scope:
            payload["scope"] = scope

        log.debug("[%s] fetching OAuth2 token from %s", self._config["name"], token_url)
        # Use a bare session (no retry adapter) for the token endpoint to avoid
        # infinite retry loops if credentials are wrong.
        resp = requests.post(token_url, data=payload, timeout=30)
        resp.raise_for_status()
        token_data = resp.json()

        self._oauth2_token = token_data["access_token"]
        expires_in = int(token_data.get("expires_in", 3600))
        # Refresh 60 seconds before actual expiry to avoid using an expired token
        self._oauth2_expires_at = time.monotonic() + expires_in - 60

        self._session.headers["Authorization"] = f"Bearer {self._oauth2_token}"
        log.debug("[%s] OAuth2 token obtained, expires in %ds", self._config["name"], expires_in)

    def _refresh_oauth2_if_needed(self) -> None:
        """Re-fetch the OAuth2 token if it is expired or near expiry."""
        auth_type = self._config.get("auth", {}).get("type", "none")
        if auth_type != "oauth2_client_credentials":
            return
        if time.monotonic() >= self._oauth2_expires_at:
            log.info("[%s] OAuth2 token expired — refreshing", self._config["name"])
            self._fetch_oauth2_token()
