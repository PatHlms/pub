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
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager

log = logging.getLogger(__name__)

_BASE_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
_AUTH_URL = "https://identitysso-cert.betfair.com/api/certlogin"

_STATUS_MAP = {
    "EXECUTABLE":         "open",
    "EXECUTION_COMPLETE": "settled",
}


class BetfairAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_key  = os.environ["BETFAIR_APP_KEY"]
        self._username = os.environ["BETFAIR_USERNAME"]
        self._password = os.environ["BETFAIR_PASSWORD"]
        self._cert     = (
            os.environ["BETFAIR_CERT_PATH"],
            os.environ["BETFAIR_KEY_PATH"],
        )
        self._session_token: str | None = None
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
                    "side": signal.action,          # "BACK" or "LAY"
                    "orderType": "LIMIT",
                    "limitOrder": {
                        "size":            signal.stake,
                        "price":           signal.price,
                        "persistenceType": "LAPSE",
                    },
                }
            ],
        }
        result = self._post("placeOrders", payload)
        reports = result.get("instructionReports", [{}])
        report  = reports[0] if reports else {}
        bet_id  = report.get("betId", "")
        ok      = report.get("status") == "SUCCESS"

        if not ok:
            err = report.get("errorCode", "UNKNOWN")
            log.error("[betfair] placeOrders failed: %s", err)
            return Wager(
                wager_id=bet_id or "failed",
                signal=signal,
                status="failed",
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
            status="open",
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        """
        Cancels an unmatched portion of a bet.

        For fully matched bets Betfair requires placing an opposing LIMIT bet
        at current lay/back price to achieve a full cashout — implement that
        in a future iteration using placeOrders with the opposing side.
        """
        try:
            result = self._post("cancelOrders", {
                "instructions": [{"betId": wager_id}],
            })
            reports = result.get("instructionReports", [{}])
            ok = bool(reports and reports[0].get("status") == "SUCCESS")
            if ok:
                log.info("[betfair] cancelled bet_id=%s", wager_id)
            else:
                log.warning("[betfair] cancelOrders returned non-SUCCESS for %s", wager_id)
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
                "status":       "settled",
                "matched_size": 0.0,
                "profit_loss":  None,
            }
        order = orders[0]
        return {
            "wager_id":     wager_id,
            "status":       _STATUS_MAP.get(order.get("status", ""), "open"),
            "matched_size": order.get("sizeMatched", 0.0),
            "profit_loss":  order.get("bspLiability"),
        }

    def list_open(self) -> list[dict[str, Any]]:
        result = self._post("listCurrentOrders", {"orderProjection": "EXECUTABLE"})
        orders = result.get("currentOrders", [])
        return [
            {"wager_id": o["betId"], "status": "open"}
            for o in orders
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _authenticate(self) -> None:
        resp = requests.post(
            _AUTH_URL,
            data={"username": self._username, "password": self._password},
            cert=self._cert,
            headers={
                "X-Application": self._app_key,
                "Accept":        "application/json",
            },
            timeout=15,
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
            "X-Application":  self._app_key,
            "X-Authentication": self._session_token,
            "Content-Type":   "application/json",
            "Accept":         "application/json",
        }

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{_BASE_URL}/{endpoint}/"
        resp = self._session.post(url, json=payload, headers=self._headers(), timeout=15)
        if resp.status_code == 401:
            log.debug("[betfair] session expired — re-authenticating")
            self._session_token = None
            resp = self._session.post(url, json=payload, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()
