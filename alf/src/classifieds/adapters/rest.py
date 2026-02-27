import logging
from typing import Any, Optional

from src.adapters.rest import RestAdapter, _get_field, _to_date, _to_float
from src.classifieds.adapters.base import BaseClassifiedAdapter
from src.classifieds.models import ClassifiedListing

log = logging.getLogger(__name__)


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


class ClassifiedRestAdapter(BaseClassifiedAdapter, RestAdapter):
    """
    Generic REST adapter for classified listing sites.

    Inherits all HTTP fetch and pagination logic from RestAdapter:
      - _fetch_offset() with offset_step and max_pages support
      - _fetch_cursor() with max_pages support
      - _unwrap() with common wrapper key detection
      - dot-notation field path support via _get_field()

    Overrides parse() and _map_item() to produce ClassifiedListing
    instances with classifieds-specific fields (price, mileage, year,
    fuel_type, transmission, colour, location).
    """

    name = "rest"

    def __init__(self, site_config: dict[str, Any], fetcher: Any) -> None:
        # Explicitly initialise BaseClassifiedAdapter (sets self.config, self.fetcher)
        BaseClassifiedAdapter.__init__(self, site_config, fetcher)

    def fetch(self) -> list[ClassifiedListing]:
        """Delegate to RestAdapter.fetch() — all pagination logic is inherited."""
        return RestAdapter.fetch(self)

    def parse(self, raw_response: Any) -> list[ClassifiedListing]:
        mapping = self.config.get("field_mapping", {})
        source  = self.config["name"]
        records = []

        items = self._unwrap(raw_response)
        for item in items:
            try:
                records.append(self._map_item(item, mapping, source))
            except Exception as exc:
                log.warning("[%s] skipping malformed listing: %s — %r", source, exc, item)

        log.debug("[%s] parsed %d listings", source, len(records))
        return records

    def _map_item(
        self,
        item: dict[str, Any],
        mapping: dict[str, str],
        source: str,
    ) -> ClassifiedListing:
        """Map a single API response dict to a ClassifiedListing."""
        mapped_top_keys = {v.split(".")[0] for v in mapping.values() if v}

        def _get(canonical: str) -> Any:
            return _get_field(item, mapping, canonical)

        raw = {k: v for k, v in item.items() if k not in mapped_top_keys}

        return ClassifiedListing(
            id           = str(_get("id") or ""),
            source       = source,
            manufacturer = str(_get("manufacturer") or "").strip().title(),
            model        = str(_get("model") or "").strip().title(),
            year         = _to_int(_get("year")),
            price        = _to_float(_get("price")),
            currency     = str(_get("currency") or "GBP").upper(),
            mileage      = _to_int(_get("mileage")),
            mileage_unit = str(_get("mileage_unit") or "miles").lower(),
            condition    = _get("condition"),
            fuel_type    = _get("fuel_type"),
            transmission = _get("transmission"),
            colour       = _get("colour"),
            location     = _get("location"),
            url          = _get("url"),
            listed_date  = _to_date(_get("listed_date"), source),
            raw          = raw,
        )
