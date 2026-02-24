"""
Betdaq Exchange adapter.

Auth: credentials embedded in SOAP header per request (no token).
API:  Betdaq APING SOAP v2.0.

Required env vars
-----------------
  BETDAQ_USERNAME — Betdaq account username
  BETDAQ_PASSWORD — Betdaq account password
  BETDAQ_API_KEY  — Betdaq licence / API key

Signal field mapping
--------------------
  signal.market_id    → Betdaq market ID (integer string)
  signal.selection_id → Betdaq selection/runner ID (integer string)
  signal.action       → "BACK" (polarity=1) | "LAY" (polarity=2)
  signal.price        → decimal odds
  signal.stake        → stake in GBP (converted to pence: int(stake * 100))
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import requests

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager, WagerStatus

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.betdaq.com/v2.0/BetDAQAPIService"
_NS_SOAP  = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_API   = "http://www.betdaq.com/api/v2/aping"

# Betdaq polarity: 1 = back, 2 = lay
_POLARITY: dict[str, int] = {"BACK": 1, "LAY": 2}

# Betdaq order status code → ralf WagerStatus
_STATUS_MAP: dict[int, str] = {
    1: WagerStatus.OPEN,      # Unmatched
    2: WagerStatus.OPEN,      # Partially matched
    3: WagerStatus.MATCHED,   # Fully matched
    4: WagerStatus.SETTLED,   # Settled
    5: WagerStatus.LAPSED,    # Cancelled
    6: WagerStatus.LAPSED,    # Void
    7: WagerStatus.LAPSED,    # Suspended
}

_DEFAULT_TIMEOUT = 15


class BetdaqAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        missing = [v for v in ("BETDAQ_USERNAME", "BETDAQ_PASSWORD", "BETDAQ_API_KEY")
                   if not os.environ.get(v)]
        if missing:
            raise EnvironmentError(
                f"[betdaq] Missing required environment variable(s): {', '.join(missing)}"
            )
        self._username = os.environ["BETDAQ_USERNAME"]
        self._password = os.environ["BETDAQ_PASSWORD"]
        self._api_key  = os.environ["BETDAQ_API_KEY"]
        self._timeout  = config.get("timeout_seconds", _DEFAULT_TIMEOUT)
        self._session  = requests.Session()

    # ------------------------------------------------------------------
    # BaseExchangeAdapter interface
    # ------------------------------------------------------------------

    def place(self, signal: Signal) -> Wager:
        polarity = _POLARITY.get(signal.action)
        if polarity is None:
            raise ValueError(
                f"[betdaq] Invalid signal action {signal.action!r}. Expected BACK or LAY."
            )
        stake_pence = int(round(signal.stake * 100))

        body = (
            f"<api:PlaceSingleOrderNoReceipt>"
            f"  <api:order>"
            f"    <api:SelectionId>{xml_escape(signal.selection_id)}</api:SelectionId>"
            f"    <api:Polarity>{polarity}</api:Polarity>"
            f"    <api:RequestedPrice>{signal.price:.2f}</api:RequestedPrice>"
            f"    <api:RequestedSize>{stake_pence}</api:RequestedSize>"
            f"    <api:ExpectedSelectionResetCount>0</api:ExpectedSelectionResetCount>"
            f"    <api:ExpectedWithdrawalSequenceNumber>0</api:ExpectedWithdrawalSequenceNumber>"
            f"    <api:CancelOnInRunning>false</api:CancelOnInRunning>"
            f"    <api:CancelIfSelectionReset>false</api:CancelIfSelectionReset>"
            f"  </api:order>"
            f"</api:PlaceSingleOrderNoReceipt>"
        )
        root = self._soap("PlaceSingleOrderNoReceipt", body)
        ns   = {"api": _NS_API}

        order_handle = root.findtext(".//api:OrderHandle", namespaces=ns, default="")
        ret_code     = int(root.findtext(".//api:ReturnStatus/api:Code", namespaces=ns, default="0"))

        if ret_code != 0 or not order_handle:
            log.error("[betdaq] PlaceSingleOrderNoReceipt error code=%d", ret_code)
            return Wager(
                wager_id=order_handle or "failed",
                signal=signal,
                status=WagerStatus.FAILED,
                placed_at=datetime.now(timezone.utc).isoformat(),
            )

        log.info(
            "[betdaq] placed %s order_handle=%s market=%s selection=%s price=%.2f stake=%.2f",
            signal.action, order_handle, signal.market_id, signal.selection_id,
            signal.price, signal.stake,
        )
        return Wager(
            wager_id=order_handle,
            signal=signal,
            status=WagerStatus.OPEN,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        body = (
            f"<api:CancelOrders>"
            f"  <api:orderHandles>"
            f"    <api:string>{xml_escape(wager_id)}</api:string>"
            f"  </api:orderHandles>"
            f"</api:CancelOrders>"
        )
        try:
            root     = self._soap("CancelOrders", body)
            ns       = {"api": _NS_API}
            ret_code = int(root.findtext(".//api:ReturnStatus/api:Code", namespaces=ns, default="1"))
            ok       = ret_code == 0
            if ok:
                log.info("[betdaq] cancelled order_handle=%s", wager_id)
            else:
                log.warning("[betdaq] CancelOrders error code=%d for %s", ret_code, wager_id)
            return ok
        except Exception as exc:
            log.error("[betdaq] cashout failed for %s: %s", wager_id, exc)
            return False

    def get_status(self, wager_id: str) -> dict[str, Any]:
        body = (
            "<api:ListBootstrapOrders>"
            "  <api:sequence>0</api:sequence>"
            "  <api:want_rollup>false</api:want_rollup>"
            "</api:ListBootstrapOrders>"
        )
        root = self._soap("ListBootstrapOrders", body)
        ns   = {"api": _NS_API}

        for order in root.findall(".//api:Order", namespaces=ns):
            handle = order.findtext("api:Handle", namespaces=ns, default="")
            if handle == wager_id:
                status_code = int(order.findtext("api:Status", namespaces=ns, default="1"))
                matched     = float(order.findtext("api:MatchedSize", namespaces=ns, default="0")) / 100
                status      = _STATUS_MAP.get(status_code)
                if status is None:
                    log.warning("[betdaq] Unknown status code %d for %s", status_code, wager_id)
                    status = WagerStatus.OPEN
                return {
                    "wager_id":     wager_id,
                    "status":       status,
                    "matched_size": matched,
                    "profit_loss":  None,
                }

        # Not found in active orders — treat as settled
        return {
            "wager_id":     wager_id,
            "status":       WagerStatus.SETTLED,
            "matched_size": 0.0,
            "profit_loss":  None,
        }

    def list_open(self) -> list[dict[str, Any]]:
        body = (
            "<api:ListBootstrapOrders>"
            "  <api:sequence>0</api:sequence>"
            "  <api:want_rollup>false</api:want_rollup>"
            "</api:ListBootstrapOrders>"
        )
        root = self._soap("ListBootstrapOrders", body)
        ns   = {"api": _NS_API}
        out  = []
        for order in root.findall(".//api:Order", namespaces=ns):
            status_code = int(order.findtext("api:Status", namespaces=ns, default="0"))
            if status_code in (1, 2):   # Unmatched or partially matched
                handle = order.findtext("api:Handle", namespaces=ns, default="")
                out.append({"wager_id": handle, "status": WagerStatus.OPEN})
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _soap(self, action: str, body_xml: str) -> ET.Element:
        # Credentials are XML-escaped to prevent malformed envelopes if
        # username/password contain characters like <, >, &, or "
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<soap:Envelope xmlns:soap="{_NS_SOAP}" xmlns:api="{_NS_API}">'
            '  <soap:Header>'
            '    <api:ExternalApiHeader'
            '      version="2"'
            f'      licence="{xml_escape(self._api_key)}"'
            f'      username="{xml_escape(self._username)}"'
            f'      password="{xml_escape(self._password)}"'
            '      languageCode="en" />'
            '  </soap:Header>'
            f'  <soap:Body>{body_xml}</soap:Body>'
            '</soap:Envelope>'
        )
        resp = self._session.post(
            _ENDPOINT,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=UTF-8",
                "SOAPAction":   f'"{_NS_API}/{action}"',
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return ET.fromstring(resp.text)
