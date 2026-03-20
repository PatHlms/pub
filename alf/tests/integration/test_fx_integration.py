"""
Integration tests for FXProvider rate fetching, caching, and conversion.

HTTP calls are mocked via monkeypatch so no live network access is required.
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from src.fx import FXProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider(base="GBP", provider="frankfurter", rates_ttl=3600):
    cfg = {
        "base_currency": base,
        "provider": provider,
        "api_key_env_var": None,
        "rates_ttl_seconds": rates_ttl,
    }
    return FXProvider(cfg)


def _mock_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _skip_fetch(fx, rates):
    """Pre-populate rates and mark as freshly fetched to suppress network calls."""
    fx._rates = rates
    fx._fetched_at = time.monotonic()


# ---------------------------------------------------------------------------
# Frankfurter provider
# ---------------------------------------------------------------------------

class TestFrankfurterIntegration:
    def test_rates_loaded_and_inverted(self, monkeypatch):
        """frankfurter returns CCY per 1 GBP; we store GBP per 1 CCY (inverted)."""
        data = {"base": "GBP", "rates": {"USD": 1.27, "EUR": 1.17}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("GBP")
        result = fx.convert(127.0, "USD")
        assert result == pytest.approx(100.0, rel=1e-3)

    def test_base_currency_always_maps_to_one(self, monkeypatch):
        data = {"base": "GBP", "rates": {"USD": 1.27}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("GBP")
        fx.convert(1.0, "USD")  # triggers fetch
        assert fx._rates.get("GBP") == 1.0

    def test_correct_url_and_params_sent(self, monkeypatch):
        calls = []
        def fake_get(url, params=None, timeout=None):
            calls.append((url, params))
            return _mock_response({"base": "GBP", "rates": {"USD": 1.27}})
        monkeypatch.setattr("requests.get", fake_get)
        fx = _provider("GBP")
        fx.convert(100.0, "USD")
        assert calls[0][0] == "https://api.frankfurter.app/latest"
        assert calls[0][1]["from"] == "GBP"

    def test_eur_base(self, monkeypatch):
        data = {"base": "EUR", "rates": {"GBP": 0.85, "USD": 1.08}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("EUR")
        # 108 USD at 1 USD = (1/1.08) EUR ≈ 100 EUR
        result = fx.convert(108.0, "USD")
        assert result == pytest.approx(100.0, rel=1e-2)


# ---------------------------------------------------------------------------
# OpenExchangeRates provider
# ---------------------------------------------------------------------------

class TestOpenExchangeRatesIntegration:
    def test_cross_rate_computation(self, monkeypatch):
        """
        OXR returns CCY per 1 USD.  For GBP base:
          GBP_per_CCY = (GBP per USD) / (CCY per USD)
          GBP per USD = usd_rates["GBP"] = 0.79
          GBP per EUR = 0.79 / 1.17
        """
        usd_rates = {"GBP": 0.79, "EUR": 1.17, "JPY": 148.5}
        data = {"rates": usd_rates}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("GBP", provider="openexchangerates")
        result = fx.convert(100.0, "EUR")
        expected = round(100.0 * (0.79 / 1.17), 2)
        assert result == pytest.approx(expected, rel=1e-4)

    def test_same_base_as_request_base_maps_to_one(self, monkeypatch):
        usd_rates = {"GBP": 0.79, "USD": 1.0}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response({"rates": usd_rates}))
        fx = _provider("GBP", provider="openexchangerates")
        fx.convert(1.0, "EUR")  # trigger fetch
        assert fx._rates.get("GBP") == 1.0


# ---------------------------------------------------------------------------
# Fixer provider
# ---------------------------------------------------------------------------

class TestFixerIntegration:
    def test_rates_loaded_on_success(self, monkeypatch):
        data = {"success": True, "base": "GBP", "rates": {"USD": 1.27, "EUR": 1.17}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("GBP", provider="fixer")
        result = fx.convert(127.0, "USD")
        assert result == pytest.approx(100.0, rel=1e-3)

    def test_fixer_error_response_leaves_rates_empty(self, monkeypatch):
        data = {"success": False, "error": {"info": "paid plan required"}}
        monkeypatch.setattr("requests.get", lambda *a, **kw: _mock_response(data))
        fx = _provider("GBP", provider="fixer")
        result = fx.convert(100.0, "USD")
        assert result is None  # rates empty after failed fetch


# ---------------------------------------------------------------------------
# TTL caching behaviour
# ---------------------------------------------------------------------------

class TestTTLCaching:
    def test_rates_not_refetched_within_ttl(self, monkeypatch):
        fetch_count = {"n": 0}
        def fake_fetch(self):
            fetch_count["n"] += 1
            self._rates = {"USD": 0.79}
            self._rates["GBP"] = 1.0
        monkeypatch.setattr(FXProvider, "_fetch_frankfurter", fake_fetch)
        fx = _provider(rates_ttl=3600)
        fx.convert(100.0, "USD")  # triggers fetch #1
        fx.convert(200.0, "USD")  # within TTL → no refetch
        fx.convert(300.0, "USD")
        assert fetch_count["n"] == 1

    def test_rates_refetched_after_ttl_expires(self, monkeypatch):
        fetch_count = {"n": 0}
        def fake_fetch(self):
            fetch_count["n"] += 1
            self._rates = {"USD": 0.79}
            self._rates["GBP"] = 1.0
        monkeypatch.setattr(FXProvider, "_fetch_frankfurter", fake_fetch)
        fx = _provider(rates_ttl=0)  # TTL=0 → every call re-fetches
        fx.convert(100.0, "USD")
        fx.convert(200.0, "USD")
        assert fetch_count["n"] == 2

    def test_same_currency_skips_fetch(self, monkeypatch):
        fetch_count = {"n": 0}
        def fake_fetch(self):
            fetch_count["n"] += 1
        monkeypatch.setattr(FXProvider, "_fetch_frankfurter", fake_fetch)
        fx = _provider("GBP")
        fx.convert(100.0, "GBP")  # same currency → returns immediately, no fetch
        assert fetch_count["n"] == 0

    def test_failed_fetch_still_updates_fetched_at(self, monkeypatch):
        """After a fetch failure _fetched_at must be updated to prevent retry storms."""
        def fail(self):
            raise RuntimeError("network down")
        monkeypatch.setattr(FXProvider, "_fetch_frankfurter", fail)
        fx = _provider()
        t_before = time.monotonic()
        fx.convert(100.0, "USD")
        assert fx._fetched_at >= t_before

    def test_failed_fetch_does_not_retry_within_ttl(self, monkeypatch):
        call_count = {"n": 0}
        def fail(self):
            call_count["n"] += 1
            raise RuntimeError("down")
        monkeypatch.setattr(FXProvider, "_fetch_frankfurter", fail)
        fx = _provider(rates_ttl=3600)
        fx.convert(100.0, "USD")
        fx.convert(200.0, "USD")
        fx.convert(300.0, "USD")
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# Conversion correctness
# ---------------------------------------------------------------------------

class TestConversionCorrectness:
    def test_none_amount_returns_none(self):
        fx = _provider()
        _skip_fetch(fx, {"USD": 0.79})
        assert fx.convert(None, "USD") is None

    def test_unknown_currency_returns_none(self):
        fx = _provider()
        _skip_fetch(fx, {"USD": 0.79})
        assert fx.convert(100.0, "XYZ") is None

    def test_case_insensitive_currency_code(self):
        fx = _provider()
        _skip_fetch(fx, {"USD": 0.79})
        assert fx.convert(100.0, "usd") == fx.convert(100.0, "USD")

    def test_result_rounded_to_two_decimals(self):
        fx = _provider()
        _skip_fetch(fx, {"EUR": 0.8571})
        result = fx.convert(7.0, "EUR")
        assert result == round(7.0 * 0.8571, 2)

    def test_zero_amount_returns_zero(self):
        fx = _provider()
        _skip_fetch(fx, {"USD": 0.79})
        assert fx.convert(0.0, "USD") == 0.0

    def test_same_currency_no_fetch_needed(self):
        fx = _provider("GBP")
        # _fetched_at is -inf but same-currency short-circuits before fetch
        assert fx.convert(99.99, "GBP") == 99.99
