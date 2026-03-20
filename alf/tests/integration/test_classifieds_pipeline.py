"""
Integration tests for the classifieds REST adapter pipeline.

These tests exercise the full parse path — field mapping, type coercion,
nested dot-notation extraction, pagination — using a mock fetcher so no
real HTTP calls are made.
"""
import pytest

from src.classifieds.adapters.rest import ClassifiedRestAdapter
from src.classifieds.models import ClassifiedListing

from tests.integration.conftest import (
    CLASSIFIED_SITE_CONFIG,
    make_fetcher,
    sample_classified_item,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _adapter(fetcher=None, config=None):
    cfg = config or CLASSIFIED_SITE_CONFIG
    return ClassifiedRestAdapter(cfg, fetcher or make_fetcher())


# ---------------------------------------------------------------------------
# Field mapping and type coercion
# ---------------------------------------------------------------------------

class TestClassifiedParse:
    def test_parse_single_item_returns_listing(self):
        adapter = _adapter()
        items = [sample_classified_item()]
        listings = adapter.parse({"listings": items})
        assert len(listings) == 1
        assert isinstance(listings[0], ClassifiedListing)

    def test_parse_flat_list_response(self):
        adapter = _adapter()
        listings = adapter.parse([sample_classified_item()])
        assert len(listings) == 1

    def test_id_mapped_correctly(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(listing_id="ad-999")])
        assert listing.id == "ad-999"

    def test_manufacturer_title_cased(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(make="volkswagen")])
        assert listing.manufacturer == "Volkswagen"

    def test_model_title_cased(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(model="golf gti")])
        assert listing.model == "Golf Gti"

    def test_nested_price_extracted(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(price_amount=22500.0)])
        assert listing.price == 22500.0

    def test_nested_currency_extracted(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(price_currency="EUR")])
        assert listing.currency == "EUR"

    def test_currency_uppercased(self):
        adapter = _adapter()
        item = sample_classified_item()
        item["price"]["currency"] = "gbp"
        [listing] = adapter.parse([item])
        assert listing.currency == "GBP"

    def test_currency_defaults_to_gbp_when_absent(self):
        adapter = _adapter()
        item = sample_classified_item()
        del item["price"]["currency"]
        [listing] = adapter.parse([item])
        assert listing.currency == "GBP"

    def test_nested_location_extracted(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(town="Manchester")])
        assert listing.location == "Manchester"

    def test_year_converted_to_int(self):
        adapter = _adapter()
        item = sample_classified_item()
        item["year"] = "2019"
        [listing] = adapter.parse([item])
        assert listing.year == 2019
        assert isinstance(listing.year, int)

    def test_year_from_float_string(self):
        adapter = _adapter()
        item = sample_classified_item()
        item["year"] = "2019.0"
        [listing] = adapter.parse([item])
        assert listing.year == 2019

    def test_mileage_converted_to_int(self):
        adapter = _adapter()
        item = sample_classified_item()
        item["mileage"] = "32000"
        [listing] = adapter.parse([item])
        assert listing.mileage == 32000
        assert isinstance(listing.mileage, int)

    def test_mileage_unit_lowercased(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(mileage_unit="Miles")])
        assert listing.mileage_unit == "miles"

    def test_mileage_unit_defaults_to_miles_when_absent(self):
        adapter = _adapter()
        item = sample_classified_item()
        del item["mileageUnit"]
        [listing] = adapter.parse([item])
        assert listing.mileage_unit == "miles"

    def test_source_set_from_config_name(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item()])
        assert listing.source == "test_classified"

    def test_all_vehicle_specifics_mapped(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(
            condition="used", fuel_type="Petrol", gearbox="Manual", colour="Red"
        )])
        assert listing.condition == "used"
        assert listing.fuel_type == "Petrol"
        assert listing.transmission == "Manual"
        assert listing.colour == "Red"

    def test_url_mapped(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(url="https://example.com/car")])
        assert listing.url == "https://example.com/car"

    def test_listed_date_parsed(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item(listed_at="2024-03-10")])
        assert listing.listed_date == "2024-03-10"

    def test_listed_date_parses_slash_format(self):
        adapter = _adapter()
        item = sample_classified_item()
        item["listedAt"] = "10/03/2024"
        [listing] = adapter.parse([item])
        assert listing.listed_date == "2024-03-10"

    def test_harvested_at_is_set(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item()])
        assert listing.harvested_at is not None
        assert "T" in listing.harvested_at  # ISO format

    def test_raw_excludes_mapped_top_keys(self):
        """Keys whose top-level name appears in field_mapping paths are excluded from raw."""
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item()])
        # "price", "location", "listingId", "make", "model" are all mapped
        assert "price" not in listing.raw
        assert "location" not in listing.raw
        assert "listingId" not in listing.raw

    def test_raw_includes_unmapped_keys(self):
        adapter = _adapter()
        [listing] = adapter.parse([sample_classified_item()])
        assert "extra_field" in listing.raw
        assert listing.raw["extra_field"] == "ignored"

    def test_multiple_items_all_parsed(self):
        adapter = _adapter()
        items = [sample_classified_item(listing_id=str(i)) for i in range(5)]
        listings = adapter.parse(items)
        assert len(listings) == 5
        assert [l.id for l in listings] == [str(i) for i in range(5)]

    def test_malformed_item_skipped_others_returned(self):
        """An item that raises during mapping is skipped; valid items are returned."""
        adapter = _adapter()
        good = sample_classified_item(listing_id="good")
        bad = None  # causes TypeError in _map_item
        listings = adapter.parse([bad, good])
        assert len(listings) == 1
        assert listings[0].id == "good"

    def test_unknown_wrapper_key_returns_empty(self):
        adapter = _adapter()
        listings = adapter.parse({"completely_unknown_key": [sample_classified_item()]})
        assert listings == []

    def test_empty_response_returns_empty(self):
        adapter = _adapter()
        assert adapter.parse([]) == []
        assert adapter.parse({}) == []


# ---------------------------------------------------------------------------
# Pagination via fetch()
# ---------------------------------------------------------------------------

class TestClassifiedFetchPagination:
    def test_fetch_single_full_page_then_empty(self):
        page1 = [sample_classified_item(listing_id="a"), sample_classified_item(listing_id="b")]
        page2 = []
        fetcher = make_fetcher({"listings": page1}, {"listings": page2})
        adapter = _adapter(fetcher)
        listings = adapter.fetch()
        assert len(listings) == 2

    def test_fetch_two_full_pages_then_short(self):
        """pageSize=2; two full pages + one short page = stops correctly."""
        page1 = [sample_classified_item(listing_id="1"), sample_classified_item(listing_id="2")]
        page2 = [sample_classified_item(listing_id="3"), sample_classified_item(listing_id="4")]
        page3 = [sample_classified_item(listing_id="5")]  # short page → stop
        fetcher = make_fetcher(
            {"listings": page1},
            {"listings": page2},
            {"listings": page3},
        )
        adapter = _adapter(fetcher)
        listings = adapter.fetch()
        assert len(listings) == 5
        assert [l.id for l in listings] == ["1", "2", "3", "4", "5"]

    def test_fetch_stops_immediately_on_empty_first_page(self):
        fetcher = make_fetcher({"listings": []})
        adapter = _adapter(fetcher)
        listings = adapter.fetch()
        assert listings == []
        fetcher.get.assert_called_once()

    def test_fetch_http_error_returns_empty(self):
        fetcher = make_fetcher()
        fetcher.get.side_effect = Exception("connection refused")
        adapter = _adapter(fetcher)
        listings = adapter.fetch()
        assert listings == []

    def test_fetch_cursor_pagination(self):
        config = {
            **CLASSIFIED_SITE_CONFIG,
            "pagination": {
                "type": "cursor",
                "cursor_param": "cursor",
                "cursor_response_field": "next_cursor",
            },
        }
        item_a = sample_classified_item(listing_id="a")
        item_b = sample_classified_item(listing_id="b")
        item_c = sample_classified_item(listing_id="c")
        fetcher = make_fetcher(
            {"listings": [item_a], "next_cursor": "tok1"},
            {"listings": [item_b], "next_cursor": "tok2"},
            {"listings": [item_c]},  # no next_cursor → stop
        )
        adapter = _adapter(fetcher, config)
        listings = adapter.fetch()
        assert len(listings) == 3
        assert [l.id for l in listings] == ["a", "b", "c"]

    def test_fetch_no_pagination_single_request(self):
        config = {**CLASSIFIED_SITE_CONFIG, "pagination": {"type": "none"}}
        item = sample_classified_item()
        fetcher = make_fetcher([item])
        adapter = _adapter(fetcher, config)
        listings = adapter.fetch()
        assert len(listings) == 1
        fetcher.get.assert_called_once()
