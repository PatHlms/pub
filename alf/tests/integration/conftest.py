"""
Shared fixtures and helpers for integration tests.
"""
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Minimal site configs (auth type "none" avoids env-var reads in Fetcher)
# ---------------------------------------------------------------------------

AUCTION_SITE_CONFIG = {
    "name": "test_auction",
    "base_url": "https://api.example.com",
    "endpoints": {"auctions": "/v1/lots"},
    "auth": {"type": "none"},
    "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
    "retry": {"max_attempts": 1, "backoff_factor": 1.0, "retry_on_status": []},
    "default_params": {"pageSize": 2},
    "pagination": {
        "type": "offset",
        "page_param": "page",
        "page_size_param": "pageSize",
        "start_page": 1,
        "offset_step": 1,
    },
    "field_mapping": {
        "id":            "id",
        "manufacturer":  "make",
        "model":         "model",
        "sold_price":    "price.sold",
        "reserve_price": "price.reserve",
        "start_price":   "price.start",
        "currency":      "currency",
        "auction_date":  "date",
        "url":           "url",
        "lot_id":        "lotNumber",
    },
}

CLASSIFIED_SITE_CONFIG = {
    "name": "test_classified",
    "base_url": "https://api.example.com",
    "endpoints": {"auctions": "/v1/listings"},
    "auth": {"type": "none"},
    "rate_limit": {"requests_per_second": 1000.0, "burst": 100},
    "retry": {"max_attempts": 1, "backoff_factor": 1.0, "retry_on_status": []},
    "default_params": {"pageSize": 2},
    "pagination": {
        "type": "offset",
        "page_param": "page",
        "page_size_param": "pageSize",
        "start_page": 1,
        "offset_step": 1,
    },
    "field_mapping": {
        "id":           "listingId",
        "manufacturer": "make",
        "model":        "model",
        "year":         "year",
        "price":        "price.amount",
        "currency":     "price.currency",
        "mileage":      "mileage",
        "mileage_unit": "mileageUnit",
        "condition":    "condition",
        "fuel_type":    "fuelType",
        "transmission": "gearbox",
        "colour":       "colour",
        "location":     "location.town",
        "url":          "url",
        "listed_date":  "listedAt",
    },
}

GLOBAL_RETRY = {"max_attempts": 1, "backoff_factor": 1.0, "retry_on_status": []}


def make_fetcher(*responses):
    """Return a mock fetcher whose get() yields responses in sequence."""
    fetcher = MagicMock()
    fetcher.get.side_effect = list(responses)
    return fetcher


# ---------------------------------------------------------------------------
# Sample raw API items
# ---------------------------------------------------------------------------

def sample_auction_item(
    id_="lot-1",
    make="Porsche",
    model="911",
    sold=50000.0,
    currency="GBP",
    date="2024-03-15",
    url="https://example.com/lot-1",
    lot_number="42",
):
    return {
        "id": id_,
        "make": make,
        "model": model,
        "price": {"sold": sold, "reserve": 45000.0, "start": 30000.0},
        "currency": currency,
        "date": date,
        "url": url,
        "lotNumber": lot_number,
        "extra_field": "ignored",
    }


def sample_classified_item(
    listing_id="ad-1",
    make="Volkswagen",
    model="Golf GTI",
    year=2019,
    price_amount=18500.0,
    price_currency="GBP",
    mileage=32000,
    mileage_unit="miles",
    condition="used",
    fuel_type="Petrol",
    gearbox="Manual",
    colour="Red",
    town="London",
    url="https://example.com/ad-1",
    listed_at="2024-03-10",
):
    return {
        "listingId": listing_id,
        "make": make,
        "model": model,
        "year": year,
        "price": {"amount": price_amount, "currency": price_currency},
        "mileage": mileage,
        "mileageUnit": mileage_unit,
        "condition": condition,
        "fuelType": fuel_type,
        "gearbox": gearbox,
        "colour": colour,
        "location": {"town": town},
        "url": url,
        "listedAt": listed_at,
        "extra_field": "ignored",
    }
