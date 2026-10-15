"""Keep entities and their history attached to the supply point (PPE).

PGE occasionally archives a billing account and continues the same supply
point under a new account number. Entity IDs are derived from the PPE, and
unique IDs are moved to the new account, so the recorder history continues
under unchanged entity IDs.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.util import slugify

from .accounts import account_ppes, describe_billing_account, find_successor
from .const import CONF_ACCOUNT_ID, DOMAIN
from .entity_ids import default_entity_id, entry_identifier, ppe_for_entry

_LOGGER = logging.getLogger(__name__)

CONF_PPE = "ppe"
# Marks entries whose existing entities were renamed to the PPE-based scheme.
CONF_ENTITY_SCHEME = "entity_id_scheme"
ENTITY_SCHEME_PPE = "ppe"


def entry_slug(data: dict[str, Any]) -> str:
    """Prefix of every unique ID of the entry (stable per login and account)."""
    username, account_id = data[CONF_USERNAME], data.get(CONF_ACCOUNT_ID)
    return slugify(f"{username}_{account_id}") if account_id is not None else slugify(username)


def _account(accounts: list[dict] | None, account_id: Any) -> dict | None:
    return next((acc for acc in accounts or [] if str(acc.get("id")) == str(account_id)), None)


@callback
def async_store_ppe(
    hass: HomeAssistant, entry: ConfigEntry, accounts: list[dict] | None, reported: str | None
) -> None:
    """Remember the entry's single PPE, so entity IDs no longer depend on PGE's answers."""
    if entry.data.get(CONF_PPE):
        return
    account = _account(accounts, entry.data.get(CONF_ACCOUNT_ID))
    ppe = ppe_for_entry(entry.data, entry.title, account_ppes(account) if account else ())
    ppe = ppe or (str(reported) if reported else None)
    if ppe:
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_PPE: ppe})


@callback
def async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename the entry's existing entities to sensor.pge_<ppe>_<sensor> once.

    The recorder moves states and long-term statistics along with a renamed
    entity ID. Later manual renames are respected because this runs only once.
    """
    if not entry.data.get(CONF_PPE) or entry.data.get(CONF_ENTITY_SCHEME) == ENTITY_SCHEME_PPE:
        return
    registry = er.async_get(hass)
    prefix = f"{entry_slug(entry.data)}_"
    identifier = entry_identifier(entry.data, entry.title)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.domain != "sensor" or not registered.unique_id.startswith(prefix):
            continue
        desired = default_entity_id(identifier, registered.unique_id.removeprefix(prefix))
        if registered.entity_id == desired:
            continue
        try:
            registry.async_update_entity(registered.entity_id, new_entity_id=desired)
        except ValueError:
            _LOGGER.warning("Not renaming %s: %s is already in use", registered.entity_id, desired)
        else:
            _LOGGER.info("Renamed %s to %s; history moves with it", registered.entity_id, desired)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_ENTITY_SCHEME: ENTITY_SCHEME_PPE})


def _issue_id(entry: ConfigEntry) -> str:
    return f"account_replaced_{entry.entry_id}"


def account_label(account: dict) -> str:
    return str(account.get("accountNumber") or account.get("id"))


@callback
def async_check_account_replacement(
    hass: HomeAssistant, entry: ConfigEntry, accounts: list[dict] | None
) -> None:
    """Raise a repair issue when another active account took over our PPE."""
    ppe, account_id = entry.data.get(CONF_PPE), entry.data.get(CONF_ACCOUNT_ID)
    if accounts is None or not ppe or account_id is None:
        return
    successor = find_successor(accounts, account_id, ppe)
    if successor is None:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return
    ir.async_create_issue(
        hass, DOMAIN, _issue_id(entry),
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="account_replaced",
        translation_placeholders={
            "title": entry.title,
            "ppe": ppe,
            "old_account": str(entry.data.get("account_number") or account_id),
            "new_account": account_label(successor),
        },
        data={"entry_id": entry.entry_id, "account_id": successor.get("id")},
    )


def conflicting_entry(hass: HomeAssistant, entry: ConfigEntry, account: dict) -> ConfigEntry | None:
    """Another entry already configured for the new account."""
    unique_id = f"{entry.data[CONF_USERNAME].lower()}_{account.get('id')}"
    return next((other for other in hass.config_entries.async_entries(DOMAIN)
                 if other.unique_id == unique_id and other.entry_id != entry.entry_id), None)


async def async_switch_account(hass: HomeAssistant, entry: ConfigEntry, account: dict) -> None:
    """Point the entry at the new account, keeping its entities and history."""
    old_prefix = entry_slug(entry.data)
    data = {**entry.data, CONF_ACCOUNT_ID: account["id"]}
    data.pop("account_number", None)
    if account.get("accountNumber"):
        data["account_number"] = str(account["accountNumber"])
    new_prefix = entry_slug(data)

    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id.startswith(f"{old_prefix}_"):
            registry.async_update_entity(
                registered.entity_id,
                new_unique_id=new_prefix + registered.unique_id.removeprefix(old_prefix))

    devices = dr.async_get(hass)
    if device := devices.async_get_device(identifiers={(DOMAIN, old_prefix)}):
        devices.async_update_device(device.id, new_identifiers={(DOMAIN, new_prefix)})

    hass.config_entries.async_update_entry(
        entry, data=data, title=describe_billing_account(account),
        unique_id=f"{entry.data[CONF_USERNAME].lower()}_{account['id']}")
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
    _LOGGER.info("%s now follows account %s", entry.title, account_label(account))
    await hass.config_entries.async_reload(entry.entry_id)
