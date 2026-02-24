from abc import ABC, abstractmethod
from typing import Any


class BaseBankingProvider(ABC):
    """
    Abstract interface for Open Banking Payment Initiation Service providers.

    Concrete implementations connect to a specific aggregator or bank API
    (e.g. Token.io) to initiate GBP transfers from a source bank account
    to a destination account (typically an exchange funding account).

    Only PIS (Payment Initiation) is in scope — balance reads (AIS) are not
    implemented here; available funds are tracked internally by FundsManager.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    @abstractmethod
    def initiate_payment(
        self,
        amount: float,
        currency: str,
        destination: dict[str, str],
        reference: str,
    ) -> str:
        """
        Initiate a payment from the configured source account.

        Parameters
        ----------
        amount      : transfer amount (e.g. 500.0)
        currency    : ISO 4217 code (e.g. "GBP")
        destination : bank account dict — keys depend on implementation:
                        sort_code, account_number, name   (UK domestic)
                        iban, bic, name                   (SEPA / international)
        reference   : payment reference string shown on both statements

        Returns
        -------
        str  — provider-assigned payment / transfer ID for status polling
        """

    @abstractmethod
    def get_payment_status(self, payment_id: str) -> dict[str, Any]:
        """
        Poll the status of a previously initiated payment.

        Returns a dict with at minimum:
            payment_id : str
            status     : str  — "pending" | "processing" | "completed" | "failed"
            amount     : float
            currency   : str
        """
