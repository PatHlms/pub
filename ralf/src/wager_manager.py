import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import filelock

from src.exchange.base import BaseExchangeAdapter
from src.models import Signal, Wager

if TYPE_CHECKING:
    from src.funds_manager import FundsManager

log = logging.getLogger(__name__)

_LOCK_TIMEOUT = 5
_WAGER_FILENAME = "wagers.json"


class WagerManager:
    """
    Tracks open wager positions and drives the place/cashout lifecycle.

    Responsibilities
    ----------------
    - Maintain an in-memory registry of all wagers (open and closed).
    - Persist the registry to {state_dir}/wagers.json after every change.
    - On each engine cycle:
        1. review_positions(): poll the exchange for status updates on open
           wagers; cashout those that exceed the profit threshold.
        2. process_signals(): for each actionable signal, optionally cashout
           an existing wager on the same market, then place a new one.

    If a FundsManager is supplied, wager placement is gated on available
    funds and debits/credits are recorded for each lifecycle event.
    """

    def __init__(
        self,
        config: dict[str, Any],
        state_dir: str,
        funds: Optional["FundsManager"] = None,
    ) -> None:
        self._max_open           = config.get("max_open_wagers", 20)
        self._profit_threshold   = config.get("cashout_profit_threshold_pct", 10.0) / 100.0
        self._cashout_on_refresh = config.get("cashout_on_signal_refresh", True)
        self._default_stake      = config.get("default_stake", 10.0)
        self._funds              = funds

        self._state_dir  = Path(state_dir)
        self._wager_file = self._state_dir / _WAGER_FILENAME
        self._lock_file  = self._state_dir / f"{_WAGER_FILENAME}.lock"

        # wager_id → Wager
        self._wagers: dict[str, Wager] = self._load_wagers()
        log.info(
            "WagerManager initialised — %d wager(s) loaded (%d open)%s",
            len(self._wagers),
            self._open_count(),
            "  [funds guard active]" if funds else "",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review_positions(self, adapter: BaseExchangeAdapter) -> None:
        """
        Poll the exchange for status updates on all open wagers.

        Wagers that settle or lapse have their stake (plus any P&L) credited
        back to FundsManager. Wagers above the profit threshold are cashed out.
        """
        open_wagers = [w for w in self._wagers.values() if w.is_open()]
        if not open_wagers:
            log.debug("WagerManager.review_positions: no open wagers")
            return

        log.debug("WagerManager.review_positions: checking %d open wager(s)", len(open_wagers))
        changed = False

        for wager in open_wagers:
            try:
                status_info = adapter.get_status(wager.wager_id)
            except Exception as exc:
                log.warning("get_status failed for %s: %s", wager.wager_id, exc)
                continue

            exchange_status = status_info.get("status", wager.status)
            pl = status_info.get("profit_loss")

            if exchange_status in ("settled", "lapsed", "cancelled"):
                wager.status      = exchange_status
                wager.profit_loss = pl
                log.info("Wager %s → %s  P&L=%s", wager.wager_id, exchange_status, pl)
                # Credit funds: return stake + profit (or stake - loss)
                if self._funds is not None:
                    if exchange_status == "settled" and pl is not None:
                        self._funds.credit(wager.signal.stake + pl, label=wager.wager_id)
                    else:
                        self._funds.credit(wager.signal.stake, label=f"{wager.wager_id} lapsed")
                changed = True
                continue

            if pl is not None and pl > 0 and pl / wager.signal.stake >= self._profit_threshold:
                if self._do_cashout(wager, adapter):
                    changed = True

        if changed:
            self._persist_wagers()

    def process_signals(self, signals: list[Signal], adapter: BaseExchangeAdapter) -> None:
        """
        For each actionable signal, optionally cashout any existing wager on
        the same market, then place a new wager if capacity and funds allow.
        """
        actionable = [s for s in signals if s.is_actionable()]
        if not actionable:
            log.debug("WagerManager.process_signals: no actionable signals")
            return

        log.info("WagerManager.process_signals: %d actionable signal(s)", len(actionable))
        changed = False

        for signal in actionable:
            if self._open_count() >= self._max_open:
                log.warning(
                    "Max open wagers (%d) reached — skipping signal for market=%s",
                    self._max_open, signal.market_id,
                )
                break

            # Funds guard — skip if insufficient balance
            if self._funds is not None and not self._funds.can_wager(signal.stake):
                log.warning(
                    "Funds guard: skipping signal for market=%s (stake=%.2f balance=%.2f)",
                    signal.market_id, signal.stake, self._funds.balance,
                )
                continue

            if self._cashout_on_refresh:
                existing = self._find_open_by_market(signal.market_id)
                if existing:
                    if self._do_cashout(existing, adapter):
                        changed = True

            wager = self._place(signal, adapter)
            if wager:
                self._wagers[wager.wager_id] = wager
                if self._funds is not None:
                    self._funds.debit(signal.stake, label=wager.wager_id)
                changed = True

        if changed:
            self._persist_wagers()

    def summary(self) -> dict[str, Any]:
        """Return a snapshot of wager counts by status."""
        counts: dict[str, int] = {}
        for w in self._wagers.values():
            counts[w.status] = counts.get(w.status, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _open_count(self) -> int:
        return sum(1 for w in self._wagers.values() if w.is_open())

    def _find_open_by_market(self, market_id: str) -> Wager | None:
        for w in self._wagers.values():
            if w.is_open() and w.signal.market_id == market_id:
                return w
        return None

    def _do_cashout(self, wager: Wager, adapter: BaseExchangeAdapter) -> bool:
        try:
            ok = adapter.cashout(wager.wager_id)
        except Exception as exc:
            log.warning("cashout failed for %s: %s", wager.wager_id, exc)
            return False

        if ok:
            from datetime import datetime, timezone
            wager.status       = "cashed_out"
            wager.cashed_out_at = datetime.now(timezone.utc).isoformat()
            log.info("Cashed out wager %s (market=%s)", wager.wager_id, wager.signal.market_id)
            # Return stake to available funds (P&L unknown at cashout time)
            if self._funds is not None:
                self._funds.credit(wager.signal.stake, label=f"{wager.wager_id} cashout")
        return ok

    def _place(self, signal: Signal, adapter: BaseExchangeAdapter) -> Wager | None:
        try:
            wager = adapter.place(signal)
            log.info(
                "Placed wager %s: %s @ %.2f stake=%.2f market=%s",
                wager.wager_id, signal.action, signal.price,
                signal.stake, signal.market_id,
            )
            return wager
        except Exception as exc:
            log.error("Failed to place wager for market=%s: %s", signal.market_id, exc)
            return None

    def _load_wagers(self) -> dict[str, Wager]:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        if not self._wager_file.exists():
            return {}
        try:
            with open(self._wager_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {d["wager_id"]: Wager.from_dict(d) for d in raw}
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            log.warning("Could not load wagers from %s: %s — starting fresh", self._wager_file, exc)
            return {}

    def _persist_wagers(self) -> None:
        try:
            with filelock.FileLock(str(self._lock_file), timeout=_LOCK_TIMEOUT):
                with open(self._wager_file, "w", encoding="utf-8") as f:
                    json.dump([w.to_dict() for w in self._wagers.values()], f, indent=2)
        except filelock.Timeout:
            log.error("Lock timeout persisting wagers — state may be slightly stale")
        except OSError as exc:
            log.error("Could not persist wagers: %s", exc)
