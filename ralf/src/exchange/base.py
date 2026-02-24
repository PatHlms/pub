from abc import ABC, abstractmethod
from typing import Any

from src.models import Signal, Wager


class BaseExchangeAdapter(ABC):
    """
    Abstract interface for exchange adapters.

    Concrete adapters implement this interface for a specific exchange
    (e.g. Betfair, Smarkets, Matchbook). The stub adapter satisfies the
    interface without making real API calls, enabling dry-run operation.

    All methods must be safe to call repeatedly; idempotency is preferred
    where the exchange API supports it.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @abstractmethod
    def place(self, signal: Signal) -> Wager:
        """
        Place a wager on the exchange for the given signal.

        Returns a Wager with status "open" (unmatched at this point).
        Raises on hard errors (auth failure, invalid market, etc.).
        """

    @abstractmethod
    def cashout(self, wager_id: str) -> bool:
        """
        Request an immediate cashout (partial or full) for an open wager.

        Returns True if the cashout was accepted, False if unavailable
        (e.g. wager already settled or market suspended).
        """

    @abstractmethod
    def get_status(self, wager_id: str) -> dict[str, Any]:
        """
        Retrieve current status of a wager from the exchange.

        Returns a dict with at minimum:
            status       : str  — exchange status string
            matched_size : float — portion of stake matched
            profit_loss  : float | None — realised P&L if settled
        """

    @abstractmethod
    def list_open(self) -> list[dict[str, Any]]:
        """
        List all open/unmatched wagers currently on the exchange account.

        Returns a list of dicts with at minimum:
            wager_id : str
            status   : str
        """
