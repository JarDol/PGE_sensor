"""PGE Sensor API using mobile endpoints (mBOK PGE)."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests

from .accounts import describe_billing_account, points_from_documents, account_sort_key

_LOGGER = logging.getLogger(__name__)


class PgeScraperError(RuntimeError):
    """Domain-specific exception raised by PgeScraper."""


@dataclass
class BalanceInfo:
    """Represents a single outstanding payment entry and latest invoice details."""

    amount: float
    due_date: Optional[date] = None
    invoice_number: Optional[str] = None
    issue_date: Optional[date] = None
    paid_date: Optional[date] = None
    payment_status: Optional[str] = None
    ppe: Optional[str] = None
    consumed_energy: Optional[float] = None
    feed_in_energy: float | None = None
    settled_energy: float | None = None
    energy_storage: dict | None = None
    invoice_amount: Optional[float] = None
    billing_period: Optional[str] = None
    current_payment: Optional[float] = None
    settlement_date: Optional[str] = None
    settlement_invoice: Optional[str] = None
    settlement_amount: Optional[float] = None
    forecast_energy: Optional[float] = None
    forecast_period: Optional[str] = None
    actual_invoice_amount: Optional[float] = None
    actual_invoice_number: Optional[str] = None
    actual_invoice_date: Optional[str] = None
    prosument: Optional[bool] = None


class PgeScraper:
    """Retrieves outstanding payment data from the mBOK PGE mobile API."""

    AUTH_URL = "https://mbok-services.gkpge.pl/authorization-service/api/auth/login"
    BILLING_ACCOUNTS_URL = "https://mbok-services.gkpge.pl/billing-service-v1/billingAccounts/filter"
    BASE_URL = "https://mbok-services.gkpge.pl"
    
    def __init__(self, username: str, password: str, *, timeout: int = 15) -> None:
        if not username or not password:
            raise ValueError("Username and password must be provided")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._session = requests.Session()
        # Mocking an Android app request
        self._session.headers.update({
            "User-Agent": "okhttp/4.9.2",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        self._access_token: Optional[str] = None
        self._device_id = str(uuid.uuid4())

    def get_billing_accounts(self) -> list[dict]:
        """Return every billing account (point of consumption) available for this user."""
        self._login()
        self._session.headers.update({"Authorization": f"Bearer {self._access_token}"})
        try:
            response = self._session.post(self.BILLING_ACCOUNTS_URL, json={}, timeout=self._timeout)
            response.raise_for_status()
            accounts = response.json().get("billingAccounts", [])
            for account in accounts:
                if not account.get("ppms") and account.get("id") is not None:
                    # Optional enrichment must not prevent account selection.
                    try:
                        documents = self._get_documents(account["id"])
                        account["ppms"] = points_from_documents(documents)
                    except (PgeScraperError, requests.RequestException, ValueError, TypeError):
                        _LOGGER.debug("Supply-point details unavailable for an account")
            return sorted(accounts, key=account_sort_key)
        except requests.RequestException as exc:
            raise PgeScraperError("Failed to fetch billing accounts") from exc

    def get_balance_details(self, account_id: Optional[int] = None) -> BalanceInfo:
        """Return the outstanding payment along with its due date.

        If ``account_id`` is not provided, the default (or first available)
        billing account is used, preserving the historical single-account behavior.
        """
        from .settlement import (
            billing_period as settlement_period, latest_actual, latest_invoice, numeric,
        )

        # Always perform a fresh login to ensure the access token is valid (it expires over time)
        self._login()

        # Update headers with auth token
        self._session.headers.update({"Authorization": f"Bearer {self._access_token}"})

        if account_id is None:
            account_id = self._get_billing_account_id()
        if not account_id:
            _LOGGER.warning("No billing accounts found for user %s", self._username)
            return BalanceInfo(amount=0.0)

        balance_data = self._get_balance(account_id)
        # Often totalAmount or requiredAmount stores the due value
        amount = balance_data.get("totalAmount", 0.0)

        # Get latest document/invoice to find due date
        documents = self._get_documents(account_id)
        
        # Filter for documents that actually need to be paid
        unpaid_docs = [
            doc for doc in documents 
            if (doc.get("amountToPay") or 0.0) > 0 or doc.get("paymentStatus") != "PAID"
        ]

        def parse_date(date_str: str) -> datetime:
            try:
                date_str = date_str.replace("T", " ")
                return datetime.strptime(date_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                return datetime.max

        due_date = None
        if unpaid_docs:
            unpaid_docs.sort(key=lambda d: parse_date(d.get("paymentDueDate", "9999-12-31 00:00:00")))
            due_date = parse_date(unpaid_docs[0].get("paymentDueDate", "9999-12-31 00:00:00")).date()

        target_doc = documents[0] if documents else None
        
        issue_date = None
        paid_date = None
        invoice_number = None
        payment_status = None
        ppe = None
        consumed_energy = None
        feed_in_energy = None
        settled_energy = None
        invoice_amount = None
        energy_storage = None
        billing_period = None
        current_payment = None

        if target_doc:
            invoice_number = target_doc.get("documentNumber")
            payment_status = target_doc.get("paymentStatus")
            invoice_amount = target_doc.get("totalAmount")
            document_id = target_doc.get("documentId")
            
            if target_doc.get("creationDate"):
                issue_date = parse_date(target_doc["creationDate"]).date()
            if target_doc.get("paidDate"):
                paid_date = parse_date(target_doc["paidDate"]).date()
                
            current_payment = target_doc.get("amountToPay")
            # Financial metadata remains attached to the payment document.
            # Energy and bank belong exclusively to the latest actual settlement.
            # If no unpaid doc, we can still provide a due date from the latest doc
            if not due_date and target_doc.get("paymentDueDate"):
                date_parsed = parse_date(target_doc["paymentDueDate"])
                if date_parsed != datetime.max:
                    due_date = date_parsed.date()

        actual = latest_actual(documents)
        # A standard consumer's INVOICE may have no ppmConsumptions at all.
        # Its financial amount is still valid; do not require energy details.
        actual_invoice = latest_invoice(documents)
        settlement_date = settlement_invoice = settlement_amount = None
        forecast_energy = forecast_period = None
        if target_doc and target_doc.get("documentType") == "PREPAYMENT_INVOICE":
            forecasts = target_doc.get("ppmConsumptions") or []
            if len(forecasts) == 1:
                forecast_energy = numeric(forecasts[0].get("consumptionValue"))
                forecast_period, _ = settlement_period(forecasts[0])
        # Multiple PPE require explicit aggregation/selection. Do not present
        # the first point alone as the entire account's energy or bank.
        if actual and len(actual["ppmConsumptions"]) == 1:
            ppm = actual["ppmConsumptions"][0]
            consumed_energy = numeric(ppm.get("consumptionValue"))
            feed_in_energy = numeric(ppm.get("feedInValue"))
            # API valueSettledEnergyConsumed is a monetary value, NOT kWh.
            settled_energy = None
            settlement_amount = numeric(ppm.get("valueSettledEnergyConsumed"))
            settlement_invoice = actual.get("documentNumber")
            billing_period, settlement_date = settlement_period(ppm)
            ppe = ppm.get("ppmNumber")
            document_id = actual.get("documentId")
            ppm_id = (ppm.get("ppm") or {}).get("id")
            if actual.get("prosument") is True and document_id and ppm_id:
                url = f"{self.BASE_URL}/mbok-service-v1/billingAccountsDocument/{document_id}/datawarehouse/{ppm_id}"
                try:
                    response = self._session.get(url, timeout=self._timeout)
                    response.raise_for_status()
                    payload = response.json()
                    energy_storage = payload if isinstance(payload, dict) else None
                except (requests.RequestException, ValueError):
                    _LOGGER.warning("Unable to retrieve settlement bank; leaving it unknown")

        return BalanceInfo(
            amount=amount,
            due_date=due_date,
            invoice_number=invoice_number,
            issue_date=issue_date,
            paid_date=paid_date,
            payment_status=payment_status,
            ppe=ppe,
            consumed_energy=consumed_energy,
            feed_in_energy=feed_in_energy,
            settled_energy=settled_energy,
            invoice_amount=invoice_amount,
            energy_storage=energy_storage,
            billing_period=billing_period,
            current_payment=current_payment,
            settlement_date=settlement_date, settlement_invoice=settlement_invoice,
            settlement_amount=settlement_amount, forecast_energy=forecast_energy,
            forecast_period=forecast_period,
            actual_invoice_amount=numeric(actual_invoice.get("totalAmount")) if actual_invoice else None,
            actual_invoice_number=actual_invoice.get("documentNumber") if actual_invoice else None,
            actual_invoice_date=str(actual_invoice.get("creationDate") or "")[:10] or None if actual_invoice else None,
            prosument=(target_doc.get("prosument") if target_doc and isinstance(target_doc.get("prosument"), bool)
                       else actual_invoice.get("prosument") if actual_invoice else None)
        )

    def _login(self) -> None:
        payload = {
            "email": self._username,
            "password": self._password,
            "deviceId": self._device_id,
            "deviceName": "Home Assistant",
            "platform": "Android"
        }
        # Remove old expired token if it exists in the session headers
        self._session.headers.pop("Authorization", None)
        try:
            response = self._session.post(
                self.AUTH_URL,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            if "accessToken" not in data:
                raise PgeScraperError("Login response missing accessToken")
            self._access_token = data["accessToken"]
        except requests.RequestException as exc:
            _LOGGER.debug("Login failed: %s", exc)
            if exc.response is not None and exc.response.status_code in (401, 403):
                raise PgeScraperError("Login failed: incorrect credentials") from exc
            raise PgeScraperError("Login request failed") from exc

    def _get_billing_account_id(self) -> Optional[int]:
        try:
            # First try to get the default account
            response = self._session.post(
                self.BILLING_ACCOUNTS_URL,
                json={"defaultAccount": True},
                timeout=self._timeout
            )
            response.raise_for_status()
            accounts = response.json().get("billingAccounts", [])
            
            if not accounts:
                # Fallback to any account if default is not set
                response = self._session.post(
                    self.BILLING_ACCOUNTS_URL,
                    json={},
                    timeout=self._timeout
                )
                response.raise_for_status()
                accounts = response.json().get("billingAccounts", [])

            if accounts:
                return accounts[0].get("id")
        except requests.RequestException as exc:
            raise PgeScraperError("Failed to fetch billing accounts") from exc
            
        return None

    def _get_balance(self, account_id: int) -> dict:
        url = f"https://mbok-services.gkpge.pl/billing-service-v1/billingAccounts/{account_id}/balance"
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise PgeScraperError(f"Failed to fetch balance for account {account_id}") from exc

    def _get_documents(self, account_id: int) -> list[dict]:
        url = f"https://mbok-services.gkpge.pl/mbok-service-v1/billingAccounts/{account_id}/documents/filter?pageNo=0&pageSize=100"
        try:
            response = self._session.post(url, json={}, timeout=self._timeout)
            response.raise_for_status()
            return response.json().get("documents", [])
        except requests.RequestException as exc:
            _LOGGER.warning("Failed to fetch documents: %s", exc)
            return []
