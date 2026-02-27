"""
Betfair Exchange adapter.

Auth: certificate-based SSL login → session token.
API:  Betfair Exchange APING REST v1.0 (JSON/HTTPS).

Required env vars
-----------------
  BETFAIR_APP_KEY    — developer application key
  BETFAIR_USERNAME   — Betfair account username
  BETFAIR_PASSWORD   — Betfair account password
  BETFAIR_CERT_PATH  — path to SSL client certificate (.crt / .pem)
  BETFAIR_KEY_PATH   — path to SSL private key (.key / .pem)

Signal field mapping
--------------------
  signal.market_id    → Betfair marketId  (e.g. "1.234567890")
  signal.selection_id → Betfair selectionId (integer string)
  signal.action       → "BACK" | "LAY"
  signal.price        → decimal odds (e.g. 2.5)
  signal.stake        → size in GBP

Notes
-----
  profit_loss in get_status() is sourced from bspLiability, which is only
  populated for BSP bets. For limit orders it will be None. A future
  iteration should pull sizeProfit from the settlements API.
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

_BASE_URL        = "https://api.betfair.com/exchange/betting/rest/v1.0"
_AUTH_URL        = "https://identitysso-cert.betfair.com/api/certlogin"
_DEFAULT_TIMEOUT = 15

_REQUIRED_VARS = (
    "BETFAIR_APP_KEY", "BETFAIR_USERNAME", "BETFAIR_PASSWORD",
    "BETFAIR_CERT_PATH", "BETFAIR_KEY_PATH",
)

_STATUS_MAP: dict[str, str] = {
    "EXECUTABLE":         WagerStatus.OPEN,
    "EXECUTION_COMPLETE": WagerStatus.SETTLED,
}


class BetfairAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
        if missing:
            raise EnvironmentError(
                f"[betfair] Missing required environment variable(s): {', '.join(missing)}"
            )
        self._app_key  = os.environ["BETFAIR_APP_KEY"]
        self._username = os.environ["BETFAIR_USERNAME"]
        self._password = os.environ["BETFAIR_PASSWORD"]
        self._cert     = (os.environ["BETFAIR_CERT_PATH"], os.environ["BETFAIR_KEY_PATH"])
        self._timeout  = config.get("timeout_seconds", _DEFAULT_TIMEOUT)
        self._session_token: Optional[str] = None
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # BaseExchangeAdapter interface
    # ------------------------------------------------------------------

    def place(self, signal: Signal) -> Wager:
        payload = {
            "marketId": signal.market_id,
            "instructions": [
                {
                    "selectionId": int(signal.selection_id),
                    "side":        signal.action,
                    "orderType":   "LIMIT",
                    "limitOrder": {
                        "size":            signal.stake,
                        "price":           signal.price,
                        "persistenceType": "LAPSE",
                    },
                }
            ],
        }
        result  = self._post("placeOrders", payload)
        reports = result.get("instructionReports", [{}])
        report  = reports[0] if reports else {}
        bet_id  = report.get("betId", "")
        ok      = report.get("status") == "SUCCESS"

        if not ok:
            log.error("[betfair] placeOrders failed: %s", report.get("errorCode", "UNKNOWN"))
            return Wager(
                wager_id=bet_id or "failed",
                signal=signal,
                status=WagerStatus.FAILED,
                placed_at=datetime.now(timezone.utc).isoformat(),
            )

        log.info(
            "[betfair] placed %s bet_id=%s market=%s selection=%s price=%.2f stake=%.2f",
            signal.action, bet_id, signal.market_id, signal.selection_id,
            signal.price, signal.stake,
        )
        return Wager(
            wager_id=bet_id,
            signal=signal,
            status=WagerStatus.OPEN,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        """
        Cancels the unmatched portion of a bet.

        For fully matched bets a true cashout requires placing an opposing
        LIMIT order at the current market price — implement via placeOrders
        with the opposing side in a future iteration.
        """
        try:
            result  = self._post("cancelOrders", {"instructions": [{"betId": wager_id}]})
            reports = result.get("instructionReports", [{}])
            ok      = bool(reports and reports[0].get("status") == "SUCCESS")
            if ok:
                log.info("[betfair] cancelled bet_id=%s", wager_id)
            else:
                err = reports[0].get("errorCode") if reports else "no report"
                log.warning("[betfair] cancelOrders non-SUCCESS for %s: %s", wager_id, err)
            return ok
        except Exception as exc:
            log.error("[betfair] cashout failed for %s: %s", wager_id, exc)
            return False

    def get_status(self, wager_id: str) -> dict[str, Any]:
        result = self._post("listCurrentOrders", {"betIds": [wager_id]})
        orders = result.get("currentOrders", [])
        if not orders:
            return {
                "wager_id":     wager_id,
                "status":       WagerStatus.SETTLED,
                "matched_size": 0.0,
                "profit_loss":  None,
            }
        order      = orders[0]
        raw_status = order.get("status", "")
        status     = _STATUS_MAP.get(raw_status)
        if status is None:
            log.warning("[betfair] unknown order status %r for %s — treating as open", raw_status, wager_id)
            status = WagerStatus.OPEN
        return {
            "wager_id":     wager_id,
            "status":       status,
            "matched_size": order.get("sizeMatched", 0.0),
            "profit_loss":  order.get("bspLiability"),   # None for non-BSP limit orders
        }

    def list_open(self) -> list[dict[str, Any]]:
        result = self._post("listCurrentOrders", {"orderProjection": "EXECUTABLE"})
        return [
            {"wager_id": o["betId"], "status": WagerStatus.OPEN}
            for o in result.get("currentOrders", [])
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _authenticate(self) -> None:
        resp = requests.post(
            _AUTH_URL,
            data={"username": self._username, "password": self._password},
            cert=self._cert,
            headers={"X-Application": self._app_key, "Accept": "application/json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("loginStatus") != "SUCCESS":
            raise RuntimeError(f"Betfair login failed: {data.get('loginStatus')}")
        self._session_token = data["sessionToken"]
        log.debug("[betfair] authenticated (session token acquired)")

    def _headers(self) -> dict[str, str]:
        if not self._session_token:
            self._authenticate()
        return {
            "X-Application":    self._app_key,
            "X-Authentication": self._session_token,
            "Content-Type":     "application/json",
            "Accept":           "application/json",
        }

    def _post(self, endpoint: str, payload: dict) -> dict:
        url  = f"{_BASE_URL}/{endpoint}/"
        resp = self._session.post(url, json=payload, headers=self._headers(), timeout=self._timeout)
        if resp.status_code == 401:
            log.debug("[betfair] session expired — re-authenticating")
            self._session_token = None
            resp = self._session.post(url, json=payload, headers=self._headers(), timeout=self._timeout)
        resp.raise_for_status()
        return resp.json()
