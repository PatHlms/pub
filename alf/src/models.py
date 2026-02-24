from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class AuctionRecord:
    # Identity
    id: str                          # Site-native auction/lot ID
    source: str                      # Site name from sites.json "name" field
    lot_id: Optional[str]            # Human-readable lot number (e.g. "Lot 42")
    url: Optional[str]               # Direct link to the listing

    # Classification
    manufacturer: str                # e.g. "Porsche", normalised to title case
    model: str                       # e.g. "911 Carrera", normalised to title case

    # Pricing (all in units of `currency`)
    sold_price: Optional[float]      # Hammer price; None if no sale (passed-in lot)
    reserve_price: Optional[float]   # Reserve; None if not disclosed
    start_price: Optional[float]     # Opening bid / estimate low
    currency: str                    # ISO 4217, e.g. "GBP", "EUR", "USD"

    # Timing
    auction_date: Optional[str]      # ISO 8601 date string "YYYY-MM-DD" of sale
    harvested_at: str = field(       # UTC ISO 8601 timestamp set at parse time
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Passthrough for unmapped fields from the source API response
    raw: dict[str, Any] = field(default_factory=dict)

    # FX-converted prices (None when FX is disabled or the currency is unknown)
    base_currency: Optional[str]        = None
    sold_price_base: Optional[float]    = None
    reserve_price_base: Optional[float] = None
    start_price_base: Optional[float]   = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":                 self.id,
            "source":             self.source,
            "lot_id":             self.lot_id,
            "url":                self.url,
            "manufacturer":       self.manufacturer,
            "model":              self.model,
            "sold_price":         self.sold_price,
            "reserve_price":      self.reserve_price,
            "start_price":        self.start_price,
            "currency":           self.currency,
            "auction_date":       self.auction_date,
            "harvested_at":       self.harvested_at,
            "base_currency":      self.base_currency,
            "sold_price_base":    self.sold_price_base,
            "reserve_price_base": self.reserve_price_base,
            "start_price_base":   self.start_price_base,
            "raw":                self.raw,
        }

    @property
    def storage_path_parts(self) -> tuple[str, str, str]:
        """Returns (manufacturer_slug, model_slug, date_str) for path construction."""
        mfr  = self.manufacturer.lower().replace(" ", "_") or "unknown"
        mdl  = self.model.lower().replace(" ", "_") or "unknown"
        date = self.auction_date or self.harvested_at[:10]
        return mfr, mdl, date
