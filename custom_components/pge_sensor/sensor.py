"""Sensor platform for the PGE Sensor integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .entity_ids import account_number_for_entry, default_entity_id
from .const import CONF_ACCOUNT_ID, DOMAIN
from .settlement import bank_total, bank_zones
from .coordinator import PgeEbokCoordinator

MONETARY_UNIT = "PLN"


@dataclass
class PgeSensorDescription:
    name: str
    key: str


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PgeEbokCoordinator = hass.data[DOMAIN][entry.entry_id]
    username = entry.data[CONF_USERNAME]
    account_id = entry.data.get(CONF_ACCOUNT_ID)
    # Include the account/point id in the slug so multiple points for the same
    # user get distinct entities and devices instead of colliding.
    slug = slugify(f"{username}_{account_id}") if account_id is not None else slugify(username)
    device_name = entry.title or f"PGE Sensor ({username})"

    # Retire the legacy sensor: its source field is PLN, not energy. Keep the
    # registry entry and history; expose the corrected value through a new ID.
    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id == f"{slug}_settled_energy" and registered.disabled_by is None:
            registry.async_update_entity(
                registered.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
            )

    # An explicit False means these capabilities do not apply. Preserve
    # existing registry entries/history, but stop advertising bank/export.
    prosumer_suffixes = ("_feed_in_energy", "_energy_storage", "_energy_storage_1",
                         "_energy_storage_2", "_bank_date")
    prosument = coordinator.data.prosument if coordinator.data else None
    not_prosumer = prosument is False
    registry = er.async_get(hass)
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        if registered.unique_id.endswith(prosumer_suffixes):
            if not_prosumer and registered.disabled_by is None:
                registry.async_update_entity(registered.entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION)
            elif prosument is True and registered.disabled_by == er.RegistryEntryDisabler.INTEGRATION:
                registry.async_update_entity(registered.entity_id, disabled_by=None)

    entities: list[SensorEntity] = [
        PgeBalanceSensor(coordinator, slug, username, device_name),
        PgeInvoiceAmountSensor(coordinator, slug, username, device_name),
        PgeConsumedEnergySensor(coordinator, slug, username, device_name),
        PgeFeedInEnergySensor(coordinator, slug, username, device_name),
        PgeActualInvoiceSensor(coordinator, slug, username, device_name),
        PgeSettlementValueSensor(coordinator, slug, username, device_name),
        PgeForecastEnergySensor(coordinator, slug, username, device_name),
        PgeBankDateSensor(coordinator, slug, username, device_name),
        PgeBankZoneSensor(coordinator, slug, username, device_name, "Strefa 1"),
        PgeBankZoneSensor(coordinator, slug, username, device_name, "Strefa 2"),
        PgeEnergyStorageSensor(coordinator, slug, username, device_name),
        PgeBillingPeriodSensor(coordinator, slug, username, device_name),
        PgeCurrentPaymentSensor(coordinator, slug, username, device_name),
        PgeDueDateSensor(coordinator, slug, username, device_name),
    ]

    multiple_accounts = sum(
        item.disabled_by is None for item in hass.config_entries.async_entries(DOMAIN)
    ) > 1
    account_number = account_number_for_entry(entry.data, entry.title)
    for entity in entities:
        key = entity.unique_id.removeprefix(f"{slug}_")
        entity.entity_id = default_entity_id(
            account_number, key, multiple_accounts=multiple_accounts
        )

    async_add_entities(entities)


class PgeBaseSensor(CoordinatorEntity[PgeEbokCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: PgeEbokCoordinator,
        slug: str,
        username: str,
        device_name: str = "PGE Sensor",
    ) -> None:
        super().__init__(coordinator)
        self._slug = slug
        self._username = username
        self._device_name = device_name
        if (coordinator.data and coordinator.data.prosument is False
                and isinstance(self, (PgeFeedInEnergySensor, PgeEnergyStorageSensor, PgeBankDateSensor))):
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._slug)},
            name=self._device_name,
            manufacturer="PGE",
        )

    @property
    def available(self) -> bool:
        if self._attr_available is False:
            return False
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        if not data or self.unique_id.endswith(("_invoice_amount", "_current_payment", "_due_date", "_forecast_energy")):
            return {}
        return {"pge_energy_details_available": data.consumed_energy is not None,
                "prosument": data.prosument,
                "settlement_date": data.settlement_date,
                "settlement_invoice": data.settlement_invoice,
                "billing_period": data.billing_period,
                "historical_settlement": True}


class PgeBalanceSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = MONETARY_UNIT
    _attr_name = "PGE Saldo"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_balance"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data:
            return round(self.coordinator.data.amount, 2)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        if not self.coordinator.data:
            return None
        attributes = {}
        data = self.coordinator.data
        if data.invoice_number:
            attributes["invoice_number"] = data.invoice_number
        if data.issue_date:
            attributes["issue_date"] = data.issue_date.isoformat()
        if data.paid_date:
            attributes["paid_date"] = data.paid_date.isoformat()
        if data.payment_status:
            attributes["payment_status"] = data.payment_status
        if data.ppe:
            attributes["ppe"] = data.ppe
        return attributes or None


class PgeDueDateSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_name = "PGE Termin płatności"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_due_date"

    @property
    def native_value(self) -> date | None:
        if self.coordinator.data:
            return self.coordinator.data.due_date
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data and self.coordinator.data.due_date is None:
            self._attr_available = False
        else:
            self._attr_available = True
        super()._handle_coordinator_update()


class PgeInvoiceAmountSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = MONETARY_UNIT
    _attr_name = "PGE Kwota ostatniego dokumentu płatności"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_invoice_amount"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self.coordinator.data.invoice_amount is not None:
            return round(self.coordinator.data.invoice_amount, 2)
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.invoice_amount is not None


class PgeConsumedEnergySensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = None
    _attr_name = "PGE Pobór w ostatnim rzeczywistym rozliczeniu"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_consumed_energy"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self.coordinator.data.consumed_energy is not None:
            return self.coordinator.data.consumed_energy
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.consumed_energy is not None


class PgeFeedInEnergySensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = None
    _attr_name = "PGE Oddanie w ostatnim rzeczywistym rozliczeniu"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_feed_in_energy"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self.coordinator.data.feed_in_energy is not None:
            return self.coordinator.data.feed_in_energy
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.feed_in_energy is not None


class PgeSettledEnergySensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_name = "PGE Zużycie po rozliczeniu (wycofany błędny odczyt)"
    _attr_entity_registry_enabled_default = False

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_settled_energy"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self.coordinator.data.settled_energy is not None:
            return self.coordinator.data.settled_energy
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.settled_energy is not None


class PgeEnergyStorageSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = None
    _attr_name = "PGE Bank po opuście — ostatnie rozliczenie"

    @property
    def unique_id(self):
        return f"{self._slug}_energy_storage"

    @property
    def native_value(self):
        return bank_total(self.coordinator.data.energy_storage) if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs.update({"after_opust": True, "zones": bank_zones(self.coordinator.data.energy_storage) if self.coordinator.data else {}})
        # Preserve the author's attribute names for existing templates/cards.
        storage = self.coordinator.data.energy_storage if self.coordinator.data else None
        zones = (storage or {}).get("zones", {})
        first = zones.get("Strefa 1") or zones.get("Strefa 1 w sumie") or next(iter(zones.values()), {})
        summary = first.get("dataWarehouseSummary") or {}
        for original, attribute in (("settledEnergyAmountSumWithFactor", "settled_energy_sum_with_factor"),
                                    ("settledEnergyAmountSum", "settled_energy_sum"), ("factor", "factor")):
            if original in summary:
                attrs[attribute] = summary[original]
        if first.get("dataWarehousePpm"):
            attrs["history"] = sorted(first["dataWarehousePpm"], key=lambda x: x.get("insertToGridDate", ""), reverse=True)
        return attrs

    @property
    def available(self):
        return super().available and self.native_value is not None


class PgeBankZoneSensor(PgeEnergyStorageSensor):
    def __init__(self, coordinator, slug, username, device_name, zone):
        super().__init__(coordinator, slug, username, device_name)
        self.zone = zone
        self._attr_name = f"PGE Bank {zone} po opuście — ostatnie rozliczenie"

    @property
    def unique_id(self):
        return f"{self._slug}_energy_storage_{self.zone[-1]}"

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return bank_zones(self.coordinator.data.energy_storage).get(self.zone, {}).get("available_kwh")


class PgeBankDateSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_name = "PGE Data potwierdzonego salda banku"

    @property
    def unique_id(self):
        return f"{self._slug}_bank_date"

    @property
    def native_value(self):
        value = self.coordinator.data.settlement_date if self.coordinator.data else None
        if not value or bank_total(self.coordinator.data.energy_storage) is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @property
    def available(self):
        return super().available and self.native_value is not None


class PgeSettlementValueSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = "PLN"
    _attr_name = "PGE Wartość rozliczenia energii (PLN)"

    @property
    def unique_id(self):
        return f"{self._slug}_settlement_value_pln"

    @property
    def native_value(self):
        return self.coordinator.data.settlement_amount if self.coordinator.data else None

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        attrs = super().extra_state_attributes
        attrs["source_field"] = "valueSettledEnergyConsumed"
        return attrs


class PgeForecastEnergySensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = None
    _attr_name = "PGE Prognozowany pobór — dokument płatności"

    @property
    def unique_id(self):
        return f"{self._slug}_forecast_energy"

    @property
    def native_value(self):
        return self.coordinator.data.forecast_energy if self.coordinator.data else None

    @property
    def available(self):
        return super().available and self.native_value is not None

    @property
    def extra_state_attributes(self):
        return {"forecast": True, "billing_period": self.coordinator.data.forecast_period if self.coordinator.data else None}


class PgeBillingPeriodSensor(PgeBaseSensor):
    _attr_device_class = None
    _attr_icon = "mdi:calendar-range"
    _attr_name = "PGE Okres rozliczeniowy"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_billing_period"

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data:
            return self.coordinator.data.billing_period
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.billing_period is not None

class PgeCurrentPaymentSensor(PgeBaseSensor):
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = MONETARY_UNIT
    _attr_name = "PGE Bieżąca płatność"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_current_payment"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data and self.coordinator.data.current_payment is not None:
            return round(self.coordinator.data.current_payment, 2)
        return None

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.current_payment is not None


class PgeActualInvoiceSensor(PgeSettlementValueSensor):
    _attr_name = "PGE Kwota rzeczywistej faktury rozliczeniowej"

    @property
    def unique_id(self):
        return f"{self._slug}_actual_invoice_amount"

    @property
    def native_value(self):
        return self.coordinator.data.actual_invoice_amount if self.coordinator.data else None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {"invoice_number": data.actual_invoice_number if data else None,
                "issue_date": data.actual_invoice_date if data else None,
                "historical_invoice": True}
