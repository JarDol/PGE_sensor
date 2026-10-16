"""Interpret document snapshots without mixing payments, forecasts and energy."""
from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Any


def document_key(document: dict[str, Any]) -> tuple[str, str]:
    """Compare ISO dates, retaining API order for documents issued together."""
    return (str(document.get("creationDate") or ""), str(document.get("issueDate") or ""))


def latest_actual(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the latest measured settlement, excluding prepayment invoices."""
    actual = [doc for doc in documents if doc.get("documentType") == "INVOICE"
              and doc.get("ppmConsumptions")]
    return max(actual, key=lambda doc: (
        max(str(ppm.get("billingPeriodTo") or "") for ppm in doc["ppmConsumptions"]),
        document_key(doc),
    ), default=None)


def previous_actual(documents: list[dict[str, Any]], latest: dict[str, Any]) -> dict[str, Any] | None:
    """The measured settlement of the period that ended before ``latest`` began."""
    start = min(str(ppm.get("billingPeriodFrom") or "")[:10] for ppm in latest["ppmConsumptions"])
    earlier = [doc for doc in documents if doc.get("documentType") == "INVOICE" and doc.get("ppmConsumptions")
               and max(str(ppm.get("billingPeriodTo") or "")[:10] for ppm in doc["ppmConsumptions"]) < start]
    return latest_actual(earlier)


def latest_invoice(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Financial invoices remain valid when PGE omits energy details."""
    return max((doc for doc in documents if doc.get("documentType") == "INVOICE"),
               key=document_key, default=None)


def billing_period(ppm: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return a complete ISO period and its end date, or unknown values."""
    try:
        start = date.fromisoformat(str(ppm.get("billingPeriodFrom") or "")[:10])
        end = date.fromisoformat(str(ppm.get("billingPeriodTo") or "")[:10])
    except ValueError:
        return None, None
    if start > end:
        return None, None
    return f"{start.isoformat()} / {end.isoformat()}", end.isoformat()


def numeric(value: Any) -> float | None:
    """Reject malformed/non-finite data without turning unknown values into zero."""
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if isfinite(result) else None


def bank_zones(storage: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Convert the remaining raw energy to withdrawable energy once per zone."""
    result = {}
    zones = (storage or {}).get("zones") or {}
    for name in ("Strefa 1", "Strefa 2"):
        # A summary alias is a fallback, never an additional quantity to sum.
        zone = zones.get(name) or zones.get(f"{name} w sumie")
        if not zone:
            continue
        summary = zone.get("dataWarehouseSummary") or {}
        raw = numeric(summary.get("leftEnergyAmountSum"))
        factor = numeric(summary.get("factor"))
        if raw is None or factor is None or raw < 0 or not 0 < factor <= 1:
            continue
        result[name] = {"raw_kwh": raw, "factor": factor,
                        "available_kwh": raw * factor,
                        "history": zone.get("dataWarehousePpm") or []}
    return result


def bank_total(storage: dict[str, Any] | None) -> float | None:
    """Require every advertised tariff zone before reporting the total."""
    zones = bank_zones(storage)
    advertised = (storage or {}).get("zones") or {}
    expected = {name for name in ("Strefa 1", "Strefa 2")
                if name in advertised or f"{name} w sumie" in advertised}
    if not expected or set(zones) != expected:
        return None
    return sum(zone["available_kwh"] for zone in zones.values())
