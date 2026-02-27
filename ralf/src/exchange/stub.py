from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager, WagerStatus

log = logging.getLogger(__name__)


class StubAdapter(BaseExchangeAdapter):
    """
    Dry-run exchange adapter — logs all calls, returns plausible mock data.

    No credentials required; no real API calls are made. Useful for
    end-to-end testing of the engine and wager manager before connecting
    to a live exchange.

    Simulated behaviour:
    - place()      → returns a Wager with status "open"
    - get_status() → returns "matched" for all wagers (simulates instant fill)
    - cashout()    → always succeeds (returns True)
    - list_open()  → returns empty list (exchange has no real state)
    """

    def place(self, signal: Signal) -> Wager:
        wager_id = str(uuid.uuid4())
        log.info(
            "[exchange:stub] PLACE %s | market=%s selection=%s price=%.2f stake=%.2f | record=%s | %s",
            signal.action,
            signal.market_id,
            signal.selection_id,
            signal.price,
            signal.stake,
            signal.record_id,
            signal.rationale,
        )
        return Wager(
            wager_id=wager_id,
            signal=signal,
            status=WagerStatus.OPEN,
            placed_at=datetime.now(timezone.utc).isoformat(),
        )

    def cashout(self, wager_id: str) -> bool:
        log.info("[exchange:stub] CASHOUT wager_id=%s → accepted (stub)", wager_id)
        return True

    def get_status(self, wager_id: str) -> dict[str, Any]:
        log.debug("[exchange:stub] GET_STATUS wager_id=%s → matched (stub)", wager_id)
        return {
            "wager_id":     wager_id,
            "status":       WagerStatus.MATCHED,
            "matched_size": 1.0,
            "profit_loss":  None,
        }

    def list_open(self) -> list[dict[str, Any]]:
        log.debug("[exchange:stub] LIST_OPEN → [] (stub)")
        return []
