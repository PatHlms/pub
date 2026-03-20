"""
Storage format regression tests.

Verify that JSON files written to disk by AuctionStorage and ClassifiedStorage
maintain a stable, backward-compatible schema. Any change to the serialised
format will be caught here before it silently breaks downstream consumers.
"""
import json

import pytest

from src.models import AuctionRecord
from src.storage import AuctionStorage
from src.classifieds.models import ClassifiedListing
from src.classifieds.storage import ClassifiedStorage


# Expected top-level keys for each record type
AUCTION_RECORD_KEYS = {
    "id", "source", "lot_id", "url",
    "manufacturer", "model",
    "sold_price", "reserve_price", "start_price", "currency",
    "auction_date", "harvested_at",
    "base_currency", "sold_price_base", "reserve_price_base", "start_price_base",
    "raw",
}

CLASSIFIED_LISTING_KEYS = {
    "id", "source",
    "manufacturer", "model", "year",
    "price", "currency",
    "mileage", "mileage_unit",
    "condition", "fuel_type", "transmission", "colour",
    "location", "url",
    "listed_date", "harvested_at",
    "base_currency", "price_base",
    "raw",
}


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _auction(**kwargs):
    defaults = dict(
        id="lot-1", source="ebay_motors_uk", lot_id="42",
        url="https://ebay.co.uk/lot-1", manufacturer="Porsche", model="911",
        sold_price=68500.0, reserve_price=None, start_price=1.0, currency="GBP",
        auction_date="2024-03-15",
    )
    defaults.update(kwargs)
    return AuctionRecord(**defaults)


def _listing(**kwargs):
    defaults = dict(
        id="ad-1", source="autotrader_uk", manufacturer="Volkswagen", model="Golf GTI",
        year=2020, price=22995.0, currency="GBP", mileage=28500, mileage_unit="miles",
        condition="Used", fuel_type="Petrol", transmission="Manual", colour="Red",
        location="Birmingham", url="https://autotrader.co.uk/ad-1", listed_date="2024-03-01",
    )
    defaults.update(kwargs)
    return ClassifiedListing(**defaults)


# ---------------------------------------------------------------------------
# AuctionStorage format stability
# ---------------------------------------------------------------------------

class TestAuctionStorageFormat:
    def test_written_file_has_all_expected_keys(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction()])
        record = _auction()
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert set(data[0].keys()) == AUCTION_RECORD_KEYS

    def test_no_extra_keys_written(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction()])
        record = _auction()
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        extra = set(data[0].keys()) - AUCTION_RECORD_KEYS
        assert not extra, f"Unexpected extra keys in written record: {extra}"

    def test_id_field_type_is_string(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction(id="lot-99")])
        record = _auction(id="lot-99")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert isinstance(data[0]["id"], str)

    def test_sold_price_is_numeric_or_null(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        r1 = _auction(id="a", sold_price=50000.0)
        r2 = _auction(id="b", sold_price=None)
        storage.save([r1, r2])
        record = _auction(id="a")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        by_id = {r["id"]: r for r in data}
        assert isinstance(by_id["a"]["sold_price"], (int, float))
        assert by_id["b"]["sold_price"] is None

    def test_currency_is_three_char_uppercase(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction(currency="GBP")])
        record = _auction(currency="GBP")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert data[0]["currency"] == "GBP"

    def test_harvested_at_is_iso_timestamp(self, tmp_path):
        import re
        ts_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:")
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction()])
        record = _auction()
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert ts_re.match(data[0]["harvested_at"])

    def test_raw_field_is_dict(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction()
        record.raw = {"extra": "value"}
        storage.save([record])
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert isinstance(data[0]["raw"], dict)
        assert data[0]["raw"]["extra"] == "value"

    def test_fx_fields_null_when_not_converted(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction()])
        record = _auction()
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert data[0]["base_currency"] is None
        assert data[0]["sold_price_base"] is None
        assert data[0]["reserve_price_base"] is None
        assert data[0]["start_price_base"] is None

    def test_fx_fields_written_when_converted(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction()
        record.base_currency      = "GBP"
        record.sold_price_base    = 68500.0
        record.reserve_price_base = None
        record.start_price_base   = 1.0
        storage.save([record])
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert data[0]["base_currency"] == "GBP"
        assert data[0]["sold_price_base"] == 68500.0
        assert data[0]["start_price_base"] == 1.0

    def test_multiple_records_all_have_correct_keys(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        records = [_auction(id=str(i)) for i in range(5)]
        storage.save(records)
        record = _auction(id="0")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        for r in data:
            assert set(r.keys()) == AUCTION_RECORD_KEYS

    def test_file_path_structure(self, tmp_path):
        """Path must be: {data_dir}/{mfr}/{model}/{date}/auctions.json"""
        storage = AuctionStorage(str(tmp_path))
        record = _auction(manufacturer="Porsche", model="911", auction_date="2024-03-15")
        storage.save([record])
        expected = tmp_path / "porsche" / "911" / "2024-03-15" / "auctions.json"
        assert expected.exists()


# ---------------------------------------------------------------------------
# ClassifiedStorage format stability
# ---------------------------------------------------------------------------

class TestClassifiedStorageFormat:
    def test_written_file_has_all_expected_keys(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing()])
        listing = _listing()
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert set(data[0].keys()) == CLASSIFIED_LISTING_KEYS

    def test_no_extra_keys_written(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing()])
        listing = _listing()
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        extra = set(data[0].keys()) - CLASSIFIED_LISTING_KEYS
        assert not extra, f"Unexpected extra keys: {extra}"

    def test_year_is_int_or_null(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        l1 = _listing(id="a", year=2020)
        l2 = _listing(id="b", year=None)
        storage.save([l1, l2])
        listing = _listing(id="a")
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        by_id = {r["id"]: r for r in data}
        assert isinstance(by_id["a"]["year"], int)
        assert by_id["b"]["year"] is None

    def test_price_is_numeric_or_null(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        l1 = _listing(id="a", price=22995.0)
        l2 = _listing(id="b", price=None)
        storage.save([l1, l2])
        listing = _listing(id="a")
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        by_id = {r["id"]: r for r in data}
        assert isinstance(by_id["a"]["price"], (int, float))
        assert by_id["b"]["price"] is None

    def test_mileage_is_int_or_null(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing(mileage=28500)])
        listing = _listing()
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert isinstance(data[0]["mileage"], int)

    def test_mileage_unit_is_lowercase_string(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing(mileage_unit="miles")])
        listing = _listing()
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert data[0]["mileage_unit"] == "miles"

    def test_classifieds_prefix_in_path(self, tmp_path):
        """Path must include 'classifieds' subdirectory."""
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing(manufacturer="Volkswagen", model="Golf Gti", listed_date="2024-03-01")
        storage.save([listing])
        expected = tmp_path / "classifieds" / "volkswagen" / "golf_gti" / "2024-03-01" / "listings.json"
        assert expected.exists()

    def test_fx_fields_null_when_not_converted(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing()])
        listing = _listing()
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert data[0]["base_currency"] is None
        assert data[0]["price_base"] is None

    def test_fx_fields_written_when_converted(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing()
        listing.base_currency = "GBP"
        listing.price_base    = 22995.0
        storage.save([listing])
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert data[0]["base_currency"] == "GBP"
        assert data[0]["price_base"] == 22995.0

    def test_source_field_matches_site_name(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing(source="autotrader_uk")])
        listing = _listing(source="autotrader_uk")
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert data[0]["source"] == "autotrader_uk"

    def test_unicode_preserved_in_json(self, tmp_path):
        """ensure_ascii=False: unicode characters must survive round-trip."""
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing(manufacturer="Ñoño Motors", colour="Über Weiß")
        storage.save([listing])
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        raw_text = path.read_text(encoding="utf-8")
        # Must not be escaped as \u00d1 etc.
        assert "Ñoño" in raw_text
        assert "Über" in raw_text
