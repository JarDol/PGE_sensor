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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .entity_ids import account_number_for_entry, default_entity_id
from .const import CONF_ACCOUNT_ID, DOMAIN
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

    entities: list[SensorEntity] = [
        PgeBalanceSensor(coordinator, slug, username, device_name),
        PgeInvoiceAmountSensor(coordinator, slug, username, device_name),
        PgeConsumedEnergySensor(coordinator, slug, username, device_name),
        PgeFeedInEnergySensor(coordinator, slug, username, device_name),
        PgeSettledEnergySensor(coordinator, slug, username, device_name),
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
        return self.coordinator.data is not None


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
    _attr_name = "PGE Kwota faktury"

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
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_name = "PGE Energia pobrana"

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
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_name = "PGE Energia wprowadzona"

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
    _attr_name = "PGE Zużycie po rozliczeniu"

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
    _attr_state_class = SensorStateClass.TOTAL
    _attr_name = "PGE Magazyn energii"

    @property
    def unique_id(self) -> str:
        return f"{self._slug}_energy_storage"

    @property
    def native_value(self) -> float | None:
        storage = self.coordinator.data.energy_storage
        if storage:
            zones = storage.get("zones", {})
            strefa_1 = zones.get("Strefa 1") or zones.get("Strefa 1 w sumie") or next(iter(zones.values()), {})
            summary = strefa_1.get("dataWarehouseSummary", {})
            if "leftEnergyAmountSum" in summary:
                return summary.get("leftEnergyAmountSum")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {}
        storage = self.coordinator.data.energy_storage
        if storage:
            zones = storage.get("zones", {})
            strefa_1 = zones.get("Strefa 1") or zones.get("Strefa 1 w sumie") or next(iter(zones.values()), {})
            summary = strefa_1.get("dataWarehouseSummary", {})
            
            if "settledEnergyAmountSumWithFactor" in summary:
                attrs["settled_energy_sum_with_factor"] = summary.get("settledEnergyAmountSumWithFactor")
            if "settledEnergyAmountSum" in summary:
                attrs["settled_energy_sum"] = summary.get("settledEnergyAmountSum")
            if "factor" in summary:
                attrs["factor"] = summary.get("factor")
                
            history = strefa_1.get("dataWarehousePpm")
            if history:
                attrs["history"] = sorted(
                    history,
                    key=lambda x: x.get("insertToGridDate", ""),
                    reverse=True
                )

        return attrs

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        return self.coordinator.data.energy_storage is not None

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
