"""Config flow for the PGE Sensor integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .accounts import account_ppes
from .api import PgeScraper, PgeScraperError, describe_billing_account
from .const import (
    CONF_ACCOUNT_ID, CONF_METER_EXPORT, CONF_METER_IMPORT, CONF_OPUST_FACTOR, CONF_PRECISION, DOMAIN,
)
from .local_bank import DEFAULT_STEP
from .migration import CONF_ENTITY_SCHEME, CONF_PPE, ENTITY_SCHEME_PPE

ALL_POINTS_KEY = "__all__"
METER_KEYS = (CONF_METER_IMPORT, CONF_METER_EXPORT)
PRECISIONS = ("0.01", "0.1", "0.5", "1")


def _meters_schema(current: dict[str, Any]) -> vol.Schema:
    """Optional meter pickers; suggested values keep the fields clearable."""
    selector = EntitySelector(
        EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.ENERGY)
    )
    schema: dict[Any, Any] = {
        vol.Optional(key, description={"suggested_value": current.get(key)}): selector
        for key in METER_KEYS
    }
    precision = f"{float(current.get(CONF_PRECISION, DEFAULT_STEP)):g}"
    schema[vol.Required(CONF_PRECISION, default=precision if precision in PRECISIONS else "0.1")] = (
        SelectSelector(SelectSelectorConfig(
            options=list(PRECISIONS), mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_PRECISION)))
    # Empty means: use the factor reported by PGE, or 0.8 when PGE has none.
    schema[vol.Optional(CONF_OPUST_FACTOR, description={"suggested_value": current.get(CONF_OPUST_FACTOR)})] = (
        NumberSelector(NumberSelectorConfig(min=0.1, max=1, step=0.01, mode=NumberSelectorMode.BOX)))
    return vol.Schema(schema)


def _meters_error(user_input: dict[str, Any]) -> str | None:
    """The bank projection needs both cumulative meters, or neither."""
    imported, exported = (user_input.get(key) for key in METER_KEYS)
    if bool(imported) != bool(exported):
        return "meters_incomplete"
    if imported and imported == exported:
        return "meters_identical"
    return None


def _meters_options(user_input: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {key: user_input[key] for key in METER_KEYS if user_input.get(key)}
    options[CONF_PRECISION] = float(user_input.get(CONF_PRECISION, DEFAULT_STEP))
    if user_input.get(CONF_OPUST_FACTOR) is not None:
        options[CONF_OPUST_FACTOR] = float(user_input[CONF_OPUST_FACTOR])
    return options


def _point_data(account: dict) -> dict[str, str]:
    """New entries start with PPE-based entity IDs; nothing to migrate later."""
    ppes = account_ppes(account)
    return {CONF_PPE: ppes[0], CONF_ENTITY_SCHEME: ENTITY_SCHEME_PPE} if len(ppes) == 1 else {}


async def _async_fetch_accounts(hass: HomeAssistant, data: dict[str, str]) -> list[dict]:
    def _fetch() -> list[dict]:
        scraper = PgeScraper(data[CONF_USERNAME], data[CONF_PASSWORD])
        return scraper.get_billing_accounts()

    return await hass.async_add_executor_job(_fetch)


class PgeEbokConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PGE Sensor."""

    VERSION = 1

    def __init__(self) -> None:
        self._username: str | None = None
        self._password: str | None = None
        self._accounts: list[dict] = []
        self._available: list[dict] = []
        self._entry_title: str | None = None
        self._entry_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return PgeOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME]
            try:
                accounts = await _async_fetch_accounts(self.hass, user_input)
            except PgeScraperError as exc:
                if "incorrect credentials" in str(exc):
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                self._username = username
                self._password = user_input[CONF_PASSWORD]
                self._accounts = accounts

                existing_ids = {
                    entry.data.get(CONF_ACCOUNT_ID)
                    for entry in self._async_current_entries()
                    if entry.data[CONF_USERNAME].lower() == username.lower()
                }
                self._available = [acc for acc in accounts if acc.get("id") not in existing_ids]

                if not accounts:
                    # No billing accounts reported at all; fall back to a single
                    # entry without an account id (legacy single-account behavior).
                    return await self._async_finish({})
                if not self._available:
                    return self.async_abort(reason="already_configured")
                if len(self._available) == 1:
                    return await self._async_finish(self._available[0])
                return await self.async_step_select_point()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    async def async_step_select_point(self, user_input: dict[str, str] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        options = {ALL_POINTS_KEY: f"Wszystkie konta rozliczeniowe ({len(self._available)})"}
        options.update({str(acc["id"]): describe_billing_account(acc) for acc in self._available})

        if user_input is not None:
            choice = user_input["point"]
            if choice == ALL_POINTS_KEY:
                first, *rest = self._available
                for acc in rest:
                    self.hass.async_create_task(
                        self.hass.config_entries.flow.async_init(
                            DOMAIN,
                            context={"source": config_entries.SOURCE_IMPORT},
                            data={
                                CONF_USERNAME: self._username,
                                CONF_PASSWORD: self._password,
                                CONF_ACCOUNT_ID: acc["id"],
                                "label": describe_billing_account(acc),
                                "account_number": acc.get("accountNumber"),
                                **_point_data(acc),
                            },
                        )
                    )
                return await self._async_finish(first)

            chosen = next((acc for acc in self._available if str(acc["id"]) == choice), None)
            if chosen is None:
                errors["base"] = "unknown"
            else:
                return await self._async_finish(chosen)

        data_schema = vol.Schema({vol.Required("point", default=ALL_POINTS_KEY): vol.In(options)})
        return self.async_show_form(step_id="select_point", data_schema=data_schema, errors=errors)

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Create an entry queued by the "all points" selection, without further prompts."""
        username = import_data[CONF_USERNAME]
        account_id = import_data[CONF_ACCOUNT_ID]

        await self.async_set_unique_id(f"{username.lower()}_{account_id}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=import_data.get("label") or f"{username} ({account_id})",
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: import_data[CONF_PASSWORD],
                CONF_ACCOUNT_ID: account_id,
                "account_number": import_data.get("account_number"),
                **{key: import_data[key] for key in (CONF_PPE, CONF_ENTITY_SCHEME) if key in import_data},
            },
        )

    async def _async_finish(self, account: dict) -> FlowResult:
        account_id = account.get("id")
        unique_id = f"{self._username.lower()}_{account_id}" if account_id is not None else self._username.lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        data: dict[str, Any] = {CONF_USERNAME: self._username, CONF_PASSWORD: self._password}
        if account_id is not None:
            data[CONF_ACCOUNT_ID] = account_id
            if account.get("accountNumber"):
                data["account_number"] = str(account["accountNumber"])
            data.update(_point_data(account))

        self._entry_title = describe_billing_account(account) if account else self._username
        self._entry_data = data
        return await self.async_step_meters()

    async def async_step_meters(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Optionally pick the local meters used to project the energy bank."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _meters_error(user_input):
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._entry_title,
                    data=self._entry_data,
                    options=_meters_options(user_input),
                )
        return self.async_show_form(
            step_id="meters",
            data_schema=_meters_schema(user_input or {}),
            errors=errors,
            description_placeholders={"account": self._entry_title or ""},
        )


class PgeOptionsFlow(config_entries.OptionsFlow):
    """Change the meters without re-adding the account."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        # Not assigned to self.config_entry: setting it is deprecated in newer HA.
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := _meters_error(user_input):
                errors["base"] = error
            else:
                return self.async_create_entry(title="", data=_meters_options(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=_meters_schema(user_input or self._entry.options),
            errors=errors,
        )
