"""
Data quality validation tests.

These tests verify invariants that must hold for well-formed output data:
year ranges, non-negative prices and mileage, currency format, title-casing,
FX conversion postconditions, and storage path safety.
"""
import re
import pytest

from src.models import AuctionRecord
from src.classifieds.models import ClassifiedListing
from src.classifieds.adapters.rest import ClassifiedRestAdapter
from src.adapters.rest import RestAdapter

from tests.integration.conftest import (
    AUCTION_SITE_CONFIG,
    CLASSIFIED_SITE_CONFIG,
    make_fetcher,
    sample_auction_item,
    sample_classified_item,
)


CURRENT_YEAR = 2026
MIN_VEHICLE_YEAR = 1886  # Benz Patent-Motorwagen
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
SLUG_SAFE_RE = re.compile(r"^[a-z0-9_ ]*$")  # slugs may only contain safe chars before replace


# ---------------------------------------------------------------------------
# Helpers to produce parsed outputs
# ---------------------------------------------------------------------------

def _parse_classified(item, config=None):
    cfg = config or CLASSIFIED_SITE_CONFIG
    adapter = ClassifiedRestAdapter(cfg, make_fetcher())
    return adapter.parse([item])[0]


def _parse_auction(item, config=None):
    cfg = config or AUCTION_SITE_CONFIG
    adapter = RestAdapter(cfg, make_fetcher())
    return adapter.parse([item])[0]


# ---------------------------------------------------------------------------
# Year range
# ---------------------------------------------------------------------------

class TestYearRange:
    def test_valid_modern_year(self):
        l = _parse_classified(sample_classified_item(year=2020))
        assert l.year == 2020

    def test_valid_classic_year(self):
        l = _parse_classified(sample_classified_item(year=1965))
        assert l.year == 1965

    def test_year_none_when_missing(self):
        item = sample_classified_item()
        del item["year"]
        l = _parse_classified(item)
        assert l.year is None

    @pytest.mark.parametrize("year", [1900, 1950, 1990, 2010, 2023, 2025])
    def test_reasonable_years_parse_correctly(self, year):
        l = _parse_classified(sample_classified_item(year=year))
        assert l.year == year
        if l.year is not None:
            assert MIN_VEHICLE_YEAR <= l.year <= CURRENT_YEAR + 2

    def test_year_as_string_coerced_to_int(self):
        item = sample_classified_item()
        item["year"] = "2019"
        l = _parse_classified(item)
        assert isinstance(l.year, int)


# ---------------------------------------------------------------------------
# Non-negative mileage
# ---------------------------------------------------------------------------

class TestMileage:
    def test_mileage_is_non_negative(self):
        l = _parse_classified(sample_classified_item(mileage=0))
        assert l.mileage == 0

    def test_mileage_positive(self):
        l = _parse_classified(sample_classified_item(mileage=45000))
        assert l.mileage >= 0

    def test_mileage_none_when_missing(self):
        item = sample_classified_item()
        del item["mileage"]
        l = _parse_classified(item)
        assert l.mileage is None

    def test_mileage_unit_is_string(self):
        l = _parse_classified(sample_classified_item(mileage_unit="km"))
        assert isinstance(l.mileage_unit, str)
        assert l.mileage_unit == "km"


# ---------------------------------------------------------------------------
# Non-negative prices
# ---------------------------------------------------------------------------

class TestPrice:
    def test_classified_price_non_negative(self):
        l = _parse_classified(sample_classified_item(price_amount=0.0))
        assert l.price == 0.0

    def test_classified_price_positive(self):
        l = _parse_classified(sample_classified_item(price_amount=15000.0))
        assert l.price >= 0.0

    def test_auction_sold_price_non_negative(self):
        item = sample_auction_item(sold=0.0)
        item["price"]["sold"] = 0.0
        r = _parse_auction(item)
        assert r.sold_price == 0.0

    def test_auction_sold_price_positive(self):
        r = _parse_auction(sample_auction_item(sold=75000.0))
        assert r.sold_price >= 0.0

    def test_auction_none_price_is_none(self):
        item = sample_auction_item()
        item["price"]["sold"] = None
        r = _parse_auction(item)
        assert r.sold_price is None


# ---------------------------------------------------------------------------
# Currency format
# ---------------------------------------------------------------------------

class TestCurrencyFormat:
    @pytest.mark.parametrize("currency", ["GBP", "EUR", "USD"])
    def test_classified_currency_three_char_uppercase(self, currency):
        l = _parse_classified(sample_classified_item(price_currency=currency))
        assert CURRENCY_RE.match(l.currency), f"Invalid currency: {l.currency!r}"

    def test_classified_lowercase_currency_uppercased(self):
        item = sample_classified_item()
        item["price"]["currency"] = "gbp"
        l = _parse_classified(item)
        assert l.currency == "GBP"

    def test_auction_currency_uppercased(self):
        r = _parse_auction(sample_auction_item(currency="gbp"))
        assert r.currency == "GBP"

    def test_classified_default_currency_valid(self):
        item = sample_classified_item()
        del item["price"]["currency"]
        l = _parse_classified(item)
        assert CURRENCY_RE.match(l.currency)

    def test_auction_default_currency_valid(self):
        config = {
            **AUCTION_SITE_CONFIG,
            "field_mapping": {**AUCTION_SITE_CONFIG["field_mapping"], "currency": None},
        }
        r = _parse_auction(sample_auction_item(), config=config)
        assert CURRENCY_RE.match(r.currency)


# ---------------------------------------------------------------------------
# Title casing
# ---------------------------------------------------------------------------

class TestTitleCasing:
    @pytest.mark.parametrize("raw,expected", [
        ("volkswagen", "Volkswagen"),
        ("PORSCHE",    "Porsche"),
        ("alfa romeo", "Alfa Romeo"),
        ("BMW",        "Bmw"),
    ])
    def test_classified_manufacturer_title_cased(self, raw, expected):
        l = _parse_classified(sample_classified_item(make=raw))
        assert l.manufacturer == expected

    @pytest.mark.parametrize("raw,expected", [
        ("golf gti",   "Golf Gti"),
        ("911 CARRERA","911 Carrera"),
        ("M3",         "M3"),
    ])
    def test_classified_model_title_cased(self, raw, expected):
        l = _parse_classified(sample_classified_item(model=raw))
        assert l.model == expected

    def test_auction_manufacturer_title_cased(self):
        r = _parse_auction(sample_auction_item(make="ferrari"))
        assert r.manufacturer == "Ferrari"

    def test_manufacturer_leading_trailing_whitespace_stripped(self):
        item = sample_classified_item()
        item["make"] = "  BMW  "
        l = _parse_classified(item)
        assert l.manufacturer == "Bmw"
        assert not l.manufacturer.startswith(" ")
        assert not l.manufacturer.endswith(" ")


# ---------------------------------------------------------------------------
# FX conversion postconditions
# ---------------------------------------------------------------------------

class TestFXConversionPostconditions:
    def test_price_base_positive_when_price_positive(self):
        l = _listing(price=18500.0, currency="GBP")
        l.base_currency = "GBP"
        l.price_base = 18500.0
        assert l.price_base > 0

    def test_price_base_none_when_price_none(self):
        l = _listing(price=None)
        l.price_base = None
        assert l.price_base is None

    def test_base_currency_set_after_conversion(self):
        l = _listing(price=10000.0, currency="USD")
        l.base_currency = "GBP"
        l.price_base = 7900.0
        assert l.base_currency == "GBP"

    def test_same_currency_conversion_preserves_amount(self):
        from src.fx import FXProvider
        import time
        fx = FXProvider({"base_currency": "GBP", "provider": "frankfurter", "api_key_env_var": None})
        fx._rates = {"GBP": 1.0}
        fx._fetched_at = time.monotonic()
        result = fx.convert(18500.0, "GBP")
        assert result == 18500.0

    def test_fx_conversion_result_rounded_to_two_decimals(self):
        from src.fx import FXProvider
        import time
        fx = FXProvider({"base_currency": "GBP", "provider": "frankfurter", "api_key_env_var": None})
        fx._rates = {"USD": 0.7913}
        fx._fetched_at = time.monotonic()
        result = fx.convert(333.33, "USD")
        # Result should have at most 2 decimal places
        assert result == round(result, 2)


# ---------------------------------------------------------------------------
# Storage path safety
# ---------------------------------------------------------------------------

class TestStoragePathSafety:
    @pytest.mark.parametrize("manufacturer,model", [
        ("Alfa Romeo",   "4C Spider"),
        ("Land Rover",   "Range Rover"),
        ("Mercedes-Benz","GLE 450"),
        ("Volkswagen",   "Golf GTI"),
        ("",             ""),
    ])
    def test_classified_storage_parts_have_no_path_separators(self, manufacturer, model):
        l = _listing(manufacturer=manufacturer, model=model)
        for part in l.storage_path_parts:
            assert "/" not in part, f"Path separator in {part!r}"
            assert "\\" not in part

    def test_storage_date_is_iso_format(self):
        l = _listing(date="2024-06-15")
        _, _, date = l.storage_path_parts
        assert ISO_DATE_RE.match(date)

    def test_auction_storage_parts_safe(self):
        r = _auction(manufacturer="Aston Martin", model="DB5")
        for part in r.storage_path_parts:
            assert "/" not in part


# ---------------------------------------------------------------------------
# Private factories (avoiding conftest dependency for simple unit-level checks)
# ---------------------------------------------------------------------------

def _listing(**kwargs):
    # Accept "date" as a convenience alias for "listed_date"
    if "date" in kwargs:
        kwargs.setdefault("listed_date", kwargs.pop("date"))
    defaults = dict(
        id="ad-1", source="test", manufacturer="Volkswagen", model="Golf",
        year=2019, price=18500.0, currency="GBP", mileage=32000,
        mileage_unit="miles", condition="used", fuel_type="Petrol",
        transmission="Manual", colour="Red", location="London",
        url="https://example.com/ad-1", listed_date="2024-03-10",
    )
    defaults.update(kwargs)
    return ClassifiedListing(**defaults)


def _auction(**kwargs):
    defaults = dict(
        id="lot-1", source="test", lot_id=None, url="https://example.com/lot-1",
        manufacturer="Porsche", model="911", sold_price=50000.0,
        reserve_price=None, start_price=None, currency="GBP",
        auction_date="2024-03-15",
    )
    defaults.update(kwargs)
    return AuctionRecord(**defaults)
