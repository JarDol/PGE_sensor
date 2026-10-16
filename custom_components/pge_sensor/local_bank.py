"""Project the PGE energy bank forward from local meter readings.

PGE reports the bank only as of the last actual settlement. Starting from the
batches left after that settlement, every month of local meter readings adds
a new batch (exported energy × opust factor), consumption draws batches FIFO,
and batches older than 12 months expire. The bank never goes below zero:
consumption it cannot cover is a deficit (energy to pay for) that later
exports repay first.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import Any

EXPIRY_MONTHS = 12
DEFAULT_FACTOR = 0.8
DEFAULT_STEP = 0.1
_DUST_KWH = 0.0005


def month_index(day: date) -> int:
    return day.year * 12 + day.month - 1


def _month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def quantize(value: float, step: float) -> float:
    """Round to a multiple of ``step``, e.g. 0.5 kWh: 12.74 -> 12.5."""
    return round(round(value / step) * step, 6)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if isfinite(result) else None


def projection_start(billing_period: str | None) -> date | None:
    """The day after the settled period ends: "2025-01-01 / 2025-12-31" -> 2026-01-01."""
    try:
        end = date.fromisoformat(str(billing_period or "").split("/")[-1].strip())
    except ValueError:
        return None
    return end + timedelta(days=1)


def reading_days(start: date, today: date) -> list[date]:
    """Projection start followed by every first day of a month up to today."""
    days = [start]
    month = month_index(start) + 1
    while (day := date(month // 12, month % 12 + 1, 1)) <= today:
        days.append(day)
        month += 1
    return days


def period_reading_days(billing_period: str | None) -> list[date]:
    """Reading days spanning a settled period, ending the day after it."""
    try:
        start = date.fromisoformat(str(billing_period or "").split("/")[0].strip())
    except ValueError:
        return []
    end = projection_start(billing_period)
    if end is None or end <= start:
        return []
    days = reading_days(start, end)
    return days if days[-1] == end else [*days, end]


def simulate_bank(
    history: list[dict[str, Any]],
    factor: float,
    readings: list[tuple[date, float, float]],
    today: date,
    step: float = DEFAULT_STEP,
) -> dict[str, Any]:
    """Return the bank state for today, every kWh value rounded to ``step``.

    ``history`` holds PGE's settled batches (``insertToGridDate`` and raw
    ``leftEnergyAmount``). ``readings`` are cumulative (imported, exported) kWh
    on the projection start, on the first day of later months and, last, now.
    """
    batches: list[list[float]] = []
    for item in sorted(history, key=lambda h: str(h.get("insertToGridDate") or "")):
        left = _number(item.get("leftEnergyAmount"))
        try:
            inserted = date.fromisoformat(str(item.get("insertToGridDate") or "")[:10])
        except ValueError:
            continue
        if left is not None and left > 0:
            batches.append([month_index(inserted), left * factor])

    deficit = imported = exported = expired = 0.0
    deficit_since: str | None = None
    for (day, imp, exp), (_, next_imp, next_exp) in zip(readings, readings[1:]):
        month = month_index(day)
        consumed = max(next_imp - imp, 0.0)
        fed_in = max(next_exp - exp, 0.0)
        imported += consumed
        exported += fed_in

        # This month's batch repays any deficit before it can be banked.
        new = fed_in * factor
        repaid = min(new, deficit)
        deficit -= repaid
        batches.append([month, new - repaid])

        remaining = consumed
        kept = []
        for batch_month, amount in batches:
            if month - batch_month > EXPIRY_MONTHS:
                expired += amount
                continue
            used = min(amount, remaining)
            remaining -= used
            if amount - used > _DUST_KWH:
                kept.append([batch_month, amount - used])
        batches = kept
        deficit += remaining
        if deficit <= _DUST_KWH:
            deficit_since = None
        elif deficit_since is None:
            deficit_since = _month_label(month)

    now = month_index(today)
    active = []
    for batch_month, amount in batches:
        if now - batch_month > EXPIRY_MONTHS:
            expired += amount
        else:
            active.append({
                "miesiac": _month_label(int(batch_month)),
                "kwh": quantize(amount, step),
                "wygasa_z_koncem": _month_label(int(batch_month) + EXPIRY_MONTHS),
            })

    return {
        # A deficit exists only once every batch is used up, so this is never negative.
        "pozostalo": quantize(sum(b[1] for b in batches if now - b[0] <= EXPIRY_MONTHS), step),
        "factor": factor,
        "pobrana_od_startu": quantize(imported, step),
        "oddana_od_startu": quantize(exported, step),
        "oddana_po_opuscie": quantize(exported * factor, step),
        "deficyt": quantize(deficit, step),
        "deficyt_od": deficit_since,
        "wygaslo": quantize(expired, step),
        "najblizsze_wygasniecie": active[0] if active else None,
        "partie": active,
    }
