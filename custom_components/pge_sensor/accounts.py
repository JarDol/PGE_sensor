"""Build account labels from supply-point data, not mailing addresses."""
from __future__ import annotations

from typing import Any


def point_address(point: dict[str, Any]) -> str:
    """Read an explicit point address or format its structured fields."""
    direct = point.get("address")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    building = str(point.get("buildingNumber") or "").strip()
    flat = str(point.get("flatNumber") or "").strip()
    if flat:
        building += f"/{flat}"
    street = " ".join(filter(None, [str(point.get("street") or "").strip(), building]))
    locality = " ".join(
        filter(
            None,
            [
                str(point.get("postcode") or point.get("zipCode") or "").strip(),
                str(point.get("city") or "").strip(),
            ],
        )
    )
    return " ".join(filter(None, [street, locality]))


def points_from_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recover missing points from documents, deduplicating by PPE number."""
    points: dict[str, dict[str, Any]] = {}
    for document in documents:
        for item in document.get("ppmConsumptions") or []:
            detail = item.get("ppm") or {}
            number = item.get("ppmNumber") or detail.get("ppmNumber")
            address = point_address(detail)
            if number and address:
                points.setdefault(
                    str(number),
                    {"number": str(number), "address": address, "medium": item.get("medium")},
                )
    return list(points.values())


def describe_billing_account(account: dict[str, Any]) -> str:
    """Distinguish accounts sharing a supply point without changing their IDs."""
    points = []
    for point in account.get("ppms") or []:
        address = point_address(point) or "Adres PPE niedostępny"
        number = point.get("number") or point.get("ppmNumber")
        points.append(f"{address} — PPE {number}" if number else address)

    label = " / ".join(dict.fromkeys(points)) if points else "Punkt PPE nieopisany przez PGE"
    if not points:
        # Preserve older API descriptions without treating an account address
        # as a verified address of the supply point.
        for key in ("premiseAddress", "address", "shortName", "name"):
            value = account.get(key)
            if isinstance(value, str) and value.strip():
                label += f" — opis konta: {value.strip()}"
                break
        if account.get("ppeNumber"):
            label += f" — PPE {account['ppeNumber']}"

    number = account.get("accountNumber") or account.get("consumerNumber")
    number = number or account.get("number") or account.get("id")
    if number is not None:
        label += f" | konto {number}"
    if account.get("archived"):
        label += " | ARCHIWALNE"
    if account.get("defaultAccount"):
        label += " | domyślne"
    if account.get("prosument"):
        label += " | prosument"
    return label


def account_sort_key(account: dict[str, Any]) -> tuple[bool, bool, str]:
    """Keep active/default accounts ahead of archived accounts."""
    return (
        bool(account.get("archived")),
        not bool(account.get("defaultAccount")),
        describe_billing_account(account).casefold(),
    )
