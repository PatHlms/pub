import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from src.adapters import ADAPTER_REGISTRY
from src.fetcher import Fetcher
from src.fx import FXProvider
from src.models import AuctionRecord
from src.storage import AuctionStorage

log = logging.getLogger(__name__)


class HarvestClient:
    """
    Orchestrator for a single micro-batch harvest run.

    Adapters and their underlying Fetchers (HTTP sessions) are constructed
    once at startup and reused across every call to run(), so TCP connections
    and OAuth2 tokens survive between batches. FXProvider is similarly
    long-lived and refreshes exchange rates only when its TTL expires.
    """

    def __init__(self, config_dir: str, data_dir: Optional[str] = None) -> None:
        self._settings    = self._load_json(Path(config_dir) / "settings.json")
        self._data_dir    = data_dir or self._settings.get("data_dir", "data")
        self._max_workers = self._settings.get("max_workers", 4)
        self._storage     = AuctionStorage(self._data_dir)
        # Build once; reuse sessions and auth tokens across all batch runs.
        self._adapters = self._build_adapters(
            self._load_json(Path(config_dir) / "sites.json").get("sites", [])
        )
        fx_cfg = self._settings.get("fx", {})
        self._fx: Optional[FXProvider] = FXProvider(fx_cfg) if fx_cfg.get("enabled") else None

    @property
    def batch_interval_seconds(self) -> int:
        return self._settings.get("batch_interval_seconds", 300)

    def run(self) -> dict[str, Any]:
        """
        Execute one harvest batch.

        Returns a stats dict:
        {
            "sites_attempted": int,
            "sites_succeeded": int,
            "sites_failed":    int,
            "records_fetched": int,
            "records_written": int,
            "site_stats":      { site_name: {"fetched": int, "written": int} }
        }
        """
        if not self._adapters:
            log.warning("No enabled sites configured.")
            return _empty_stats()

        log.info("Starting batch: %d site(s)", len(self._adapters))
        results:  dict[str, list[AuctionRecord]] = {}
        failures: dict[str, str]                 = {}

        with ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(self._adapters)),
            thread_name_prefix="alf-site",
        ) as executor:
            future_to_name = {
                executor.submit(adapter.fetch): name
                for name, adapter in self._adapters.items()
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    records = future.result()
                    results[name] = records
                    log.info("[%s] fetched %d records", name, len(records))
                except Exception as exc:
                    failures[name] = str(exc)
                    log.error("[%s] site fetch failed: %s", name, exc)
                    results[name] = []

        # Apply FX in the main thread; the long-lived FXProvider refreshes
        # its rate table automatically when the TTL expires.
        if self._fx:
            for name in results:
                for record in results[name]:
                    _apply_fx(record, self._fx)

        site_stats: dict[str, dict[str, int]] = {}
        total_fetched = 0
        total_written = 0

        for name, records in results.items():
            fetched = len(records)
            written = self._storage.save(records)
            total_fetched += fetched
            total_written += written
            site_stats[name] = {"fetched": fetched, "written": written}

        log.info(
            "Batch complete: %d fetched, %d written, %d site(s) failed",
            total_fetched, total_written, len(failures),
        )

        return {
            "sites_attempted": len(self._adapters),
            "sites_succeeded": len(self._adapters) - len(failures),
            "sites_failed":    len(failures),
            "records_fetched": total_fetched,
            "records_written": total_written,
            "site_stats":      site_stats,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_adapters(self, sites: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Construct one Fetcher + Adapter per enabled site.

        Both objects are long-lived: the Fetcher wraps a requests.Session
        that maintains a connection pool, and the Adapter caches its
        field_mapping at construction time.
        """
        global_retry = self._settings.get("retry", {})
        adapters: dict[str, Any] = {}
        for site in sites:
            if not site.get("enabled", False):
                continue
            adapter_name = site.get("adapter", "rest")
            adapter_cls  = ADAPTER_REGISTRY.get(adapter_name)
            if adapter_cls is None:
                raise ValueError(
                    f"Unknown adapter {adapter_name!r} for site {site['name']!r}. "
                    f"Available: {list(ADAPTER_REGISTRY)}"
                )
            adapters[site["name"]] = adapter_cls(site, Fetcher(site, global_retry))
        return adapters

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def _apply_fx(record: AuctionRecord, fx: FXProvider) -> None:
    record.base_currency      = fx.base_currency
    record.sold_price_base    = fx.convert(record.sold_price,    record.currency)
    record.reserve_price_base = fx.convert(record.reserve_price, record.currency)
    record.start_price_base   = fx.convert(record.start_price,   record.currency)


def _empty_stats() -> dict[str, Any]:
    return {
        "sites_attempted": 0,
        "sites_succeeded": 0,
        "sites_failed":    0,
        "records_fetched": 0,
        "records_written": 0,
        "site_stats":      {},
    }
