"""
Integration tests for AuctionStorage and ClassifiedStorage.

Tests cover: file creation, correct path structure, JSON validity,
deduplication, merge-with-existing, and concurrent writes.
"""
import json
import threading

import pytest

from src.models import AuctionRecord
from src.storage import AuctionStorage
from src.classifieds.models import ClassifiedListing
from src.classifieds.storage import ClassifiedStorage


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def _auction(
    id_="lot-1",
    manufacturer="Porsche",
    model="911",
    date="2024-03-15",
    source="test_site",
    sold_price=50000.0,
    currency="GBP",
):
    return AuctionRecord(
        id=id_,
        source=source,
        lot_id=None,
        url="https://example.com/" + id_,
        manufacturer=manufacturer,
        model=model,
        sold_price=sold_price,
        reserve_price=None,
        start_price=None,
        currency=currency,
        auction_date=date,
    )


def _listing(
    id_="ad-1",
    manufacturer="Volkswagen",
    model="Golf",
    year=2019,
    date="2024-03-10",
    source="test_site",
    price=18500.0,
    currency="GBP",
):
    return ClassifiedListing(
        id=id_,
        source=source,
        manufacturer=manufacturer,
        model=model,
        year=year,
        price=price,
        currency=currency,
        mileage=32000,
        mileage_unit="miles",
        condition="used",
        fuel_type="Petrol",
        transmission="Manual",
        colour="Red",
        location="London",
        url="https://example.com/" + id_,
        listed_date=date,
    )


# ---------------------------------------------------------------------------
# AuctionStorage
# ---------------------------------------------------------------------------

class TestAuctionStorage:
    def test_creates_file_on_first_save(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction()
        storage.save([record])
        mfr, mdl, date = record.storage_path_parts
        expected = tmp_path / mfr / mdl / date / "auctions.json"
        assert expected.exists()

    def test_written_file_is_valid_json_array(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction()
        storage.save([record])
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_returns_count_of_new_records(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        n = storage.save([_auction(id_="1"), _auction(id_="2")])
        assert n == 2

    def test_deduplication_same_id_not_stored_twice(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction(id_="dup-1")
        storage.save([record])
        written = storage.save([record])
        assert written == 0
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert len(data) == 1

    def test_new_records_merged_with_existing(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        storage.save([_auction(id_="1")])
        storage.save([_auction(id_="2")])
        record = _auction(id_="1")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        ids = {r["id"] for r in data}
        assert ids == {"1", "2"}

    def test_empty_list_returns_zero(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        assert storage.save([]) == 0

    def test_path_uses_lowercase_slug(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction(manufacturer="Alfa Romeo", model="Giulia Sprint")
        storage.save([record])
        assert (tmp_path / "alfa_romeo").exists()
        assert (tmp_path / "alfa_romeo" / "giulia_sprint").exists()

    def test_path_fallback_manufacturer_unknown(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction(manufacturer="", model="")
        storage.save([record])
        assert (tmp_path / "unknown").exists()

    def test_records_contain_all_fields(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction(id_="r1", manufacturer="BMW", model="M3", sold_price=65000.0)
        storage.save([record])
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        r = data[0]
        assert r["id"] == "r1"
        assert r["manufacturer"] == "BMW"
        assert r["model"] == "M3"
        assert r["sold_price"] == 65000.0
        assert "harvested_at" in r

    def test_concurrent_writes_to_same_path_no_corruption(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        errors = []

        def save_batch(start, count):
            try:
                records = [_auction(id_=str(start + i)) for i in range(count)]
                storage.save(records)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_batch, args=(i * 10, 10)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        record = _auction(id_="0")
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        data = json.loads(path.read_text())
        assert len(data) == 50

    def test_corrupted_existing_file_is_overwritten(self, tmp_path):
        storage = AuctionStorage(str(tmp_path))
        record = _auction()
        mfr, mdl, date = record.storage_path_parts
        path = tmp_path / mfr / mdl / date / "auctions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("this is not json {{{{")
        written = storage.save([record])
        assert written == 1
        data = json.loads(path.read_text())
        assert len(data) == 1


# ---------------------------------------------------------------------------
# ClassifiedStorage
# ---------------------------------------------------------------------------

class TestClassifiedStorage:
    def test_creates_file_on_first_save(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing()
        storage.save([listing])
        mfr, mdl, date = listing.storage_path_parts
        expected = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        assert expected.exists()

    def test_path_has_classifieds_prefix(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing()
        storage.save([listing])
        # "classifieds" subdir must be present
        assert (tmp_path / "classifieds").is_dir()

    def test_written_file_is_valid_json_array(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing()
        storage.save([listing])
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_returns_count_of_new_listings(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        n = storage.save([_listing(id_="1"), _listing(id_="2")])
        assert n == 2

    def test_deduplication(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing(id_="dup")
        storage.save([listing])
        written = storage.save([listing])
        assert written == 0

    def test_merge_existing_and_new(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        storage.save([_listing(id_="1")])
        storage.save([_listing(id_="2")])
        listing = _listing(id_="1")
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        assert {r["id"] for r in data} == {"1", "2"}

    def test_empty_list_returns_zero(self, tmp_path):
        assert ClassifiedStorage(str(tmp_path)).save([]) == 0

    def test_records_contain_classified_fields(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing(id_="l1", year=2020, price=21000.0)
        storage.save([listing])
        mfr, mdl, date = listing.storage_path_parts
        path = tmp_path / "classifieds" / mfr / mdl / date / "listings.json"
        data = json.loads(path.read_text())
        r = data[0]
        assert r["year"] == 2020
        assert r["price"] == 21000.0
        assert r["mileage_unit"] == "miles"
        assert "harvested_at" in r

    def test_path_fallback_uses_harvested_at_when_no_listed_date(self, tmp_path):
        storage = ClassifiedStorage(str(tmp_path))
        listing = _listing(date=None)
        # Should not raise; uses harvested_at[:10] as date
        written = storage.save([listing])
        assert written == 1
