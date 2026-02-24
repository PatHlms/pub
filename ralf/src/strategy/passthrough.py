import logging
from typing import Any

from src.models import Signal
from src.strategy.base import BaseStrategy

log = logging.getLogger(__name__)


class PassthroughStrategy(BaseStrategy):
    """
    No-op strategy — logs every new record and returns no actionable signals.

    Used as the default scaffold strategy so the engine, reader, and wager
    manager can be exercised end-to-end before a real strategy is implemented.
    """

    def evaluate(self, records: list[dict[str, Any]]) -> list[Signal]:
        if not records:
            return []

        log.info(
            "[strategy:passthrough] %d new record(s) received — no action taken",
            len(records),
        )
        for r in records:
            log.debug(
                "[strategy:passthrough] record id=%s source=%s %s %s sold=%s %s",
                r.get("id"),
                r.get("source"),
                r.get("manufacturer", ""),
                r.get("model", ""),
                r.get("sold_price"),
                r.get("currency", ""),
            )

        return []
