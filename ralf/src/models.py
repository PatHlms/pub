from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Signal actions
# ---------------------------------------------------------------------------

VALID_ACTIONS: frozenset[str] = frozenset({"BACK", "LAY", "SKIP"})


# ---------------------------------------------------------------------------
# Wager status constants
#
# Terminal statuses: settled, lapsed, cancelled, cashed_out, failed
# Open statuses:     open, matched
#
# profit_loss semantics: NET profit/loss, NOT including the returned stake.
#   e.g. stake=10, win=15 → profit_loss=+15, total_return=25
#   e.g. stake=10, full loss → profit_loss=-10, total_return=0
# When crediting FundsManager on settlement use: stake + profit_loss
# ---------------------------------------------------------------------------

class WagerStatus:
    OPEN       = "open"
    MATCHED    = "matched"
    CASHED_OUT = "cashed_out"
    SETTLED    = "settled"
    LAPSED     = "lapsed"
    CANCELLED  = "cancelled"
    FAILED     = "failed"

    OPEN_SET:     frozenset[str] = frozenset({OPEN, MATCHED})
    TERMINAL_SET: frozenset[str] = frozenset({CASHED_OUT, SETTLED, LAPSED, CANCELLED, FAILED})


@dataclass
class Signal:
    """
    Output of a Strategy evaluation for a single auction record.

    action      — "BACK" (bet for), "LAY" (bet against), or "SKIP" (no action).
    market_id   — Exchange market identifier (strategy-defined; empty string for SKIP).
    selection_id— Exchange selection identifier within the market.
    price       — Requested odds / price on the exchange.
    stake       — Stake amount in the configured base currency. Must be > 0.
    record_id   — The alf AuctionRecord `id` that triggered this signal.
    rationale   — Human-readable explanation (for logging and audit).
    """
    action:       str
    market_id:    str
    selection_id: str
    price:        float
    stake:        float
    record_id:    str
    rationale:    str = ""

    def is_actionable(self) -> bool:
        return self.action in ("BACK", "LAY")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action":       self.action,
            "market_id":    self.market_id,
            "selection_id": self.selection_id,
            "price":        self.price,
            "stake":        self.stake,
            "record_id":    self.record_id,
            "rationale":    self.rationale,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Signal:
        return cls(
            action=d["action"],
            market_id=d["market_id"],
            selection_id=d["selection_id"],
            price=d["price"],
            stake=d["stake"],
            record_id=d["record_id"],
            rationale=d.get("rationale", ""),
        )


@dataclass
class Wager:
    """
    Represents a single wager placed (or attempted) on the exchange.

    wager_id     — Exchange-assigned bet ID (stub uses a UUID).
    signal       — The Signal that triggered this wager.
    status       — Lifecycle state (see WagerStatus constants).
    placed_at    — UTC ISO 8601 timestamp of placement.
    cashed_out_at— UTC ISO 8601 timestamp of cashout (None if not cashed out).
    profit_loss  — Realised NET P&L in base currency (None while open).
                   Does NOT include stake return; see WagerStatus docstring.
    """
    wager_id:      str
    signal:        Signal
    status:        str
    placed_at:     str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    cashed_out_at: Optional[str]   = None
    profit_loss:   Optional[float] = None

    def is_open(self) -> bool:
        return self.status in WagerStatus.OPEN_SET

    def to_dict(self) -> dict[str, Any]:
        return {
            "wager_id":      self.wager_id,
            "signal":        self.signal.to_dict(),
            "status":        self.status,
            "placed_at":     self.placed_at,
            "cashed_out_at": self.cashed_out_at,
            "profit_loss":   self.profit_loss,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Wager:
        return cls(
            wager_id=d["wager_id"],
            signal=Signal.from_dict(d["signal"]),
            status=d["status"],
            placed_at=d["placed_at"],
            cashed_out_at=d.get("cashed_out_at"),
            profit_loss=d.get("profit_loss"),
        )
