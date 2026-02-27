"""
Smarkets Exchange adapter.

Auth: username/password → user_token (Bearer).
API:  Smarkets REST API v3.

Required env vars
-----------------
  SMARKETS_USERNAME — Smarkets account email / username
  SMARKETS_PASSWORD — Smarkets account password
  SMARKETS_APP_KEY  — (optional) application key

Signal field mapping
--------------------
  signal.market_id    → Smarkets market ID
  signal.selection_id → Smarkets contract ID
  signal.action       → "BACK" → side "buy" | "LAY" → side "sell"
  signal.price        → decimal odds (converted to basis-point integer: 2.5 → 250)
  signal.stake        → payout amount in GBP (converted to pence: £10 → 1000)
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

_BASE_URL        = "https://api.smarkets.com/v3"
_DEFAULT_TIMEOUT = 15

_REQUIRED_VARS = ("SMARKETS_USERNAME", "SMARKETS_PASSWORD")

_STATUS_MAP: dict[str, str] = {
    "new":              WagerStatus.OPEN,
    "partially_filled": WagerStatus.OPEN,
    "filled":           WagerStatus.SETTLED,
    "cancelled":        WagerStatus.CANCELLED,
    "expired":          WagerStatus.LAPSED,
}


class SmarketsAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
        if missing:
            raise EnvironmentError(
                f"[smarkets] Missing required environment variable(s): {', '.join(missing)}"
            )
        self._username = os.environ["SMARKETS_USERNAME"]
        self._password = os.environ["SMARKETS_PASSWORD"]
        self._app_key  = os.environ.get("SMARKETS_APP_KEY", "")
        self._timeout  = config.get("timeout_seconds", _DEFAULT_TIMEOUT)
        self._token: Optional[str] = None
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
        side      = "buy" if signal.action == "BACK" else "sell"
        price_bp  = round(signal.price * 100)       # decimal odds → basis points
        qty_pence = round(signal.stake * 100)        # GBP → pence

        payload = {
            "market_id":     signal.market_id,
            "contract_id":   signal.selection_id,
            "side":          side,
            "quantity_type": "PAYOUT",
            "price":         price_bp,
            "quantity":      qty_pence,
        }
        resp = self._session.post(f"{_BASE_URL}/orders/", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        order    = resp.json().get("order", {})
        order_id = str(order.get("id", ""))
        status   = self._map_status(order.get("status", ""), order_id)

        log.info(
            "[smarkets] placed %s order_id=%s market=%s contract=%s price=%d stake=%d",
            signal.action, order_id, signal.market_id, signal.selection_id,
            price_bp, qty_pence,
        )
        return Wager(
            wager_id=order_id,
            signal=signal,
            status=status,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        self._ensure_auth()
        try:
            resp = self._session.delete(f"{_BASE_URL}/orders/{wager_id}/", timeout=self._timeout)
            ok = resp.status_code in (200, 204)
            if ok:
                log.info("[smarkets] cancelled order_id=%s", wager_id)
            else:
                log.warning("[smarkets] cancel returned %d for %s", resp.status_code, wager_id)
            return ok
        except Exception as exc:
            log.error("[smarkets] cashout failed for %s: %s", wager_id, exc)
            return False

    def get_status(self, wager_id: str) -> dict[str, Any]:
        self._ensure_auth()
        resp = self._session.get(f"{_BASE_URL}/orders/{wager_id}/", timeout=self._timeout)
        resp.raise_for_status()
        order = resp.json().get("order", {})
        return {
            "wager_id":     wager_id,
            "status":       self._map_status(order.get("status", ""), wager_id),
            "matched_size": order.get("filled_quantity", 0) / 100,   # pence → GBP
            "profit_loss":  None,
        }

    def list_open(self) -> list[dict[str, Any]]:
        self._ensure_auth()
        resp = self._session.get(
            f"{_BASE_URL}/orders/",
            params={"status": "new,partially_filled"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
        return [{"wager_id": str(o["id"]), "status": WagerStatus.OPEN} for o in orders]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _map_status(self, raw: str, wager_id: str = "") -> str:
        status = _STATUS_MAP.get(raw)
        if status is None:
            log.warning(
                "[smarkets] unknown order status %r%s — treating as open",
                raw, f" for {wager_id}" if wager_id else "",
            )
            return WagerStatus.OPEN
        return status

    def _authenticate(self) -> None:
        resp = requests.post(
            f"{_BASE_URL}/sessions/",
            json={"login": self._username, "password": self._password},
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        self._token = resp.json()["user_token"]
        self._session.headers.update({"Authorization": self._token})
        log.debug("[smarkets] authenticated (user_token acquired)")

    def _ensure_auth(self) -> None:
        if not self._token:
            self._authenticate()
