"""
Matchbook Exchange adapter.

Auth: username/password → session-token (header).
API:  Matchbook REST API (edge/rest).

Required env vars
-----------------
  MATCHBOOK_USERNAME — Matchbook account username
  MATCHBOOK_PASSWORD — Matchbook account password

Signal field mapping
--------------------
  signal.market_id    → Matchbook market ID
                        Optionally dot-separated: "{event_id}.{market_id}"
                        to supply the required event-id field.
  signal.selection_id → Matchbook runner ID
  signal.action       → "BACK" | "LAY"
  signal.price        → decimal odds
  signal.stake        → stake in GBP
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager, WagerStatus

log = logging.getLogger(__name__)

_BASE_URL        = "https://api.matchbook.com/edge/rest"
_DEFAULT_TIMEOUT = 15

_REQUIRED_VARS = ("MATCHBOOK_USERNAME", "MATCHBOOK_PASSWORD")

_STATUS_MAP: dict[str, str] = {
    "open":               WagerStatus.OPEN,
    "matched":            WagerStatus.MATCHED,
    "partially-matched":  WagerStatus.OPEN,
    "cancelled":          WagerStatus.CANCELLED,
    "settled":            WagerStatus.SETTLED,
}


class MatchbookAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
        if missing:
            raise EnvironmentError(
                f"[matchbook] Missing required environment variable(s): {', '.join(missing)}"
            )
        self._username      = os.environ["MATCHBOOK_USERNAME"]
        self._password      = os.environ["MATCHBOOK_PASSWORD"]
        self._timeout       = config.get("timeout_seconds", _DEFAULT_TIMEOUT)
        self._session_token: Optional[str] = None
        self._account_id:   Optional[str] = None
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })

    # ------------------------------------------------------------------
    # BaseExchangeAdapter interface
    # ------------------------------------------------------------------

    def place(self, signal: Signal) -> Wager:
        self._ensure_auth()
        side = signal.action.lower()   # "back" or "lay"

        # market_id may encode event_id as "{event_id}.{market_id}"
        if "." in signal.market_id:
            event_id, market_id = signal.market_id.split(".", 1)
        else:
            event_id  = signal.market_id
            market_id = signal.market_id

        payload = {
            "offers": [
                {
                    "event-id":     event_id,
                    "market-id":    market_id,
                    "runner-id":    signal.selection_id,
                    "side":         side,
                    "odds":         signal.price,
                    "stake":        signal.stake,
                    "keep-in-play": False,
                }
            ]
        }
        resp    = self._request("POST", "/offers", json=payload)
        offers  = resp.get("offers", [{}])
        offer   = offers[0] if offers else {}
        offer_id = str(offer.get("id", ""))
        status   = self._map_status(offer.get("status", ""), offer_id)

        log.info(
            "[matchbook] placed %s offer_id=%s market=%s runner=%s price=%.2f stake=%.2f",
            signal.action, offer_id, market_id, signal.selection_id,
            signal.price, signal.stake,
        )
        return Wager(
            wager_id=offer_id,
            signal=signal,
            status=status,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        self._ensure_auth()
        try:
            resp = self._request("DELETE", f"/offers/{wager_id}")
            ok = resp.get("_status_code", 200) in (200, 204)
            if ok:
                log.info("[matchbook] cancelled offer_id=%s", wager_id)
            else:
                log.warning("[matchbook] cancel non-OK for %s", wager_id)
            return ok
        except Exception as exc:
            log.error("[matchbook] cashout failed for %s: %s", wager_id, exc)
            return False

    def get_status(self, wager_id: str) -> dict[str, Any]:
        self._ensure_auth()
        resp  = self._request("GET", f"/offers/{wager_id}")
        offer = resp.get("offer", {})
        return {
            "wager_id":     wager_id,
            "status":       self._map_status(offer.get("status", ""), wager_id),
            "matched_size": offer.get("matched-amount", 0.0),
            "profit_loss":  offer.get("profit-and-loss"),
        }

    def list_open(self) -> list[dict[str, Any]]:
        self._ensure_auth()
        resp   = self._request(
            "GET", "/offers",
            params={"status": "open,partially-matched", "offset": 0, "per-page": 100},
        )
        offers = resp.get("offers", [])
        return [{"wager_id": str(o["id"]), "status": WagerStatus.OPEN} for o in offers]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _map_status(self, raw: str, wager_id: str = "") -> str:
        status = _STATUS_MAP.get(raw)
        if status is None:
            log.warning(
                "[matchbook] unknown offer status %r%s — treating as open",
                raw, f" for {wager_id}" if wager_id else "",
            )
            return WagerStatus.OPEN
        return status

    def _authenticate(self) -> None:
        resp = requests.post(
            f"{_BASE_URL}/security/session",
            json={"username": self._username, "password": self._password},
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._session_token = data.get("session-token", "")
        self._account_id    = str(data.get("account", {}).get("id", ""))
        self._session.headers.update({"session-token": self._session_token})
        log.debug("[matchbook] authenticated account_id=%s", self._account_id)

    def _ensure_auth(self) -> None:
        if not self._session_token:
            self._authenticate()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Execute an HTTP request with a single automatic re-auth on 401."""
        url  = f"{_BASE_URL}{path}"
        resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
        if resp.status_code == 401:
            log.debug("[matchbook] session expired — re-authenticating")
            self._session_token = None
            self._ensure_auth()
            resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
        if resp.status_code == 204:
            return {"_status_code": 204}
        resp.raise_for_status()
        return resp.json()
