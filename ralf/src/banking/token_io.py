"""
Token.io Open Banking adapter — Payment Initiation Service (PIS).

Auth:   OAuth 2.0 client credentials → Bearer access token.
API:    Token.io REST API v1.

Required env vars
-----------------
  TOKEN_IO_CLIENT_ID       — OAuth client ID (from Token.io developer console)
  TOKEN_IO_CLIENT_SECRET   — OAuth client secret
  TOKEN_IO_MEMBER_ID       — Token.io member ID (your TPP identity)

Optional env vars
-----------------
  TOKEN_IO_SANDBOX         — "true" to use sandbox endpoints (default: false)

Destination account config (in settings.json banking.destination)
-----------------------------------------------------------------
  sort_code        — UK sort code, e.g. "20-00-00"
  account_number   — UK account number, e.g. "55779911"
  account_name     — Beneficiary name shown on statement

Payment lifecycle
-----------------
  initiate_payment()  →  creates a payment request, returns payment_id
  get_payment_status() →  polls /payments/{id}, returns normalised status dict

Token.io status mapping
-----------------------
  PENDING_EXTERNAL_AUTHORIZATION  → "pending"
  PENDING_CLEARING                → "processing"
  COMPLETED                       → "completed"
  FAILED                          → "failed"
  CANCELLED                       → "failed"
"""

import logging
import os
import time
from typing import Any

import requests

from src.banking.base import BaseBankingProvider

log = logging.getLogger(__name__)

_PROD_BASE    = "https://api.token.io/v1"
_SANDBOX_BASE = "https://api.sandbox.token.io/v1"
_PROD_AUTH    = "https://auth.token.io/oauth2/token"
_SANDBOX_AUTH = "https://auth.sandbox.token.io/oauth2/token"

_STATUS_MAP = {
    "PENDING_EXTERNAL_AUTHORIZATION": "pending",
    "PENDING_CLEARING":               "processing",
    "COMPLETED":                      "completed",
    "FAILED":                         "failed",
    "CANCELLED":                      "failed",
    "REJECTED":                       "failed",
}


class TokenIoProvider(BaseBankingProvider):

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._client_id     = os.environ["TOKEN_IO_CLIENT_ID"]
        self._client_secret = os.environ["TOKEN_IO_CLIENT_SECRET"]
        self._member_id     = os.environ["TOKEN_IO_MEMBER_ID"]
        sandbox             = os.environ.get("TOKEN_IO_SANDBOX", "false").lower() == "true"
        self._base_url      = _SANDBOX_BASE if sandbox else _PROD_BASE
        self._auth_url      = _SANDBOX_AUTH if sandbox else _PROD_AUTH
        self._destination   = config.get("destination", {})
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._session = requests.Session()
        log.info(
            "[token.io] initialised — sandbox=%s member=%s destination_account=%s",
            sandbox, self._member_id,
            self._destination.get("account_number", "(not set)"),
        )

    # ------------------------------------------------------------------
    # BaseBankingProvider interface
    # ------------------------------------------------------------------

    def initiate_payment(
        self,
        amount: float,
        currency: str,
        destination: dict[str, str],
        reference: str,
    ) -> str:
        """
        Create a domestic payment request via Token.io PIS.

        The destination dict must include:
            sort_code        e.g. "20-00-00"
            account_number   e.g. "55779911"
            account_name     e.g. "Betfair Exchange"

        If destination is empty, falls back to config banking.destination.
        """
        dest = destination or self._destination
        if not dest.get("sort_code") or not dest.get("account_number"):
            raise ValueError(
                "initiate_payment: destination must include sort_code and account_number"
            )

        payload = {
            "requestPayload": {
                "description":       reference,
                "callbackState":     "ralf",
                "from": {
                    "memberId": self._member_id,
                },
                "transfer": {
                    "redeemer": {
                        "memberId": self._member_id,
                    },
                    "instructions": {
                        "transferDestinations": [
                            {
                                "domesticWire": {
                                    "accountNumber": dest["account_number"],
                                    "sortCode":      dest["sort_code"].replace("-", ""),
                                    "bankCode":      dest.get("sort_code", "").replace("-", ""),
                                    "country":       "GB",
                                    "type":          "SORT_CODE",
                                },
                                "customerData": {
                                    "legalNames": [dest.get("account_name", "Exchange Account")],
                                },
                            }
                        ],
                        "source": {
                            "account": {
                                "sepa": {
                                    "iban": dest.get("source_iban", ""),
                                }
                            }
                        },
                    },
                    "amount":   f"{amount:.2f}",
                    "currency": currency,
                },
            }
        }

        resp = self._post("/tokens", payload)
        token_id = resp.get("token", {}).get("id", "")
        if not token_id:
            raise RuntimeError(f"Token.io /tokens returned no token id: {resp}")

        # Redeem the token immediately (TPP-initiated, no user redirect required
        # when the TPP holds SCA credentials on behalf of the payer)
        redeem_payload = {"state": "ralf-redeem"}
        redeem_resp = self._post(f"/tokens/{token_id}/transfer", redeem_payload)
        transfer_id  = redeem_resp.get("transfer", {}).get("id", token_id)

        log.info(
            "[token.io] payment initiated: transfer_id=%s amount=%.2f %s → %s %s",
            transfer_id, amount, currency,
            dest.get("account_name", "exchange"),
            dest.get("account_number", ""),
        )
        return transfer_id

    def get_payment_status(self, payment_id: str) -> dict[str, Any]:
        resp      = self._get(f"/transfers/{payment_id}")
        transfer  = resp.get("transfer", {})
        raw_status = transfer.get("status", "PENDING_EXTERNAL_AUTHORIZATION")
        return {
            "payment_id": payment_id,
            "status":     _STATUS_MAP.get(raw_status, "pending"),
            "amount":     float(transfer.get("payload", {}).get("amount", 0)),
            "currency":   transfer.get("payload", {}).get("currency", "GBP"),
            "raw_status": raw_status,
        }

    # ------------------------------------------------------------------
    # Internal — auth + HTTP helpers
    # ------------------------------------------------------------------

    def _ensure_token(self) -> None:
        if self._access_token and time.time() < self._token_expiry - 30:
            return
        resp = requests.post(
            self._auth_url,
            data={
                "grant_type":    "client_credentials",
                "client_id":     self._client_id,
                "client_secret": self._client_secret,
                "scope":         "payments",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        log.debug("[token.io] access token refreshed (expires in %ds)", data.get("expires_in", 3600))

    def _headers(self) -> dict[str, str]:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def _get(self, path: str) -> dict:
        resp = self._session.get(
            f"{self._base_url}{path}", headers=self._headers(), timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict) -> dict:
        resp = self._session.post(
            f"{self._base_url}{path}",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
