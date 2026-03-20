"""
Regression tests for known edge cases and previously-fixed bugs.

Each test here documents a specific input condition that caused incorrect
behaviour at some point, or represents a boundary condition that must
remain stable.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.classifieds.adapters.rest import ClassifiedRestAdapter
from src.adapters.rest import RestAdapter, _to_date, _to_float
from src.classifieds.adapters.rest import _to_int
from src.classifieds.models import ClassifiedListing
from src.models import AuctionRecord

_REPO_ROOT = Path(__file__).parents[2]


def _load_classified_config(name):
    sites = json.loads((_REPO_ROOT / "config" / "classifieds" / "sites.json").read_text())["sites"]
    return next(s for s in sites if s["name"] == name)


def _classified_adapter(name):
    return ClassifiedRestAdapter(_load_classified_config(name), MagicMock())


# ---------------------------------------------------------------------------
# Date parsing edge cases
# ---------------------------------------------------------------------------

class TestDateParsing:
    """_to_date must handle every format seen in real API responses."""

    @pytest.mark.parametrize("raw,expected", [
        ("2024-03-15",          "2024-03-15"),   # ISO — pass-through
        ("2024-03-15T12:30:00", "2024-03-15"),   # ISO datetime — truncate
        ("2024-03-15T00:00:00Z","2024-03-15"),   # UTC datetime — truncate
        ("15/03/2024",          "2024-03-15"),   # DD/MM/YYYY
        ("03/15/2024",          "2024-03-15"),   # MM/DD/YYYY
        ("20240315",            "2024-03-15"),   # YYYYMMDD
        ("15-03-2024",          "2024-03-15"),   # DD-MM-YYYY
    ])
    def test_date_format(self, raw, expected):
        assert _to_date(raw) == expected

    def test_none_returns_none(self):
        assert _to_date(None) is None

    def test_unparseable_stored_as_is(self):
        result = _to_date("not-a-date")
        assert result == "not-a-date"

    def test_integer_date_not_crash(self):
        # Some APIs return epoch integers — should not raise
        result = _to_date(1710460800)
        assert result is not None

    def test_exchange_and_mart_slash_date(self):
        """Regression: exchange_and_mart returns DD/MM/YYYY."""
        adapter  = _classified_adapter("exchange_and_mart")
        item = {
            "adId": "x", "make": "Ford", "model": "Focus",
            "registrationYear": 2019, "price": 10000,
            "odometer": 40000, "odometerUnit": "miles",
            "fuelType": "Petrol", "gearbox": "Manual",
            "colour": "Blue", "advertiserLocation": "Leeds",
            "adUrl": "https://em.co.uk/x",
            "datePosted": "28/02/2024",
        }
        [listing] = adapter.parse([item])
        assert listing.listed_date == "2024-02-28"


# ---------------------------------------------------------------------------
# Float / int coercion edge cases
# ---------------------------------------------------------------------------

class TestTypeCoercion:
    @pytest.mark.parametrize("raw,expected", [
        (100,       100.0),
        ("100",     100.0),
        ("100.50",  100.5),
        (None,      None),
        ("",        None),
        ("n/a",     None),
        ("£50,000", None),   # locale-formatted price — graceful failure
    ])
    def test_to_float(self, raw, expected):
        assert _to_float(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        (2019,      2019),
        ("2019",    2019),
        ("2019.0",  2019),
        (2019.9,    2019),    # floor, not round
        (None,      None),
        ("",        None),
    ])
    def test_to_int(self, raw, expected):
        assert _to_int(raw) == expected

    def test_ebay_price_as_string(self):
        """eBay returns prices as strings inside JSON — must coerce to float."""
        assert _to_float("68500") == 68500.0

    def test_zero_price_is_valid(self):
        assert _to_float(0) == 0.0
        assert _to_float("0") == 0.0

    def test_very_large_price(self):
        assert _to_float(9_999_999) == 9_999_999.0

    def test_year_1886(self):
        """First motor car year must parse correctly."""
        assert _to_int(1886) == 1886

    def test_year_as_float_string_from_api(self):
        """Some APIs return year as '2019.0'."""
        assert _to_int("2019.0") == 2019


# ---------------------------------------------------------------------------
# Currency defaulting and normalisation
# ---------------------------------------------------------------------------

class TestCurrencyHandling:
    def test_null_currency_mapping_defaults_to_gbp(self):
        """Sites with currency: null in field_mapping must default to GBP."""
        adapter = _classified_adapter("autotrader_uk")
        item = {
            "id": "x", "make": "VW", "model": "Golf",
            "year": 2020, "advertisedPrice": {"priceGBP": 20000},
            "mileage": 10000,
        }
        [listing] = adapter.parse([item])
        assert listing.currency == "GBP"

    def test_lowercase_currency_uppercased(self):
        adapter = _classified_adapter("pistonheads")
        item = {
            "listingId": "x", "make": "BMW", "model": "M3",
            "year": 2022, "advertisedPrice": {"amount": 70000, "currency": "gbp"},
            "mileage": 5000,
        }
        [listing] = adapter.parse([item])
        assert listing.currency == "GBP"

    def test_eur_currency_preserved(self):
        adapter = _classified_adapter("pistonheads")
        item = {
            "listingId": "x", "make": "Porsche", "model": "911",
            "year": 2022, "advertisedPrice": {"amount": 150000, "currency": "EUR"},
            "mileage": 2000,
        }
        [listing] = adapter.parse([item])
        assert listing.currency == "EUR"

    def test_mileage_unit_defaults_to_miles(self):
        """Sites without mileage_unit mapping default to 'miles'."""
        adapter = _classified_adapter("autotrader_uk")
        item = {
            "id": "x", "make": "VW", "model": "Golf",
            "year": 2020, "advertisedPrice": {"priceGBP": 20000},
            "mileage": 30000,
        }
        [listing] = adapter.parse([item])
        assert listing.mileage_unit == "miles"


# ---------------------------------------------------------------------------
# Unicode and special characters
# ---------------------------------------------------------------------------

class TestUnicodeHandling:
    def test_manufacturer_with_umlaut(self):
        """Über-exotic manufacturer names must survive serialisation."""
        adapter = _classified_adapter("motors_co_uk")
        item = {
            "reference": "x", "make": "Mäni Räss", "model": "Xtreme",
            "year": 2022, "price": 50000, "mileage": 1000,
            "mileageUnit": "km", "vehicleCondition": "New",
            "fuelType": "Electric", "transmission": "Automatic",
            "colour": "White", "town": "Zürich",
            "url": "https://motors.co.uk/x", "listedDate": "2024-03-01",
        }
        [listing] = adapter.parse([item])
        assert "Räss" in listing.manufacturer
        assert listing.location == "Zürich"

    def test_model_with_ampersand(self):
        adapter = _classified_adapter("motors_co_uk")
        item = {
            "reference": "x", "make": "Land Rover", "model": "Discovery & Defender",
            "year": 2022, "price": 60000, "mileage": 5000,
            "mileageUnit": "miles", "vehicleCondition": "Used",
            "fuelType": "Diesel", "transmission": "Automatic",
            "colour": "Green", "town": "Oxford",
            "url": "https://motors.co.uk/x", "listedDate": "2024-03-01",
        }
        [listing] = adapter.parse([item])
        assert "&" in listing.model


# ---------------------------------------------------------------------------
# None / missing field handling
# ---------------------------------------------------------------------------

class TestMissingFields:
    def test_all_optional_classified_fields_missing(self):
        """Minimal valid item — only id, make, model must produce a listing."""
        adapter = _classified_adapter("motors_co_uk")
        item = {
            "reference": "min-001",
            "make": "Fiat",
            "model": "500",
        }
        [listing] = adapter.parse([item])
        assert listing.id == "min-001"
        assert listing.manufacturer == "Fiat"
        assert listing.model == "500"
        assert listing.year is None
        assert listing.price is None
        assert listing.mileage is None
        assert listing.listed_date is None

    def test_empty_id_string(self):
        adapter = _classified_adapter("motors_co_uk")
        item = {"reference": "", "make": "Fiat", "model": "500"}
        [listing] = adapter.parse([item])
        assert listing.id == ""

    def test_null_price_is_none(self):
        adapter = _classified_adapter("motors_co_uk")
        item = {"reference": "x", "make": "VW", "model": "Golf", "price": None}
        [listing] = adapter.parse([item])
        assert listing.price is None

    def test_auction_all_optional_prices_missing(self):
        from tests.integration.conftest import AUCTION_SITE_CONFIG
        adapter = RestAdapter(AUCTION_SITE_CONFIG, MagicMock())
        item = {"id": "x", "make": "Ford", "model": "Mustang"}
        [record] = adapter.parse([item])
        assert record.sold_price is None
        assert record.reserve_price is None
        assert record.start_price is None


# ---------------------------------------------------------------------------
# Response shape edge cases
# ---------------------------------------------------------------------------

class TestResponseShapes:
    def test_bare_list_response(self):
        """API returning a bare list (no wrapper key) must parse correctly."""
        adapter = _classified_adapter("motors_co_uk")
        items = [
            {"reference": "a", "make": "VW", "model": "Golf"},
            {"reference": "b", "make": "BMW", "model": "M3"},
        ]
        listings = adapter.parse(items)
        assert len(listings) == 2

    def test_all_known_wrapper_keys(self):
        """Every wrapper key in _WRAPPER_KEYS must unwrap correctly."""
        from src.adapters.rest import _WRAPPER_KEYS
        from tests.integration.conftest import AUCTION_SITE_CONFIG
        adapter = RestAdapter(AUCTION_SITE_CONFIG, MagicMock())
        item = {"id": "x", "make": "VW", "model": "Golf"}
        for key in _WRAPPER_KEYS:
            records = adapter.parse({key: [item]})
            assert len(records) == 1, f"Wrapper key '{key}' not unwrapped"

    def test_empty_wrapper_list(self):
        adapter = _classified_adapter("autotrader_uk")
        assert adapter.parse({"vehicles": []}) == []

    def test_completely_empty_response_dict(self):
        adapter = _classified_adapter("autotrader_uk")
        assert adapter.parse({}) == []

    def test_none_response_returns_empty(self):
        adapter = _classified_adapter("autotrader_uk")
        assert adapter.parse(None) == []


# ---------------------------------------------------------------------------
# Storage path edge cases
# ---------------------------------------------------------------------------

class TestStoragePathRegression:
    @pytest.mark.parametrize("manufacturer,model,expected_mfr,expected_mdl", [
        ("Alfa Romeo",    "4C Spider",    "alfa_romeo",    "4c_spider"),
        ("Mercedes-Benz", "GLE 450",      "mercedes-benz", "gle_450"),
        ("",              "",             "unknown",       "unknown"),
        ("Land Rover",    "Range Rover",  "land_rover",    "range_rover"),
    ])
    def test_classified_storage_slug(self, manufacturer, model, expected_mfr, expected_mdl):
        listing = ClassifiedListing(
            id="x", source="s", manufacturer=manufacturer, model=model,
            year=None, price=None, currency="GBP", mileage=None,
            mileage_unit="miles", condition=None, fuel_type=None,
            transmission=None, colour=None, location=None, url=None,
            listed_date="2024-01-01",
        )
        mfr, mdl, _ = listing.storage_path_parts
        assert mfr == expected_mfr
        assert mdl == expected_mdl

    @pytest.mark.parametrize("manufacturer,model,expected_mfr,expected_mdl", [
        ("Aston Martin", "DB5",    "aston_martin", "db5"),
        ("",             "",       "unknown",      "unknown"),
    ])
    def test_auction_storage_slug(self, manufacturer, model, expected_mfr, expected_mdl):
        record = AuctionRecord(
            id="x", source="s", lot_id=None, url=None,
            manufacturer=manufacturer, model=model,
            sold_price=None, reserve_price=None, start_price=None,
            currency="GBP", auction_date="2024-01-01",
        )
        mfr, mdl, _ = record.storage_path_parts
        assert mfr == expected_mfr
        assert mdl == expected_mdl
