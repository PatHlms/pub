"""
Validation tests for sites.json configuration files.

These tests load the actual config files from disk and verify that every
site entry satisfies the structural requirements the adapter code relies on.
"""
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load config files
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parents[2]  # alf/

AUCTION_SITES_PATH     = _REPO_ROOT / "config" / "auctions"    / "sites.json"
CLASSIFIED_SITES_PATH  = _REPO_ROOT / "config" / "classifieds" / "sites.json"
AUCTION_SETTINGS_PATH  = _REPO_ROOT / "config" / "auctions"    / "settings.json"
CLASSIFIED_SETTINGS_PATH = _REPO_ROOT / "config" / "classifieds" / "settings.json"


def _load_sites(path: Path) -> list[dict]:
    return json.loads(path.read_text())["sites"]


AUCTION_SITES    = _load_sites(AUCTION_SITES_PATH)
CLASSIFIED_SITES = _load_sites(CLASSIFIED_SITES_PATH)
ALL_SITES        = [(s, "auctions") for s in AUCTION_SITES] + \
                   [(s, "classifieds") for s in CLASSIFIED_SITES]


KNOWN_AUTH_TYPES = {"api_key", "bearer", "basic", "oauth2_client_credentials", "none"}
KNOWN_ADAPTERS   = {"rest"}
KNOWN_PAG_TYPES  = {"offset", "cursor", "none"}

# Fields the classifieds adapter knows about
CLASSIFIED_CANONICAL = {
    "id", "manufacturer", "model", "year", "price", "currency",
    "mileage", "mileage_unit", "condition", "fuel_type", "transmission",
    "colour", "location", "url", "listed_date",
}
# Fields the auction adapter knows about
AUCTION_CANONICAL = {
    "id", "manufacturer", "model", "sold_price", "reserve_price",
    "start_price", "currency", "auction_date", "url", "lot_id",
}


def _site_id(s, module):
    return f"{module}/{s.get('name', '?')}"


# ---------------------------------------------------------------------------
# Parameterised: all sites
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("site,module", ALL_SITES, ids=[_site_id(s, m) for s, m in ALL_SITES])
class TestRequiredTopLevelKeys:
    REQUIRED = {"name", "enabled", "adapter", "base_url", "auth", "endpoints"}

    def test_all_required_keys_present(self, site, module):
        missing = self.REQUIRED - site.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_name_is_non_empty_string(self, site, module):
        assert isinstance(site["name"], str) and site["name"]

    def test_enabled_is_bool(self, site, module):
        assert isinstance(site["enabled"], bool)

    def test_adapter_is_known(self, site, module):
        assert site["adapter"] in KNOWN_ADAPTERS

    def test_base_url_starts_with_https(self, site, module):
        assert site["base_url"].startswith("https://"), \
            f"{site['name']}: base_url should use HTTPS"

    def test_endpoints_has_auctions_key(self, site, module):
        assert "auctions" in site["endpoints"]
        assert site["endpoints"]["auctions"].startswith("/")


@pytest.mark.parametrize("site,module", ALL_SITES, ids=[_site_id(s, m) for s, m in ALL_SITES])
class TestAuthConfig:
    def test_auth_type_is_known(self, site, module):
        assert site["auth"]["type"] in KNOWN_AUTH_TYPES

    def test_api_key_auth_has_header_and_env_var(self, site, module):
        if site["auth"]["type"] != "api_key":
            pytest.skip("not api_key auth")
        assert "header" in site["auth"], "api_key auth must have 'header'"
        assert "env_var" in site["auth"], "api_key auth must have 'env_var'"
        assert site["auth"]["header"]
        assert site["auth"]["env_var"]

    def test_oauth2_auth_has_required_fields(self, site, module):
        if site["auth"]["type"] != "oauth2_client_credentials":
            pytest.skip("not oauth2 auth")
        required = {"token_url", "client_id_env_var", "client_secret_env_var"}
        missing = required - site["auth"].keys()
        assert not missing, f"oauth2 auth missing: {missing}"

    def test_bearer_auth_has_env_var(self, site, module):
        if site["auth"]["type"] != "bearer":
            pytest.skip("not bearer auth")
        assert "env_var" in site["auth"]


@pytest.mark.parametrize("site,module", ALL_SITES, ids=[_site_id(s, m) for s, m in ALL_SITES])
class TestRateLimitConfig:
    def test_rate_limit_present(self, site, module):
        assert "rate_limit" in site

    def test_requests_per_second_positive(self, site, module):
        rps = site["rate_limit"].get("requests_per_second", 0)
        assert rps > 0

    def test_burst_positive(self, site, module):
        burst = site["rate_limit"].get("burst", 0)
        assert burst > 0


@pytest.mark.parametrize("site,module", ALL_SITES, ids=[_site_id(s, m) for s, m in ALL_SITES])
class TestPaginationConfig:
    def test_pagination_type_known(self, site, module):
        pag_type = site.get("pagination", {}).get("type", "none")
        assert pag_type in KNOWN_PAG_TYPES

    def test_offset_pagination_has_required_params(self, site, module):
        pag = site.get("pagination", {})
        if pag.get("type") != "offset":
            pytest.skip("not offset pagination")
        assert "page_param" in pag
        assert "page_size_param" in pag

    def test_cursor_pagination_has_required_params(self, site, module):
        pag = site.get("pagination", {})
        if pag.get("type") != "cursor":
            pytest.skip("not cursor pagination")
        assert "cursor_param" in pag
        assert "cursor_response_field" in pag


@pytest.mark.parametrize("site,module", ALL_SITES, ids=[_site_id(s, m) for s, m in ALL_SITES])
class TestFieldMapping:
    def test_field_mapping_present(self, site, module):
        assert "field_mapping" in site

    def test_id_field_always_mapped(self, site, module):
        mapping = site["field_mapping"]
        assert "id" in mapping, "field_mapping must include 'id'"
        assert mapping["id"] is not None, "'id' field must have a non-null path"

    def test_non_null_paths_are_non_empty_strings(self, site, module):
        for canonical, path in site["field_mapping"].items():
            if path is not None:
                assert isinstance(path, str) and path, \
                    f"{site['name']}: field_mapping['{canonical}'] = {path!r} is invalid"

    def test_canonical_fields_from_known_set(self, site, module):
        known = CLASSIFIED_CANONICAL if module == "classifieds" else AUCTION_CANONICAL
        unknown = set(site["field_mapping"].keys()) - known
        assert not unknown, \
            f"{site['name']}: unknown field_mapping keys: {unknown}"


# ---------------------------------------------------------------------------
# Settings file validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("settings_path,label", [
    (AUCTION_SETTINGS_PATH,     "auctions"),
    (CLASSIFIED_SETTINGS_PATH,  "classifieds"),
])
class TestSettingsConfig:
    def test_settings_file_parseable(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        assert isinstance(data, dict)

    def test_batch_interval_positive(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        assert data.get("batch_interval_seconds", 0) > 0

    def test_max_workers_positive(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        assert data.get("max_workers", 0) > 0

    def test_fx_block_present(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        assert "fx" in data

    def test_fx_base_currency_is_three_char_uppercase(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        base = data["fx"].get("base_currency", "")
        assert len(base) == 3 and base == base.upper()

    def test_fx_provider_is_known(self, settings_path, label):
        data = json.loads(settings_path.read_text())
        provider = data["fx"].get("provider", "")
        assert provider in {"frankfurter", "openexchangerates", "fixer"}
