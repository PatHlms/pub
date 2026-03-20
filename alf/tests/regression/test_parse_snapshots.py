"""
Snapshot regression tests.

Each test parses a stored fixture (realistic mock API response) using the
real site config from config/classifieds/sites.json or config/auctions/sites.json,
then compares the result against a golden snapshot file.

Run with --update-snapshots to regenerate all snapshot files.

Usage:
    pytest tests/regression/test_parse_snapshots.py                  # compare
    pytest tests/regression/test_parse_snapshots.py --update-snapshots  # regenerate
"""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.classifieds.adapters.rest import ClassifiedRestAdapter
from src.adapters.rest import RestAdapter

from tests.regression.conftest import (
    assert_matches_snapshot,
    load_fixture,
    SNAPSHOTS_DIR,
)

# ---------------------------------------------------------------------------
# Load real site configs from disk
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2]


def _load_classified_config(name: str) -> dict:
    sites = json.loads((_REPO_ROOT / "config" / "classifieds" / "sites.json").read_text())["sites"]
    return next(s for s in sites if s["name"] == name)


def _load_auction_config(name: str) -> dict:
    sites = json.loads((_REPO_ROOT / "config" / "auctions" / "sites.json").read_text())["sites"]
    return next(s for s in sites if s["name"] == name)


def _classified_adapter(site_name: str) -> ClassifiedRestAdapter:
    config = _load_classified_config(site_name)
    fetcher = MagicMock()
    return ClassifiedRestAdapter(config, fetcher)


def _auction_adapter(site_name: str) -> RestAdapter:
    config = _load_auction_config(site_name)
    fetcher = MagicMock()
    return RestAdapter(config, fetcher)


# ---------------------------------------------------------------------------
# Classifieds snapshot tests
# ---------------------------------------------------------------------------

class TestClassifiedSnapshots:
    def test_autotrader_uk(self, update_snapshots):
        adapter  = _classified_adapter("autotrader_uk")
        listings = adapter.parse(load_fixture("autotrader_uk"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "autotrader_uk", update_snapshots)

    def test_exchange_and_mart(self, update_snapshots):
        adapter  = _classified_adapter("exchange_and_mart")
        listings = adapter.parse(load_fixture("exchange_and_mart"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "exchange_and_mart", update_snapshots)

    def test_motors_co_uk(self, update_snapshots):
        adapter  = _classified_adapter("motors_co_uk")
        listings = adapter.parse(load_fixture("motors_co_uk"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "motors_co_uk", update_snapshots)

    def test_pistonheads(self, update_snapshots):
        adapter  = _classified_adapter("pistonheads")
        listings = adapter.parse(load_fixture("pistonheads"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "pistonheads", update_snapshots)

    def test_bring_a_trailer(self, update_snapshots):
        adapter  = _classified_adapter("bring_a_trailer")
        listings = adapter.parse(load_fixture("bring_a_trailer"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "bring_a_trailer", update_snapshots)

    def test_cars_and_bids(self, update_snapshots):
        adapter  = _classified_adapter("cars_and_bids")
        listings = adapter.parse(load_fixture("cars_and_bids"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "cars_and_bids", update_snapshots)

    def test_car_and_classic(self, update_snapshots):
        adapter  = _classified_adapter("car_and_classic")
        listings = adapter.parse(load_fixture("car_and_classic"))
        assert len(listings) == 2
        assert_matches_snapshot(listings, "car_and_classic", update_snapshots)


# ---------------------------------------------------------------------------
# Auction snapshot tests
# ---------------------------------------------------------------------------

class TestAuctionSnapshots:
    def test_ebay_motors_uk(self, update_snapshots):
        adapter = _auction_adapter("ebay_motors_uk")
        records = adapter.parse(load_fixture("ebay_motors_uk"))
        assert len(records) == 2
        assert_matches_snapshot(records, "ebay_motors_uk", update_snapshots)


# ---------------------------------------------------------------------------
# Specific field-level snapshot assertions
# (extra guard: even if snapshot format changes these named assertions hold)
# ---------------------------------------------------------------------------

class TestSnapshotFieldValues:
    """
    Verify specific field values in the parsed output that would be
    invisible in a pure snapshot diff (e.g., title-casing, currency
    defaulting, date normalisation).
    """

    def test_autotrader_manufacturer_title_cased(self):
        adapter  = _classified_adapter("autotrader_uk")
        listings = adapter.parse(load_fixture("autotrader_uk"))
        assert listings[0].manufacturer == "Volkswagen"   # was "volkswagen"
        assert listings[1].manufacturer == "Bmw"          # was "BMW"

    def test_autotrader_currency_defaults_to_gbp(self):
        adapter  = _classified_adapter("autotrader_uk")
        [l1, l2] = adapter.parse(load_fixture("autotrader_uk"))
        assert l1.currency == "GBP"
        assert l2.currency == "GBP"

    def test_autotrader_nested_price_extracted(self):
        adapter  = _classified_adapter("autotrader_uk")
        [l1, _]  = adapter.parse(load_fixture("autotrader_uk"))
        assert l1.price == 22995.0

    def test_exchange_and_mart_slash_date_normalised(self):
        """datePosted '28/02/2024' must be normalised to ISO format."""
        adapter  = _classified_adapter("exchange_and_mart")
        listings = adapter.parse(load_fixture("exchange_and_mart"))
        assert listings[1].listed_date == "2024-02-28"

    def test_motors_co_uk_model_title_cased(self):
        adapter  = _classified_adapter("motors_co_uk")
        listings = adapter.parse(load_fixture("motors_co_uk"))
        assert listings[1].model == "Civic Type R"        # was "civic type r"

    def test_pistonheads_nested_currency_extracted(self):
        adapter  = _classified_adapter("pistonheads")
        [l1, l2] = adapter.parse(load_fixture("pistonheads"))
        assert l1.currency == "GBP"
        assert l2.currency == "GBP"

    def test_pistonheads_nested_price_extracted(self):
        adapter  = _classified_adapter("pistonheads")
        [l1, _]  = adapter.parse(load_fixture("pistonheads"))
        assert l1.price == 145000.0

    def test_car_and_classic_nested_location_extracted(self):
        adapter  = _classified_adapter("car_and_classic")
        [l1, _]  = adapter.parse(load_fixture("car_and_classic"))
        assert l1.location == "Oxfordshire"

    def test_bring_a_trailer_currency_defaults_to_gbp(self):
        """BAT has no currency in field_mapping — should default to GBP."""
        adapter  = _classified_adapter("bring_a_trailer")
        [l1, _]  = adapter.parse(load_fixture("bring_a_trailer"))
        assert l1.currency == "GBP"

    def test_ebay_uk_sold_price_from_string(self):
        """eBay currentBidPrice.value is a string — must be coerced to float."""
        adapter = _auction_adapter("ebay_motors_uk")
        [r1, _] = adapter.parse(load_fixture("ebay_motors_uk"))
        assert r1.sold_price == 68500.0
        assert isinstance(r1.sold_price, float)

    def test_ebay_uk_currency_extracted(self):
        adapter = _auction_adapter("ebay_motors_uk")
        [r1, r2] = adapter.parse(load_fixture("ebay_motors_uk"))
        assert r1.currency == "GBP"
        assert r2.currency == "GBP"

    def test_ebay_uk_lot_id_equals_item_id(self):
        """lot_id and id are both mapped to itemId in eBay config."""
        adapter = _auction_adapter("ebay_motors_uk")
        [r1, _] = adapter.parse(load_fixture("ebay_motors_uk"))
        assert r1.lot_id == r1.id == "ebay-uk-001"

    def test_unmapped_fields_in_raw(self):
        """Fields not in field_mapping must be preserved in raw{}."""
        adapter  = _classified_adapter("autotrader_uk")
        [l1, l2] = adapter.parse(load_fixture("autotrader_uk"))
        assert "bodyType" in l1.raw
        assert l1.raw["bodyType"] == "Hatchback"
        assert "doors" in l1.raw

    def test_mapped_top_keys_excluded_from_raw(self):
        """Top-level keys used by dot-notation paths must not appear in raw{}."""
        adapter  = _classified_adapter("pistonheads")
        [l1, _]  = adapter.parse(load_fixture("pistonheads"))
        # advertisedPrice is used in "advertisedPrice.amount" and ".currency" — must not be in raw
        assert "advertisedPrice" not in l1.raw
        assert "advertiserLocation" not in l1.raw
