"""
Unit tests for adapter parse helpers and pagination logic.

Run with:  pytest tests/ -v
"""
import pytest

from src.adapters.rest import RestAdapter, _get_field, _to_date, _to_float
from src.classifieds.adapters.rest import _to_int


# ---------------------------------------------------------------------------
# _get_field
# ---------------------------------------------------------------------------

class TestGetField:
    def test_simple_key(self):
        item = {"make": "Porsche"}
        mapping = {"manufacturer": "make"}
        assert _get_field(item, mapping, "manufacturer") == "Porsche"

    def test_dot_notation_two_levels(self):
        item = {"price": {"value": 15000.0, "currency": "GBP"}}
        mapping = {"sold_price": "price.value"}
        assert _get_field(item, mapping, "sold_price") == 15000.0

    def test_dot_notation_three_levels(self):
        item = {"a": {"b": {"c": 42}}}
        mapping = {"val": "a.b.c"}
        assert _get_field(item, mapping, "val") == 42

    def test_missing_canonical_returns_none(self):
        assert _get_field({}, {}, "sold_price") is None

    def test_missing_path_segment_returns_none(self):
        item = {"price": None}
        mapping = {"sold_price": "price.value"}
        assert _get_field(item, mapping, "sold_price") is None

    def test_non_dict_mid_path_returns_none(self):
        item = {"price": "flat_string"}
        mapping = {"sold_price": "price.value"}
        assert _get_field(item, mapping, "sold_price") is None

    def test_key_absent_from_item(self):
        item = {"other": 1}
        mapping = {"sold_price": "hammer_price"}
        assert _get_field(item, mapping, "sold_price") is None


# ---------------------------------------------------------------------------
# _to_float
# ---------------------------------------------------------------------------

class TestToFloat:
    def test_float_passthrough(self):
        assert _to_float(1.5) == 1.5

    def test_int_converted(self):
        assert _to_float(10) == 10.0

    def test_numeric_string(self):
        assert _to_float("3.14") == 3.14

    def test_none_returns_none(self):
        assert _to_float(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _to_float("n/a") is None

    def test_empty_string_returns_none(self):
        assert _to_float("") is None


# ---------------------------------------------------------------------------
# _to_int
# ---------------------------------------------------------------------------

class TestToInt:
    def test_int_passthrough(self):
        assert _to_int(2019) == 2019

    def test_float_truncated(self):
        assert _to_int(2019.9) == 2019

    def test_string_int(self):
        assert _to_int("85000") == 85000

    def test_none_returns_none(self):
        assert _to_int(None) is None

    def test_non_numeric_returns_none(self):
        assert _to_int("unknown") is None


# ---------------------------------------------------------------------------
# _to_date
# ---------------------------------------------------------------------------

class TestToDate:
    def test_iso_passthrough(self):
        assert _to_date("2024-03-15") == "2024-03-15"

    def test_iso_with_time_truncated(self):
        assert _to_date("2024-03-15T10:30:00Z") == "2024-03-15"

    def test_dmy_slash(self):
        assert _to_date("15/03/2024") == "2024-03-15"

    def test_mdy_slash(self):
        assert _to_date("03/15/2024") == "2024-03-15"

    def test_compact(self):
        assert _to_date("20240315") == "2024-03-15"

    def test_dmy_hyphen(self):
        assert _to_date("15-03-2024") == "2024-03-15"

    def test_none_returns_none(self):
        assert _to_date(None) is None

    def test_unparseable_returns_as_is(self):
        assert _to_date("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# RestAdapter._unwrap
# ---------------------------------------------------------------------------

class TestUnwrap:
    """Test _unwrap via a minimal RestAdapter subclass."""

    def _make_adapter(self):
        # Minimal config needed to instantiate without a Fetcher
        class _MinimalFetcher:
            pass

        cfg = {"name": "test", "base_url": "http://x", "endpoints": {"auctions": "/"}}
        adapter = RestAdapter.__new__(RestAdapter)
        adapter.config  = cfg
        adapter.fetcher = _MinimalFetcher()
        return adapter

    def test_bare_list(self):
        adapter = self._make_adapter()
        items = [{"id": "1"}, {"id": "2"}]
        assert adapter._unwrap(items) == items

    def test_results_wrapper(self):
        adapter = self._make_adapter()
        items = [{"id": "1"}]
        assert adapter._unwrap({"results": items}) == items

    def test_itemSummaries_wrapper(self):
        adapter = self._make_adapter()
        items = [{"itemId": "123"}]
        assert adapter._unwrap({"itemSummaries": items}) == items

    def test_vehicles_wrapper(self):
        adapter = self._make_adapter()
        items = [{"vehicleId": "v1"}]
        assert adapter._unwrap({"vehicles": items}) == items

    def test_unknown_wrapper_returns_empty(self):
        adapter = self._make_adapter()
        assert adapter._unwrap({"unknown_key": [1, 2, 3]}) == []

    def test_non_list_value_skipped(self):
        adapter = self._make_adapter()
        # results value is not a list → should skip and return empty
        assert adapter._unwrap({"results": {"nested": "dict"}}) == []


# ---------------------------------------------------------------------------
# RestAdapter._map_item  (integration: field_mapping → AuctionRecord)
# ---------------------------------------------------------------------------

class TestMapItem:
    def _make_adapter(self):
        cfg = {
            "name": "test_site",
            "base_url": "http://x",
            "endpoints": {"auctions": "/"},
            "field_mapping": {
                "id":            "auctionId",
                "manufacturer":  "make",
                "model":         "model",
                "sold_price":    "hammerPrice.amount",
                "currency":      "hammerPrice.currency",
                "auction_date":  "endDate",
                "lot_id":        "lotNum",
            },
        }
        adapter = RestAdapter.__new__(RestAdapter)
        adapter.config = cfg
        return adapter

    def test_basic_mapping(self):
        adapter = self._make_adapter()
        item = {
            "auctionId": "A123",
            "make": "porsche",
            "model": "911",
            "hammerPrice": {"amount": "45000", "currency": "GBP"},
            "endDate": "2024-06-01",
            "lotNum": "42",
            "extra_field": "kept",
        }
        record = adapter._map_item(item, adapter.config["field_mapping"], "test_site")
        assert record.id == "A123"
        assert record.manufacturer == "Porsche"
        assert record.model == "911"
        assert record.sold_price == 45000.0
        assert record.currency == "GBP"
        assert record.auction_date == "2024-06-01"
        assert record.lot_id == "42"
        assert "extra_field" in record.raw

    def test_mapped_top_keys_excluded_from_raw(self):
        adapter = self._make_adapter()
        item = {
            "auctionId": "B1",
            "make": "BMW",
            "model": "M3",
            "hammerPrice": {"amount": 30000, "currency": "EUR"},
            "endDate": "2024-07-15",
            "lotNum": None,
            "unmapped": "preserved",
        }
        record = adapter._map_item(item, adapter.config["field_mapping"], "test_site")
        # hammerPrice is the top-level key for a dot-path — must not appear in raw
        assert "hammerPrice" not in record.raw
        assert "auctionId" not in record.raw
        assert record.raw.get("unmapped") == "preserved"

    def test_missing_lot_id_is_none(self):
        adapter = self._make_adapter()
        item = {"auctionId": "C1", "make": "Ford", "model": "Mustang",
                "hammerPrice": {"amount": 20000, "currency": "USD"},
                "endDate": "2024-08-10", "lotNum": None}
        record = adapter._map_item(item, adapter.config["field_mapping"], "test_site")
        assert record.lot_id is None

    def test_manufacturer_title_cased(self):
        adapter = self._make_adapter()
        item = {"auctionId": "D1", "make": "LAND ROVER", "model": "defender",
                "hammerPrice": {"amount": 60000, "currency": "GBP"},
                "endDate": "2024-09-01", "lotNum": "99"}
        record = adapter._map_item(item, adapter.config["field_mapping"], "test_site")
        assert record.manufacturer == "Land Rover"
        assert record.model == "Defender"
