"""
FundsManager — available-funds tracking and Open Banking top-up.

Tracks available funds as a running balance:
    balance = initial_balance + credits - debits

Debits happen when a wager is placed (stake committed to exchange).
Credits happen when a wager is settled, lapsed, or cashed out (stake
returned, plus any profit or minus any loss).

Top-up flow
-----------
When balance drops below `top_up_threshold`, FundsManager calls
provider.initiate_payment() to transfer `top_up_amount` from the
configured bank account to the exchange account. The pending transfer
is recorded; the balance is credited only once the payment reaches
"completed" status (polled on the next cycle via poll_pending_transfers()).

Wager guard
-----------
can_wager(stake) returns False when:
    balance - stake < min_reserve
This prevents the engine from placing wagers that would exhaust the
buffer needed for exchange fees, margin, or in-flight settlements.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import filelock

from src.banking.base import BaseBankingProvider

log = logging.getLogger(__name__)

_LOCK_TIMEOUT   = 5
_FUNDS_FILENAME = "funds.json"


class FundsManager:

    def __init__(
        self,
        config:   dict[str, Any],
        state_dir: str,
        provider: Optional[BaseBankingProvider] = None,
    ) -> None:
        self._min_reserve       = config.get("min_reserve", 50.0)
        self._top_up_threshold  = config.get("top_up_threshold", 100.0)
        self._top_up_amount     = config.get("top_up_amount", 500.0)
        self._currency          = config.get("currency", "GBP")
        self._destination       = config.get("destination", {})
        self._provider          = provider

        self._state_dir   = Path(state_dir)
        self._funds_file  = self._state_dir / _FUNDS_FILENAME
        self._lock_file   = self._state_dir / f"{_FUNDS_FILENAME}.lock"

        state = self._load_state()
        self._balance: float          = state.get("balance", config.get("initial_balance", 0.0))
        self._pending: dict[str, Any] = state.get("pending_transfers", {})

        log.info(
            "FundsManager initialised — balance=%.2f %s  min_reserve=%.2f  "
            "top_up_threshold=%.2f  pending_transfers=%d",
            self._balance, self._currency,
            self._min_reserve, self._top_up_threshold,
            len(self._pending),
        )

    # ------------------------------------------------------------------
    # Wager guard
    # ------------------------------------------------------------------

    def can_wager(self, stake: float) -> bool:
        """Return True if there are sufficient funds to cover stake + reserve."""
        available = self._balance - stake - self._min_reserve
        if available < 0:
            log.warning(
                "Insufficient funds: balance=%.2f stake=%.2f reserve=%.2f — wager blocked",
                self._balance, stake, self._min_reserve,
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------

    def debit(self, amount: float, label: str = "") -> None:
        """Deduct amount from available balance (stake committed to exchange)."""
        self._balance -= amount
        log.debug("FundsManager debit %.2f %s%s → balance=%.2f",
                  amount, self._currency, f" [{label}]" if label else "", self._balance)
        self._persist()

    def credit(self, amount: float, label: str = "") -> None:
        """Add amount to available balance (stake/profit returned from exchange)."""
        self._balance += amount
        log.debug("FundsManager credit %.2f %s%s → balance=%.2f",
                  amount, self._currency, f" [{label}]" if label else "", self._balance)
        self._persist()

    @property
    def balance(self) -> float:
        return self._balance

    # ------------------------------------------------------------------
    # Top-up
    # ------------------------------------------------------------------

    def check_and_top_up(self) -> None:
        """
        If balance is below top_up_threshold and a provider is configured,
        initiate a payment for top_up_amount. Skips if a top-up is already
        pending (prevents duplicate transfers).
        """
        if self._balance >= self._top_up_threshold:
            return

        if self._provider is None:
            log.warning(
                "FundsManager: balance=%.2f below threshold=%.2f but no banking provider configured",
                self._balance, self._top_up_threshold,
            )
            return

        if self._has_pending_top_up():
            log.debug(
                "FundsManager: balance=%.2f below threshold but top-up already pending — skipping",
                self._balance,
            )
            return

        log.info(
            "FundsManager: balance=%.2f below threshold=%.2f — initiating top-up of %.2f %s",
            self._balance, self._top_up_threshold, self._top_up_amount, self._currency,
        )
        try:
            reference  = f"ralf top-up {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
            payment_id = self._provider.initiate_payment(
                amount=self._top_up_amount,
                currency=self._currency,
                destination=self._destination,
                reference=reference,
            )
            self._pending[payment_id] = {
                "amount":    self._top_up_amount,
                "currency":  self._currency,
                "initiated": datetime.now(timezone.utc).isoformat(),
                "status":    "pending",
            }
            self._persist()
            log.info("FundsManager: top-up payment initiated payment_id=%s", payment_id)
        except Exception as exc:
            log.error("FundsManager: top-up initiation failed: %s", exc)

    def poll_pending_transfers(self) -> None:
        """
        Check status of all pending top-up transfers; credit balance when
        a transfer reaches 'completed'. Called by the engine each cycle.
        """
        if not self._pending or self._provider is None:
            return

        completed = []
        for payment_id, info in self._pending.items():
            try:
                status_info = self._provider.get_payment_status(payment_id)
                status      = status_info.get("status", "pending")
                log.debug(
                    "FundsManager: transfer %s → %s", payment_id, status
                )
                if status == "completed":
                    amount = info["amount"]
                    self.credit(amount, label=f"top-up transfer {payment_id}")
                    log.info(
                        "FundsManager: top-up completed — credited %.2f %s (payment_id=%s)",
                        amount, info["currency"], payment_id,
                    )
                    completed.append(payment_id)
                elif status == "failed":
                    log.error(
                        "FundsManager: top-up transfer %s failed — will retry next cycle",
                        payment_id,
                    )
                    completed.append(payment_id)   # remove so a fresh one can be initiated
            except Exception as exc:
                log.warning("FundsManager: status check failed for %s: %s", payment_id, exc)

        if completed:
            for pid in completed:
                del self._pending[pid]
            self._persist()

    def status(self) -> dict[str, Any]:
        """Return a snapshot dict for logging / stats."""
        return {
            "balance":           round(self._balance, 2),
            "currency":          self._currency,
            "min_reserve":       self._min_reserve,
            "top_up_threshold":  self._top_up_threshold,
            "pending_transfers": len(self._pending),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _has_pending_top_up(self) -> bool:
        return any(
            info.get("status") == "pending"
            for info in self._pending.values()
        )

    def _load_state(self) -> dict:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        if not self._funds_file.exists():
            return {}
        try:
            with open(self._funds_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load funds state from %s: %s — using defaults", self._funds_file, exc)
            return {}

    def _persist(self) -> None:
        try:
            with filelock.FileLock(str(self._lock_file), timeout=_LOCK_TIMEOUT):
                with open(self._funds_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "balance":           self._balance,
                            "currency":          self._currency,
                            "pending_transfers": self._pending,
                            "updated_at":        datetime.now(timezone.utc).isoformat(),
                        },
                        f,
                        indent=2,
                    )
        except filelock.Timeout:
            log.error("Lock timeout persisting funds state — state may be slightly stale")
        except OSError as exc:
            log.error("Could not persist funds state: %s", exc)
