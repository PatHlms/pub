import logging
import signal
import time
from typing import Any

from src.exchange.base import BaseExchangeAdapter
from src.reader import DataReader
from src.strategy.base import BaseStrategy
from src.wager_manager import WagerManager

log = logging.getLogger(__name__)


class Engine:
    """
    Main loop for ralf.

    Each cycle:
        1. poll DataReader for new alf auction records
        2. pass new records to the Strategy → get signals
        3. ask WagerManager to review open positions (cashout if profitable)
        4. ask WagerManager to process signals (place new wagers)

    Runs indefinitely (run_forever) or for a single cycle (run_once).
    Handles SIGINT / SIGTERM for graceful shutdown.
    """

    def __init__(
        self,
        settings: dict[str, Any],
        reader:   DataReader,
        strategy: BaseStrategy,
        adapter:  BaseExchangeAdapter,
        manager:  WagerManager,
    ) -> None:
        self._settings  = settings
        self._reader    = reader
        self._strategy  = strategy
        self._adapter   = adapter
        self._manager   = manager
        self._interval  = settings.get("poll_interval_seconds", 30)
        self._stop      = False
        self._cycle     = 0

    def run_once(self) -> dict[str, Any]:
        """Execute one poll cycle and return a stats dict."""
        self._cycle += 1
        cycle = self._cycle
        log.info("=== Cycle %d starting ===", cycle)
        start = time.monotonic()

        new_records = self._reader.poll()
        signals     = self._strategy.evaluate(new_records)
        self._manager.review_positions(self._adapter)
        self._manager.process_signals(signals, self._adapter)

        elapsed = time.monotonic() - start
        summary = self._manager.summary()
        log.info(
            "=== Cycle %d complete in %.2fs | new_records=%d signals=%d wagers=%s ===",
            cycle, elapsed, len(new_records), len(signals), summary,
        )
        return {
            "cycle":        cycle,
            "new_records":  len(new_records),
            "signals":      len(signals),
            "elapsed_secs": elapsed,
            "wager_summary": summary,
        }

    def run_forever(self) -> None:
        """Run cycles on the configured interval until SIGINT or SIGTERM."""
        self._register_signals()
        log.info(
            "Engine starting — poll interval: %ds. Press Ctrl+C to stop.",
            self._interval,
        )

        while not self._stop:
            self.run_once()

            if self._stop:
                break

            log.debug("Sleeping %ds until next cycle...", self._interval)
            for _ in range(self._interval):
                if self._stop:
                    break
                time.sleep(1)

        log.info("Engine stopped after %d cycle(s).", self._cycle)

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _register_signals(self) -> None:
        signal.signal(signal.SIGINT,  self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        log.info("Signal %d received — stopping after current cycle.", signum)
        self._stop = True
