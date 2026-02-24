import logging
import os
from typing import Optional

import requests

log = logging.getLogger(__name__)

_TIMEOUT = 10  # seconds per HTTP request


class FXProvider:
    """
    Fetches live exchange rates and converts prices to a common base currency.

    Rates are fetched once per FXProvider instance (once per batch) and cached
    in memory. Internally stores rates as "units of base currency per 1 source
    currency" so conversion is always: base_amount = source_amount * rate.

    Supported providers
    -------------------
    frankfurter (default)
        Free, no API key. Wraps ECB daily rates.
        https://www.frankfurter.app — supports any base currency.

    openexchangerates
        Free tier available (requires API key). Free tier base is USD only;
        cross-rates to the configured base_currency are computed automatically.
        Set api_key_env_var to the env var holding your App ID.
        https://openexchangerates.org

    fixer
        Free tier available (requires API key). Note: free tier fixes base to
        EUR; a paid plan is required for non-EUR base currencies.
        Set api_key_env_var to the env var holding your Access Key.
        https://fixer.io

    Configuration (in settings.json)
    ---------------------------------
    {
      "fx": {
        "enabled": true,
        "base_currency": "GBP",
        "provider": "frankfurter",
        "api_key_env_var": null
      }
    }
    """

    def __init__(self, config: dict) -> None:
        self.base_currency: str   = config.get("base_currency", "GBP").upper()
        self._provider: str       = config.get("provider", "frankfurter").lower()
        key_env: Optional[str]    = config.get("api_key_env_var") or None
        self._api_key: Optional[str] = os.environ.get(key_env) if key_env else None
        # _rates[CCY] = units of base_currency per 1 unit of CCY
        self._rates: dict[str, float] = {}

    def convert(self, amount: Optional[float], from_currency: str) -> Optional[float]:
        """
        Convert amount from from_currency to base_currency.

        Returns None if amount is None, from_currency is unknown, or rates
        could not be fetched. Logs a warning for unknown currencies.
        """
        if amount is None:
            return None
        from_currency = from_currency.upper()
        if from_currency == self.base_currency:
            return round(amount, 2)

        if not self._rates:
            self._fetch()

        rate = self._rates.get(from_currency)
        if rate is None:
            log.warning("No FX rate available for %s → %s", from_currency, self.base_currency)
            return None

        return round(amount * rate, 2)

    # ------------------------------------------------------------------
    # Fetch dispatch
    # ------------------------------------------------------------------

    def _fetch(self) -> None:
        try:
            if self._provider == "frankfurter":
                self._fetch_frankfurter()
            elif self._provider == "openexchangerates":
                self._fetch_openexchangerates()
            elif self._provider == "fixer":
                self._fetch_fixer()
            else:
                raise ValueError(f"Unknown FX provider: {self._provider!r}")
            # Always ensure base → base is 1.0
            self._rates[self.base_currency] = 1.0
            log.info(
                "FX rates loaded from %s (base=%s, %d currencies)",
                self._provider, self.base_currency, len(self._rates),
            )
        except Exception as exc:
            log.error("Failed to fetch FX rates from %s: %s", self._provider, exc)
            # Leave _rates empty; convert() will return None for all non-base currencies

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _fetch_frankfurter(self) -> None:
        """
        GET https://api.frankfurter.app/latest?from=GBP
        Response: {"base": "GBP", "rates": {"EUR": 1.17, "USD": 1.27, ...}}
        rates[CCY] = units of CCY per 1 GBP → invert to get GBP per 1 CCY.
        """
        resp = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": self.base_currency},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        self._rates = {
            k.upper(): 1.0 / v
            for k, v in data["rates"].items()
            if v
        }

    def _fetch_openexchangerates(self) -> None:
        """
        GET https://openexchangerates.org/api/latest.json?app_id=KEY&base=USD
        Free tier is USD-base only. Cross-rates to base_currency are derived:
          base per 1 CCY = (base per 1 USD) / (CCY per 1 USD)
                         = usd_rates[base_currency] / usd_rates[CCY]
        """
        resp = requests.get(
            "https://openexchangerates.org/api/latest.json",
            params={"app_id": self._api_key, "base": "USD"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        usd_rates: dict[str, float] = resp.json()["rates"]  # CCY per 1 USD
        base_per_usd = usd_rates.get(self.base_currency, 1.0)
        self._rates = {
            k.upper(): base_per_usd / v
            for k, v in usd_rates.items()
            if v
        }

    def _fetch_fixer(self) -> None:
        """
        GET https://data.fixer.io/api/latest?access_key=KEY&base=GBP
        Response: {"success": true, "base": "GBP", "rates": {"EUR": 1.17, ...}}
        Note: non-EUR base requires a paid Fixer plan.
        rates[CCY] = units of CCY per 1 GBP → invert to get GBP per 1 CCY.
        """
        resp = requests.get(
            "https://data.fixer.io/api/latest",
            params={"access_key": self._api_key, "base": self.base_currency},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            info = data.get("error", {}).get("info", "unknown error")
            raise ValueError(f"Fixer API error: {info}")
        self._rates = {
            k.upper(): 1.0 / v
            for k, v in data["rates"].items()
            if v
        }
