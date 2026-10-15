"""Repair flow: move an entry to the account that replaced its archived one."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .migration import CONF_PPE, account_label, async_switch_account, conflicting_entry


class AccountReplacedRepairFlow(RepairsFlow):
    def __init__(self, data: dict[str, Any]) -> None:
        self._entry_id = data["entry_id"]
        self._account_id = data["account_id"]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        coordinator = self.hass.data.get(DOMAIN, {}).get(self._entry_id)
        if entry is None or coordinator is None:
            return self.async_abort(reason="entry_not_loaded")
        account = next((acc for acc in coordinator.accounts or []
                        if str(acc.get("id")) == str(self._account_id)), None)
        if account is None:
            return self.async_abort(reason="account_unavailable")
        if other := conflicting_entry(self.hass, entry, account):
            return self.async_abort(reason="new_account_configured",
                                    description_placeholders={"other": other.title})

        if user_input is not None:
            await async_switch_account(self.hass, entry, account)
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "title": entry.title,
                "ppe": entry.data.get(CONF_PPE, ""),
                "old_account": str(entry.data.get("account_number") or entry.data.get("account_id")),
                "new_account": account_label(account),
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    return AccountReplacedRepairFlow(data or {})
