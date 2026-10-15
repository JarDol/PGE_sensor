"""DataUpdateCoordinator for the PGE Sensor integration."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BalanceInfo, PgeScraper, PgeScraperError
from .const import DEFAULT_TIMEOUT

SCAN_INTERVAL = timedelta(hours=8)
RETRY_INTERVAL = timedelta(minutes=30)
_LOGGER = logging.getLogger(__name__)


class PgeEbokCoordinator(DataUpdateCoordinator[BalanceInfo]):
    """Coordinator responsible for fetching balance information."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        account_id: int | None = None,
    ) -> None:
        self._api = PgeScraper(username, password, timeout=DEFAULT_TIMEOUT)
        self._username = username
        self._account_id = account_id
        # Billing accounts as of the last refresh; None until PGE answers once.
        self.accounts: list[dict] | None = None
        name = f"PGE Sensor ({username})" if account_id is None else f"PGE Sensor ({username} / {account_id})"
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> BalanceInfo:
        try:
            data = await self.hass.async_add_executor_job(self._api.get_balance_details, self._account_id)
            self._ensure_interval(SCAN_INTERVAL)
        except PgeScraperError as err:
            self._ensure_interval(RETRY_INTERVAL)
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # pragma: no cover - defensive guard
            self._ensure_interval(RETRY_INTERVAL)
            raise UpdateFailed(f"Unexpected coordinator error: {err}") from err
        if self._account_id is not None:
            # Only used to notice PGE archiving this account; never fails the update.
            try:
                self.accounts = await self.hass.async_add_executor_job(self._api.get_billing_accounts)
            except (PgeScraperError, ValueError) as err:
                _LOGGER.debug("Billing account list unavailable: %s", err)
        return data

    @property
    def username(self) -> str:
        return self._username

    def _ensure_interval(self, interval: timedelta) -> None:
        if self.update_interval != interval:
            self.update_interval = interval
