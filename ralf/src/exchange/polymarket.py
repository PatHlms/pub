"""
Polymarket CLOB Exchange adapter.

Auth: API key credentials (generated via the Polymarket UI).
API:  Polymarket Central Limit Order Book (CLOB) REST API.

Required env vars
-----------------
  POLYMARKET_API_KEY     — CLOB API key
  POLYMARKET_API_SECRET  — CLOB API secret
  POLYMARKET_API_PASSPHRASE — CLOB API passphrase
  POLYMARKET_FUNDER_ADDRESS — (optional) Polygon wallet address for reference

Signal field mapping
--------------------
  signal.market_id    → Polymarket condition ID / token ID (the YES or NO token)
  signal.selection_id → Polymarket token ID for the specific outcome side
  signal.action       → "BACK" → side "BUY" | "LAY" → side "SELL"
  signal.price        → probability price 0.01–0.99 (e.g. 0.65 = 65¢ per $1 payout)
  signal.stake        → size in USDC (1 USDC = 1.0)

Notes
-----
  Polymarket uses USDC on Polygon; prices are expressed as probabilities (0–1).
  Orders are GTC (Good Till Cancelled) by default.
  L2 authentication uses HMAC-SHA256 signatures over timestamp + method + path + body.
"""

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager

log = logging.getLogger(__name__)

_BASE_URL = "https://clob.polymarket.com"

_STATUS_MAP = {
    "LIVE":      "open",
    "MATCHED":   "matched",
    "DELAYED":   "open",
    "FILLED":    "settled",
    "CANCELLED": "lapsed",
    "EXPIRED":   "lapsed",
    "PENDING":   "open",
}


class PolymarketAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._api_key    = os.environ["POLYMARKET_API_KEY"]
        self._api_secret = os.environ["POLYMARKET_API_SECRET"]
        self._api_pass   = os.environ["POLYMARKET_API_PASSPHRASE"]
        self._session    = requests.Session()

    # ------------------------------------------------------------------
    # BaseExchangeAdapter interface
    # ------------------------------------------------------------------

    def place(self, signal: Signal) -> Wager:
        side = "BUY" if signal.action == "BACK" else "SELL"
        payload = {
            "order": {
                "tokenID":    signal.selection_id,
                "price":      round(signal.price, 4),
                "side":       side,
                "size":       round(signal.stake, 2),
                "orderType":  "GTC",
                "feeRateBps": "0",
            }
        }
        resp = self._signed_post("/order", payload)
        data     = resp.get("orderID", "") or resp.get("order", {}).get("id", "")
        order_id = str(data)
        status   = _STATUS_MAP.get(resp.get("status", "LIVE"), "open")

        log.info(
            "[polymarket] placed %s order_id=%s token=%s price=%.4f size=%.2f",
            signal.action, order_id, signal.selection_id, signal.price, signal.stake,
        )
        return Wager(
            wager_id=order_id,
            signal=signal,
            status=status,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        try:
            resp = self._signed_delete(f"/order/{wager_id}")
            cancelled = resp.get("cancelled", False) or resp.get("success", False)
            if cancelled:
                log.info("[polymarket] cancelled order_id=%s", wager_id)
            else:
                log.warning("[polymarket] cancel response for %s: %s", wager_id, resp)
            return bool(cancelled)
        except Exception as exc:
            log.error("[polymarket] cashout failed for %s: %s", wager_id, exc)
            return False

    def get_status(self, wager_id: str) -> dict[str, Any]:
        resp = self._get(f"/order/{wager_id}")
        return {
            "wager_id":     wager_id,
            "status":       _STATUS_MAP.get(resp.get("status", "LIVE"), "open"),
            "matched_size": float(resp.get("size_matched", 0.0)),
            "profit_loss":  None,
        }

    def list_open(self) -> list[dict[str, Any]]:
        resp = self._get("/orders", params={"status": "LIVE"})
        orders = resp if isinstance(resp, list) else resp.get("data", [])
        return [{"wager_id": o["id"], "status": "open"} for o in orders]

    # ------------------------------------------------------------------
    # Internal — auth helpers
    # ------------------------------------------------------------------

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        ts        = str(int(time.time()))
        msg       = ts + method.upper() + path + body
        signature = hmac.new(
            self._api_secret.encode(),
            msg.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "POLY_ADDRESS":    os.environ.get("POLYMARKET_FUNDER_ADDRESS", ""),
            "POLY_SIGNATURE":  signature,
            "POLY_TIMESTAMP":  ts,
            "POLY_NONCE":      "0",
            "Content-Type":    "application/json",
            "Accept":          "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> Any:
        headers = self._auth_headers("GET", path)
        resp = self._session.get(
            f"{_BASE_URL}{path}", headers=headers, params=params, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def _signed_post(self, path: str, payload: dict) -> dict:
        import json
        body    = json.dumps(payload, separators=(",", ":"))
        headers = self._auth_headers("POST", path, body)
        resp    = self._session.post(
            f"{_BASE_URL}{path}", data=body, headers=headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def _signed_delete(self, path: str) -> dict:
        headers = self._auth_headers("DELETE", path)
        resp    = self._session.delete(
            f"{_BASE_URL}{path}", headers=headers, timeout=15
        )
        resp.raise_for_status()
        return resp.json()
