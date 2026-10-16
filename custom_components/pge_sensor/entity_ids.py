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
    "meter_bank": "magazyn_biezacy",
    "meter_deficit": "zuzycie_do_zaplaty_biezace",
    "meter_deficit_previous": "zuzycie_do_zaplaty_poprzedni_okres",
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


def ppe_for_entry(
    data: dict[str, Any], title: str, candidates: list[str] | tuple[str, ...] = ()
) -> str | None:
    """The supply point outlives billing accounts, so it anchors entity IDs.

    Prefer the stored PPE, then the single PPE named in the account title,
    then the single PPE reported by PGE. Accounts covering several points
    have no single PPE.
    """
    stored = str(data.get("ppe") or "")
    if stored:
        return stored
    for found in (re.findall(r"PPE\s+([0-9A-Za-z]+)", title), candidates):
        unique = set(map(str, filter(None, found)))
        if len(unique) == 1:
            return unique.pop()
    return None


def entry_identifier(data: dict[str, Any], title: str) -> str | None:
    return ppe_for_entry(data, title) or account_number_for_entry(data, title)


def default_entity_id(identifier: str | None, key: str) -> str:
    """Suggest IDs; HA's entity registry retains existing/manual entity IDs."""
    suffix = SENSOR_KEYS.get(key, key)
    token = re.sub(r"[^0-9a-z]+", "_", str(identifier or "").lower()).strip("_")
    return f"sensor.pge_{token}_{suffix}" if token else f"sensor.pge_{suffix}"
