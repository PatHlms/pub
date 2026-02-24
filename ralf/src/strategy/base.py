from abc import ABC, abstractmethod
from typing import Any

from src.models import Signal


class BaseStrategy(ABC):
    """
    Abstract base for wager strategies.

    Concrete strategies receive a list of raw AuctionRecord dicts (as written
    by alf) and return a list of Signals describing what action to take on the
    exchange for each record of interest.

    Returning a SKIP signal (or an empty list) for a record is the safe default
    — it means no wager is placed for that record in this cycle.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @abstractmethod
    def evaluate(self, records: list[dict[str, Any]]) -> list[Signal]:
        """
        Analyse new auction records and return trade signals.

        Parameters
        ----------
        records:
            List of AuctionRecord dicts as written by alf to its flat-file store.
            Only records not previously seen are passed in (deduplication is
            handled by DataReader).

        Returns
        -------
        list[Signal]
            One signal per actionable record. SKIP signals may be omitted.
        """
