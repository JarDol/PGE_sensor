"""Keep default entity IDs independent of descriptive account/device titles."""
from __future__ import annotations

import re
from typing import Any

SENSOR_KEYS = {
    "balance": "saldo",
    "invoice_amount": "kwota_faktury",
    "consumed_energy": "energia_pobrana",
    "feed_in_energy": "energia_wprowadzona",
    "settled_energy": "zuzycie_po_rozliczeniu",
    "energy_storage": "magazyn_energii",
    "billing_period": "okres_rozliczeniowy",
    "current_payment": "biezaca_platnosc",
    "due_date": "termin_platnosci",
}


def account_number_for_entry(data: dict[str, Any], title: str) -> str | None:
    """Prefer stored billing number; support existing entries without migration."""
    stored = str(data.get("account_number") or "")
    if stored.isdecimal():
        return stored
    # Older entries stored the billing number only in their title.
    match = re.search(r"\|\s*konto\s+(\d+)(?:\s*\||\s*$)", title)
    if match:
        return match.group(1)
    if title.isdecimal() and data.get("account_id") is not None:
        return title
    internal = str(data.get("account_id") or "")
    return internal if internal.isdecimal() else None


def default_entity_id(
    account_number: str | None, key: str, *, multiple_accounts: bool = True
) -> str:
    """Suggest IDs; HA's entity registry retains existing/manual entity IDs."""
    suffix = SENSOR_KEYS.get(key, key)
    prefix = f"pge_{account_number}" if multiple_accounts and account_number else "pge"
    return f"sensor.{prefix}_{suffix}"
