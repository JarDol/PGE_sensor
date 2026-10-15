"""Home Assistant integration for PGE Sensor."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ACCOUNT_ID, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import PgeEbokCoordinator
from .migration import async_check_account_replacement, async_migrate_entity_ids, async_store_ppe

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup(_hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up the integration via YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = PgeEbokCoordinator(
        hass,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_ACCOUNT_ID),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    data = coordinator.data
    async_store_ppe(hass, entry, coordinator.accounts, data.ppe if data else None)
    async_migrate_entity_ids(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def _check_account() -> None:
        async_check_account_replacement(hass, entry, coordinator.accounts)

    _check_account()
    entry.async_on_unload(coordinator.async_add_listener(_check_account))

    options = dict(entry.options)

    async def _async_reload_on_new_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Changing the meters adds or removes the projected bank sensor."""
        if dict(entry.options) != options:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_reload_on_new_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
