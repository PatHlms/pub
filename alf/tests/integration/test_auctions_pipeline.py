"""
Integration tests for the auction REST adapter pipeline.
"""
import pytest

from src.adapters.rest import RestAdapter
from src.models import AuctionRecord

from tests.integration.conftest import (
    AUCTION_SITE_CONFIG,
    make_fetcher,
    sample_auction_item,
)


def _adapter(fetcher=None, config=None):
    cfg = config or AUCTION_SITE_CONFIG
    return RestAdapter(cfg, fetcher or make_fetcher())


class TestAuctionParse:
    def test_parse_returns_auction_record(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert isinstance(record, AuctionRecord)

    def test_id_mapped(self):
        [record] = _adapter().parse([sample_auction_item(id_="lot-99")])
        assert record.id == "lot-99"

    def test_manufacturer_title_cased(self):
        [record] = _adapter().parse([sample_auction_item(make="porsche")])
        assert record.manufacturer == "Porsche"

    def test_model_title_cased(self):
        [record] = _adapter().parse([sample_auction_item(model="911 carrera")])
        assert record.model == "911 Carrera"

    def test_nested_sold_price_extracted(self):
        [record] = _adapter().parse([sample_auction_item(sold=75000.0)])
        assert record.sold_price == 75000.0

    def test_nested_reserve_and_start_extracted(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert record.reserve_price == 45000.0
        assert record.start_price == 30000.0

    def test_currency_uppercased(self):
        item = sample_auction_item(currency="gbp")
        [record] = _adapter().parse([item])
        assert record.currency == "GBP"

    def test_currency_defaults_to_gbp_when_null_in_mapping(self):
        """When field_mapping["currency"] is null, currency defaults to GBP."""
        config = {
            **AUCTION_SITE_CONFIG,
            "field_mapping": {**AUCTION_SITE_CONFIG["field_mapping"], "currency": None},
        }
        item = sample_auction_item()
        [record] = RestAdapter(config, make_fetcher()).parse([item])
        assert record.currency == "GBP"

    def test_lot_id_mapped(self):
        [record] = _adapter().parse([sample_auction_item(lot_number="Lot 42")])
        assert record.lot_id == "Lot 42"

    def test_lot_id_none_when_absent(self):
        item = sample_auction_item()
        del item["lotNumber"]
        [record] = _adapter().parse([item])
        assert record.lot_id is None

    def test_url_mapped(self):
        [record] = _adapter().parse([sample_auction_item(url="https://example.com/lot")])
        assert record.url == "https://example.com/lot"

    def test_auction_date_mapped(self):
        [record] = _adapter().parse([sample_auction_item(date="2024-06-01")])
        assert record.auction_date == "2024-06-01"

    def test_auction_date_parses_slash_format(self):
        item = sample_auction_item()
        item["date"] = "01/06/2024"
        [record] = _adapter().parse([item])
        assert record.auction_date == "2024-06-01"

    def test_source_set_to_site_name(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert record.source == "test_auction"

    def test_harvested_at_is_set(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert record.harvested_at is not None
        assert "T" in record.harvested_at

    def test_raw_excludes_mapped_top_keys(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert "price" not in record.raw
        assert "make" not in record.raw
        assert "model" not in record.raw

    def test_raw_includes_unmapped_keys(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert "extra_field" in record.raw

    def test_wrapped_response_itemsummaries(self):
        item = sample_auction_item()
        records = _adapter().parse({"itemSummaries": [item]})
        assert len(records) == 1

    def test_wrapped_response_data(self):
        records = _adapter().parse({"data": [sample_auction_item()]})
        assert len(records) == 1

    def test_wrapped_response_auctions(self):
        records = _adapter().parse({"auctions": [sample_auction_item()]})
        assert len(records) == 1

    def test_wrapped_response_lots(self):
        records = _adapter().parse({"lots": [sample_auction_item()]})
        assert len(records) == 1

    def test_unknown_wrapper_returns_empty(self):
        records = _adapter().parse({"totally_unknown": [sample_auction_item()]})
        assert records == []

    def test_multiple_items_all_parsed(self):
        items = [sample_auction_item(id_=str(i)) for i in range(10)]
        records = _adapter().parse(items)
        assert len(records) == 10

    def test_malformed_item_skipped(self):
        good = sample_auction_item(id_="ok")
        bad = None
        records = _adapter().parse([bad, good])
        assert len(records) == 1
        assert records[0].id == "ok"

    def test_fx_fields_default_to_none(self):
        [record] = _adapter().parse([sample_auction_item()])
        assert record.base_currency is None
        assert record.sold_price_base is None
        assert record.reserve_price_base is None
        assert record.start_price_base is None


class TestAuctionFetch:
    def test_fetch_offset_two_pages(self):
        page1 = [sample_auction_item(id_="1"), sample_auction_item(id_="2")]
        page2 = [sample_auction_item(id_="3")]  # short → stop
        fetcher = make_fetcher({"lots": page1}, {"lots": page2})
        records = _adapter(fetcher).fetch()
        assert len(records) == 3

    def test_fetch_returns_empty_on_http_error(self):
        fetcher = make_fetcher()
        fetcher.get.side_effect = Exception("timeout")
        assert _adapter(fetcher).fetch() == []

    def test_fetch_cursor_pagination(self):
        config = {
            **AUCTION_SITE_CONFIG,
            "pagination": {
                "type": "cursor",
                "cursor_param": "cursor",
                "cursor_response_field": "next",
            },
        }
        fetcher = make_fetcher(
            {"lots": [sample_auction_item(id_="a")], "next": "page2"},
            {"lots": [sample_auction_item(id_="b")]},
        )
        records = RestAdapter(config, fetcher).fetch()
        assert len(records) == 2

    def test_fetch_no_pagination_single_request(self):
        config = {**AUCTION_SITE_CONFIG, "pagination": {"type": "none"}}
        fetcher = make_fetcher([sample_auction_item(id_="x")])
        records = RestAdapter(config, fetcher).fetch()
        assert len(records) == 1
        fetcher.get.assert_called_once()
