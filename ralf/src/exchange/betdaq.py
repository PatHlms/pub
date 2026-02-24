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

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager

log = logging.getLogger(__name__)

_ENDPOINT  = "https://api.betdaq.com/v2.0/BetDAQAPIService"
_NS_SOAP   = "http://schemas.xmlsoap.org/soap/envelope/"
_NS_API    = "http://www.betdaq.com/api/v2/aping"

# Betdaq polarity: 1 = back, 2 = lay
_POLARITY = {"BACK": 1, "LAY": 2}

# Map Betdaq order status codes to ralf statuses
_STATUS_MAP: dict[int, str] = {
    1: "open",       # Unmatched
    2: "open",       # Partially matched
    3: "matched",    # Fully matched
    4: "settled",    # Settled
    5: "lapsed",     # Cancelled
    6: "lapsed",     # Void
    7: "lapsed",     # Suspended
}


class BetdaqAdapter(BaseExchangeAdapter):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._username = os.environ["BETDAQ_USERNAME"]
        self._password = os.environ["BETDAQ_PASSWORD"]
        self._api_key  = os.environ["BETDAQ_API_KEY"]
        self._session  = requests.Session()

    # ------------------------------------------------------------------
    # BaseExchangeAdapter interface
    # ------------------------------------------------------------------

    def place(self, signal: Signal) -> Wager:
        polarity   = _POLARITY[signal.action]
        stake_pence = int(round(signal.stake * 100))

        body = f"""
        <api:PlaceSingleOrderNoReceipt>
          <api:order>
            <api:SelectionId>{signal.selection_id}</api:SelectionId>
            <api:Polarity>{polarity}</api:Polarity>
            <api:RequestedPrice>{signal.price:.2f}</api:RequestedPrice>
            <api:RequestedSize>{stake_pence}</api:RequestedSize>
            <api:ExpectedSelectionResetCount>0</api:ExpectedSelectionResetCount>
            <api:ExpectedWithdrawalSequenceNumber>0</api:ExpectedWithdrawalSequenceNumber>
            <api:CancelOnInRunning>false</api:CancelOnInRunning>
            <api:CancelIfSelectionReset>false</api:CancelIfSelectionReset>
          </api:order>
        </api:PlaceSingleOrderNoReceipt>
        """
        root = self._soap("PlaceSingleOrderNoReceipt", body)
        ns   = {"api": _NS_API}

        order_handle = root.findtext(".//api:OrderHandle", namespaces=ns, default="")
        ret_code     = int(root.findtext(".//api:ReturnStatus/api:Code", namespaces=ns, default="0"))

        if ret_code != 0:
            log.error("[betdaq] PlaceSingleOrderNoReceipt error code=%d", ret_code)
            return Wager(
                wager_id="failed",
                signal=signal,
                status="failed",
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
            status="open",
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        body = f"""
        <api:CancelOrders>
          <api:orderHandles>
            <api:string>{wager_id}</api:string>
          </api:orderHandles>
        </api:CancelOrders>
        """
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
        body = f"""
        <api:ListBootstrapOrders>
          <api:sequence>0</api:sequence>
          <api:want_rollup>false</api:want_rollup>
        </api:ListBootstrapOrders>
        """
        root = self._soap("ListBootstrapOrders", body)
        ns   = {"api": _NS_API}

        for order in root.findall(".//api:Order", namespaces=ns):
            handle = order.findtext("api:Handle", namespaces=ns, default="")
            if handle == wager_id:
                status_code = int(order.findtext("api:Status", namespaces=ns, default="1"))
                matched     = float(order.findtext("api:MatchedSize", namespaces=ns, default="0")) / 100
                return {
                    "wager_id":     wager_id,
                    "status":       _STATUS_MAP.get(status_code, "open"),
                    "matched_size": matched,
                    "profit_loss":  None,
                }

        # Not found in current orders — assume settled
        return {
            "wager_id":     wager_id,
            "status":       "settled",
            "matched_size": 0.0,
            "profit_loss":  None,
        }

    def list_open(self) -> list[dict[str, Any]]:
        body = """
        <api:ListBootstrapOrders>
          <api:sequence>0</api:sequence>
          <api:want_rollup>false</api:want_rollup>
        </api:ListBootstrapOrders>
        """
        root = self._soap("ListBootstrapOrders", body)
        ns   = {"api": _NS_API}
        out  = []
        for order in root.findall(".//api:Order", namespaces=ns):
            status_code = int(order.findtext("api:Status", namespaces=ns, default="0"))
            if status_code in (1, 2):   # Unmatched or partially matched
                handle = order.findtext("api:Handle", namespaces=ns, default="")
                out.append({"wager_id": handle, "status": "open"})
        return out

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _soap(self, action: str, body_xml: str) -> ET.Element:
        envelope = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<soap:Envelope'
            f'  xmlns:soap="{_NS_SOAP}"'
            f'  xmlns:api="{_NS_API}">'
            f'  <soap:Header>'
            f'    <api:ExternalApiHeader'
            f'      version="2"'
            f'      licence="{self._api_key}"'
            f'      username="{self._username}"'
            f'      password="{self._password}"'
            f'      languageCode="en" />'
            f'  </soap:Header>'
            f'  <soap:Body>{body_xml}</soap:Body>'
            f'</soap:Envelope>'
        )
        resp = self._session.post(
            _ENDPOINT,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": f'text/xml; charset=UTF-8',
                "SOAPAction":   f'"{_NS_API}/{action}"',
            },
            timeout=15,
        )
        resp.raise_for_status()
        return ET.fromstring(resp.text)
