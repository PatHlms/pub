"""
Unit tests for FXProvider conversion logic and retry-storm guard.
"""
import pytest

from src.fx import FXProvider


def _provider(base: str = "GBP", rates: dict | None = None) -> FXProvider:
    """Build a pre-populated FXProvider without hitting the network."""
    cfg = {"base_currency": base, "provider": "frankfurter", "api_key_env_var": None}
    fx = FXProvider(cfg)
    fx._fetch_attempted = True          # skip network
    fx._rates = rates if rates is not None else {}
    return fx


class TestFXConvert:
    def test_same_currency_returns_rounded_amount(self):
        fx = _provider("GBP", {"GBP": 1.0})
        assert fx.convert(100.0, "GBP") == 100.0

    def test_known_rate_applied(self):
        # 1 USD = 0.79 GBP
        fx = _provider("GBP", {"USD": 0.79})
        assert fx.convert(100.0, "USD") == 79.0

    def test_rounding_to_two_decimals(self):
        fx = _provider("GBP", {"EUR": 0.8571428})
        result = fx.convert(7.0, "EUR")
        assert result == round(7.0 * 0.8571428, 2)

    def test_none_amount_returns_none(self):
        fx = _provider("GBP", {"USD": 0.79})
        assert fx.convert(None, "USD") is None

    def test_unknown_currency_returns_none(self):
        fx = _provider("GBP", {"USD": 0.79})
        assert fx.convert(50.0, "JPY") is None

    def test_case_insensitive_currency(self):
        fx = _provider("GBP", {"USD": 0.79})
        assert fx.convert(100.0, "usd") == 79.0


class TestFXRetryStorm:
    def test_failed_fetch_does_not_retry_on_convert(self, monkeypatch):
        """After a fetch failure _fetch() must not be re-called on every convert()."""
        cfg = {"base_currency": "GBP", "provider": "frankfurter", "api_key_env_var": None}
        fx = FXProvider(cfg)

        call_count = {"n": 0}

        def _fail():
            call_count["n"] += 1
            raise RuntimeError("network down")

        monkeypatch.setattr(fx, "_fetch_frankfurter", _fail)

        # First convert triggers _fetch(), which fails
        result1 = fx.convert(100.0, "USD")
        assert result1 is None
        assert call_count["n"] == 1

        # Subsequent converts must NOT re-trigger _fetch()
        fx.convert(200.0, "EUR")
        fx.convert(300.0, "USD")
        assert call_count["n"] == 1, "_fetch() was called more than once after a failure"


class TestFXFetchAttempted:
    def test_flag_set_on_success(self, monkeypatch):
        cfg = {"base_currency": "GBP", "provider": "frankfurter", "api_key_env_var": None}
        fx = FXProvider(cfg)
        monkeypatch.setattr(fx, "_fetch_frankfurter", lambda: fx._rates.update({"USD": 0.79}))
        fx.convert(1.0, "USD")
        assert fx._fetch_attempted is True

    def test_flag_set_on_failure(self, monkeypatch):
        cfg = {"base_currency": "GBP", "provider": "frankfurter", "api_key_env_var": None}
        fx = FXProvider(cfg)
        monkeypatch.setattr(fx, "_fetch_frankfurter", lambda: (_ for _ in ()).throw(RuntimeError))
        fx.convert(1.0, "USD")
        assert fx._fetch_attempted is True
