from abc import ABC, abstractmethod
from typing import Any

from src.models import AuctionRecord


class BaseAdapter(ABC):
    """
    Abstract base for all site-specific adapters.

    Each concrete adapter is responsible for:
      1. Fetching raw auction data from a site (using the provided Fetcher).
      2. Parsing raw response dicts into AuctionRecord instances.

    The adapter does NOT manage HTTP sessions, auth, or rate limiting directly.
    Those concerns belong to Fetcher, which is injected at construction time.

    Attributes
    ----------
    name : str
        Class-level identifier matching the "adapter" field in sites.json.
        Used by the adapter registry in __init__.py.
    """

    name: str = ""

    def __init__(self, site_config: dict[str, Any], fetcher: Any) -> None:
        """
        Parameters
        ----------
        site_config : dict
            The full site entry from sites.json (includes field_mapping,
            endpoints, default_params, pagination, etc.).
        fetcher : Fetcher
            Pre-configured Fetcher instance for this site. The adapter
            calls fetcher.get() / fetcher.post() rather than using
            requests directly.
        """
        self.config = site_config
        self.fetcher = fetcher

    @abstractmethod
    def fetch(self) -> list[AuctionRecord]:
        """
        Execute all necessary HTTP calls for this site and return a
        list of AuctionRecord instances.

        Must not raise on individual record parse failures — log the
        error and continue with the remaining records.
        """

    @abstractmethod
    def parse(self, raw_response: Any) -> list[AuctionRecord]:
        """
        Transform a raw API response into AuctionRecord instances using
        self.config["field_mapping"].

        Called by fetch(). Can be called independently in tests.
        """
