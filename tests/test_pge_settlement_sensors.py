"""Test sensor values/setup using small HA interfaces, not live credentials."""
import asyncio
from datetime import date
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1] / "custom_components/pge_sensor"
PACKAGE = "pge_settlement_sensor_test"
pkg = types.ModuleType(PACKAGE);pkg.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = pkg

class SensorEntity:
    _attr_available = None

class CoordinatorEntity:
    def __init__(self, coordinator): self.coordinator = coordinator
    def __class_getitem__(cls, item): return cls

class Disabler(str, Enum):
    INTEGRATION = "integration"
    USER = "user"

class Registry:
    def __init__(self, entries=()): self.entries=list(entries)
    def async_update_entity(self, entity_id, **kwargs):
        entry=next(x for x in self.entries if x.entity_id==entity_id)
        for k,v in kwargs.items():setattr(entry,k,v)

def module(name, **members):
    m=types.ModuleType(name)
    m.__dict__.update(members)
    return m

stubs={
    'homeassistant': module('homeassistant'),
    'homeassistant.components': module('homeassistant.components'),
    'homeassistant.components.sensor': module('homeassistant.components.sensor', SensorEntity=SensorEntity,
        SensorDeviceClass=types.SimpleNamespace(MONETARY='monetary', ENERGY='energy', DATE='date'),
        SensorStateClass=types.SimpleNamespace(TOTAL='total', TOTAL_INCREASING='total_increasing')),
    'homeassistant.config_entries': module('homeassistant.config_entries', ConfigEntry=object),
    'homeassistant.const': module('homeassistant.const', CONF_USERNAME='username', CONF_PASSWORD='password'),
    'homeassistant.core': module('homeassistant.core', HomeAssistant=object, callback=lambda fn:fn),
    'homeassistant.helpers': module('homeassistant.helpers'),
    'homeassistant.helpers.entity': module('homeassistant.helpers.entity', DeviceInfo=dict),
    'homeassistant.helpers.entity_registry': module('homeassistant.helpers.entity_registry',
        async_get=lambda hass:hass.registry,
        async_entries_for_config_entry=lambda registry, entry_id:registry.entries,
        RegistryEntryDisabler=Disabler),
    'homeassistant.helpers.entity_platform': module('homeassistant.helpers.entity_platform', AddEntitiesCallback=object),
    'homeassistant.helpers.update_coordinator': module('homeassistant.helpers.update_coordinator', CoordinatorEntity=CoordinatorEntity),
    'homeassistant.util': module('homeassistant.util', slugify=lambda value:value),
    PACKAGE+'.coordinator': module(PACKAGE+'.coordinator', PgeEbokCoordinator=object),
}
spec=importlib.util.spec_from_file_location(PACKAGE+'.sensor',ROOT/'sensor.py')
sensors=importlib.util.module_from_spec(spec);sys.modules[spec.name]=sensors
with patch.dict(sys.modules, stubs):spec.loader.exec_module(sensors)

def data(**updates):
    values={'prosument':True,'consumed_energy':100,'feed_in_energy':200,
        'settlement_date':'2026-06-30','settlement_invoice':'TEST/1','billing_period':'2026-01-01 / 2026-06-30',
        'settlement_amount':60,'actual_invoice_amount':50,'actual_invoice_number':'TEST/2',
        'actual_invoice_date':'2026-07-01','forecast_energy':300,'forecast_period':'2026-07-01 / 2026-09-30',
        'settled_energy':None,'energy_storage':{'zones':{'Strefa 1':{'dataWarehouseSummary':{'leftEnergyAmountSum':100,'factor':.8}}}}}
    values.update(updates);return types.SimpleNamespace(**values)

def sensor(cls, values=None, **kwargs):
    coordinator=types.SimpleNamespace(data=values or data(),last_update_success=True)
    return cls(coordinator,'test_1','test','Test',**kwargs)

class SensorTests(unittest.TestCase):
    def test_snapshot_energy_has_no_counter_state_class(self):
        for cls in (sensors.PgeConsumedEnergySensor,sensors.PgeFeedInEnergySensor,sensors.PgeForecastEnergySensor,sensors.PgeEnergyStorageSensor,sensors.PgeBankZoneSensor):
            self.assertIsNone(cls._attr_state_class)

    def test_values_have_distinct_units_and_ids(self):
        amount=sensor(sensors.PgeSettlementValueSensor)
        actual=sensor(sensors.PgeActualInvoiceSensor)
        self.assertEqual(amount.native_value,60)
        self.assertEqual(amount._attr_native_unit_of_measurement,'PLN')
        self.assertEqual(actual.native_value,50)
        self.assertNotEqual(amount.unique_id,actual.unique_id)
        self.assertEqual(actual.extra_state_attributes['invoice_number'],'TEST/2')
        self.assertNotIn('settlement_invoice',actual.extra_state_attributes)

    def test_bank_sum_and_zone_match(self):
        bank=sensor(sensors.PgeEnergyStorageSensor)
        zone=sensor(sensors.PgeBankZoneSensor,zone='Strefa 1')
        self.assertEqual(bank.native_value,80)
        self.assertEqual(zone.native_value,80)
        self.assertEqual(bank.extra_state_attributes['factor'],.8)
        self.assertTrue(bank.extra_state_attributes['after_opust'])

    def test_bank_date_requires_valid_bank(self):
        self.assertEqual(sensor(sensors.PgeBankDateSensor).native_value,date(2026,6,30))
        self.assertFalse(sensor(sensors.PgeBankDateSensor,data(energy_storage=None)).available)
        self.assertFalse(sensor(sensors.PgeBankDateSensor,data(settlement_date='bad')).available)

    def test_failed_update_is_unavailable(self):
        entity=sensor(sensors.PgeConsumedEnergySensor)
        entity.coordinator.last_update_success=False
        self.assertFalse(entity.available)

    def test_unknown_is_not_zero(self):
        self.assertFalse(sensor(sensors.PgeSettlementValueSensor,data(settlement_amount=None)).available)
        self.assertTrue(sensor(sensors.PgeSettlementValueSensor,data(settlement_amount=0)).available)

    def setup(self, prosument, registry=()):
        registry=Registry(registry)
        hass=types.SimpleNamespace(config_entries=types.SimpleNamespace(async_entries=lambda domain:[types.SimpleNamespace(disabled_by=None)]),registry=registry,data={'pge_sensor':{'test':types.SimpleNamespace(data=data(prosument=prosument),last_update_success=True)}})
        entry=types.SimpleNamespace(entry_id='test',data={'username':'test','account_id':1},title='Test')
        added=[];asyncio.run(sensors.async_setup_entry(hass,entry,added.extend))
        return added,registry

    def test_nonprosumer_bank_and_export_are_disabled_by_default(self):
        added,_=self.setup(False)
        self.assertEqual(len(added),14)
        for e in added:
            if isinstance(e,(sensors.PgeFeedInEnergySensor,sensors.PgeEnergyStorageSensor,sensors.PgeBankDateSensor)):
                self.assertFalse(e._attr_entity_registry_enabled_default)
        self.assertTrue(any(e.unique_id.endswith('_actual_invoice_amount') for e in added))

    def test_unknown_capability_is_not_treated_as_nonprosumer(self):
        added,_=self.setup(None)
        self.assertEqual(len(added),14)

    def test_disable_legacy_preserves_registry_and_user_choices(self):
        records=[types.SimpleNamespace(entity_id='sensor.old',unique_id='test_1_settled_energy',disabled_by=None),
                 types.SimpleNamespace(entity_id='sensor.bank',unique_id='test_1_energy_storage',disabled_by=Disabler.USER)]
        _,registry=self.setup(False,records)
        self.assertEqual(len(registry.entries),2)
        self.assertEqual(records[0].disabled_by,Disabler.INTEGRATION)
        self.assertEqual(records[1].disabled_by,Disabler.USER)

    def test_prosumer_can_reenable_integration_disabled_bank(self):
        record=types.SimpleNamespace(entity_id='sensor.bank',unique_id='test_1_energy_storage',disabled_by=Disabler.INTEGRATION)
        self.setup(True,[record])
        self.assertIsNone(record.disabled_by)

if __name__=='__main__':unittest.main()
