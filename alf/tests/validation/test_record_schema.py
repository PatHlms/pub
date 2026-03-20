"""
Validation tests for AuctionRecord and ClassifiedListing data models.

Covers field types, default values, serialisation, and storage path properties.
"""
import re
from datetime import datetime, timezone

import pytest

from src.models import AuctionRecord
from src.classifieds.models import ClassifiedListing


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _auction(**kwargs):
    defaults = dict(
        id="lot-1",
        source="test_site",
        lot_id="42",
        url="https://example.com/lot-1",
        manufacturer="Porsche",
        model="911 Carrera",
        sold_price=50000.0,
        reserve_price=45000.0,
        start_price=30000.0,
        currency="GBP",
        auction_date="2024-03-15",
    )
    defaults.update(kwargs)
    return AuctionRecord(**defaults)


def _listing(**kwargs):
    defaults = dict(
        id="ad-1",
        source="test_site",
        manufacturer="Volkswagen",
        model="Golf GTI",
        year=2019,
        price=18500.0,
        currency="GBP",
        mileage=32000,
        mileage_unit="miles",
        condition="used",
        fuel_type="Petrol",
        transmission="Manual",
        colour="Red",
        location="London",
        url="https://example.com/ad-1",
        listed_date="2024-03-10",
    )
    defaults.update(kwargs)
    return ClassifiedListing(**defaults)


ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TS_RE   = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:")


# ---------------------------------------------------------------------------
# AuctionRecord field types and constraints
# ---------------------------------------------------------------------------

class TestAuctionRecordSchema:
    def test_id_is_string(self):
        assert isinstance(_auction().id, str)

    def test_source_is_string(self):
        assert isinstance(_auction().source, str)

    def test_currency_is_uppercase_string(self):
        r = _auction(currency="GBP")
        assert r.currency == r.currency.upper()
        assert len(r.currency) == 3

    def test_sold_price_is_float_or_none(self):
        assert isinstance(_auction(sold_price=100.0).sold_price, float)
        assert _auction(sold_price=None).sold_price is None

    def test_reserve_price_is_float_or_none(self):
        assert isinstance(_auction(reserve_price=90.0).reserve_price, float)
        assert _auction(reserve_price=None).reserve_price is None

    def test_start_price_is_float_or_none(self):
        assert isinstance(_auction(start_price=10.0).start_price, float)
        assert _auction(start_price=None).start_price is None

    def test_auction_date_is_iso_format_or_none(self):
        r = _auction(auction_date="2024-03-15")
        assert ISO_DATE_RE.match(r.auction_date)
        assert _auction(auction_date=None).auction_date is None

    def test_harvested_at_is_iso_timestamp(self):
        r = _auction()
        assert ISO_TS_RE.match(r.harvested_at)

    def test_harvested_at_contains_timezone_info(self):
        r = _auction()
        # Should be parseable as UTC timestamp
        dt = datetime.fromisoformat(r.harvested_at.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_fx_fields_default_to_none(self):
        r = _auction()
        assert r.base_currency is None
        assert r.sold_price_base is None
        assert r.reserve_price_base is None
        assert r.start_price_base is None

    def test_raw_defaults_to_empty_dict(self):
        r = _auction()
        assert isinstance(r.raw, dict)

    def test_lot_id_may_be_none(self):
        assert _auction(lot_id=None).lot_id is None

    def test_url_may_be_none(self):
        assert _auction(url=None).url is None


class TestAuctionRecordToDict:
    EXPECTED_KEYS = {
        "id", "source", "lot_id", "url", "manufacturer", "model",
        "sold_price", "reserve_price", "start_price", "currency",
        "auction_date", "harvested_at",
        "base_currency", "sold_price_base", "reserve_price_base", "start_price_base",
        "raw",
    }

    def test_to_dict_contains_all_expected_keys(self):
        d = _auction().to_dict()
        assert self.EXPECTED_KEYS == set(d.keys())

    def test_to_dict_no_extra_keys(self):
        d = _auction().to_dict()
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_to_dict_values_match_attributes(self):
        r = _auction(id="x99", sold_price=12345.0, currency="USD")
        d = r.to_dict()
        assert d["id"] == "x99"
        assert d["sold_price"] == 12345.0
        assert d["currency"] == "USD"

    def test_fx_fields_in_dict(self):
        r = _auction()
        r.base_currency = "GBP"
        r.sold_price_base = 50000.0
        d = r.to_dict()
        assert d["base_currency"] == "GBP"
        assert d["sold_price_base"] == 50000.0


class TestAuctionRecordStoragePath:
    def test_returns_three_tuple(self):
        parts = _auction().storage_path_parts
        assert len(parts) == 3

    def test_manufacturer_slugified(self):
        mfr, _, _ = _auction(manufacturer="Alfa Romeo").storage_path_parts
        assert mfr == "alfa_romeo"
        assert " " not in mfr

    def test_model_slugified(self):
        _, mdl, _ = _auction(model="911 Carrera RS").storage_path_parts
        assert mdl == "911_carrera_rs"

    def test_date_from_auction_date(self):
        _, _, date = _auction(auction_date="2024-06-01").storage_path_parts
        assert date == "2024-06-01"

    def test_date_falls_back_to_harvested_at(self):
        r = _auction(auction_date=None)
        _, _, date = r.storage_path_parts
        assert ISO_DATE_RE.match(date)

    def test_no_path_separators_in_parts(self):
        for part in _auction(manufacturer="Alfa Romeo", model="4C Spider").storage_path_parts:
            assert "/" not in part
            assert "\\" not in part

    def test_empty_manufacturer_becomes_unknown(self):
        mfr, _, _ = _auction(manufacturer="").storage_path_parts
        assert mfr == "unknown"

    def test_empty_model_becomes_unknown(self):
        _, mdl, _ = _auction(model="").storage_path_parts
        assert mdl == "unknown"


# ---------------------------------------------------------------------------
# ClassifiedListing field types and constraints
# ---------------------------------------------------------------------------

class TestClassifiedListingSchema:
    def test_id_is_string(self):
        assert isinstance(_listing().id, str)

    def test_source_is_string(self):
        assert isinstance(_listing().source, str)

    def test_year_is_int_or_none(self):
        assert isinstance(_listing(year=2019).year, int)
        assert _listing(year=None).year is None

    def test_price_is_float_or_none(self):
        assert isinstance(_listing(price=10000.0).price, float)
        assert _listing(price=None).price is None

    def test_currency_is_uppercase_string(self):
        l = _listing(currency="GBP")
        assert l.currency == l.currency.upper()
        assert len(l.currency) == 3

    def test_mileage_is_int_or_none(self):
        assert isinstance(_listing(mileage=50000).mileage, int)
        assert _listing(mileage=None).mileage is None

    def test_mileage_unit_is_string(self):
        assert isinstance(_listing().mileage_unit, str)

    def test_listed_date_iso_format_or_none(self):
        l = _listing(listed_date="2024-03-10")
        assert ISO_DATE_RE.match(l.listed_date)
        assert _listing(listed_date=None).listed_date is None

    def test_harvested_at_is_iso_timestamp(self):
        assert ISO_TS_RE.match(_listing().harvested_at)

    def test_fx_fields_default_to_none(self):
        l = _listing()
        assert l.base_currency is None
        assert l.price_base is None

    def test_raw_defaults_to_empty_dict(self):
        assert isinstance(_listing().raw, dict)

    def test_optional_fields_may_be_none(self):
        l = _listing(condition=None, fuel_type=None, transmission=None,
                     colour=None, location=None, url=None)
        assert l.condition is None
        assert l.fuel_type is None
        assert l.transmission is None


class TestClassifiedListingToDict:
    EXPECTED_KEYS = {
        "id", "source", "manufacturer", "model", "year",
        "price", "currency", "mileage", "mileage_unit",
        "condition", "fuel_type", "transmission", "colour",
        "location", "url", "listed_date", "harvested_at",
        "base_currency", "price_base", "raw",
    }

    def test_to_dict_contains_all_expected_keys(self):
        assert self.EXPECTED_KEYS == set(_listing().to_dict().keys())

    def test_to_dict_no_extra_keys(self):
        assert set(_listing().to_dict().keys()) == self.EXPECTED_KEYS

    def test_to_dict_values_match(self):
        l = _listing(id="x", year=2021, price=25000.0)
        d = l.to_dict()
        assert d["id"] == "x"
        assert d["year"] == 2021
        assert d["price"] == 25000.0

    def test_fx_fields_in_dict(self):
        l = _listing()
        l.base_currency = "GBP"
        l.price_base = 18000.0
        d = l.to_dict()
        assert d["base_currency"] == "GBP"
        assert d["price_base"] == 18000.0


class TestClassifiedListingStoragePath:
    def test_returns_three_tuple(self):
        assert len(_listing().storage_path_parts) == 3

    def test_manufacturer_slugified(self):
        mfr, _, _ = _listing(manufacturer="Alfa Romeo").storage_path_parts
        assert mfr == "alfa_romeo"

    def test_model_slugified(self):
        _, mdl, _ = _listing(model="Golf GTI").storage_path_parts
        assert mdl == "golf_gti"

    def test_date_from_listed_date(self):
        _, _, date = _listing(listed_date="2024-06-15").storage_path_parts
        assert date == "2024-06-15"

    def test_date_falls_back_to_harvested_at(self):
        l = _listing(listed_date=None)
        _, _, date = l.storage_path_parts
        assert ISO_DATE_RE.match(date)

    def test_no_path_separators_in_parts(self):
        for part in _listing(manufacturer="Land Rover", model="Range Rover Sport").storage_path_parts:
            assert "/" not in part
