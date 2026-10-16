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
    def async_get_entity_id(self, domain, platform, unique_id):
        return next((x.entity_id for x in self.entries if x.unique_id==unique_id), None)
    def async_remove(self, entity_id):
        self.entries=[x for x in self.entries if x.entity_id!=entity_id]

def module(name, **members):
    m=types.ModuleType(name)
    m.__dict__.update(members)
    return m

stubs={
    'homeassistant': module('homeassistant'),
    'homeassistant.components': module('homeassistant.components'),
    'homeassistant.components.sensor': module('homeassistant.components.sensor', SensorEntity=SensorEntity,
        SensorDeviceClass=types.SimpleNamespace(MONETARY='monetary', ENERGY='energy', DATE='date',
            ENERGY_STORAGE='energy_storage'),
        SensorStateClass=types.SimpleNamespace(TOTAL='total', TOTAL_INCREASING='total_increasing',
            MEASUREMENT='measurement')),
    'homeassistant.config_entries': module('homeassistant.config_entries', ConfigEntry=object),
    'homeassistant.const': module('homeassistant.const', CONF_USERNAME='username', CONF_PASSWORD='password',
        ATTR_UNIT_OF_MEASUREMENT='unit_of_measurement',
        UnitOfEnergy=types.SimpleNamespace(KILO_WATT_HOUR='kWh')),
    'homeassistant.core': module('homeassistant.core', HomeAssistant=object, Event=object, callback=lambda fn:fn),
    'homeassistant.exceptions': module('homeassistant.exceptions', HomeAssistantError=Exception),
    'homeassistant.helpers': module('homeassistant.helpers'),
    'homeassistant.helpers.event': module('homeassistant.helpers.event',
        async_track_state_change_event=None, async_track_time_interval=None),
    'homeassistant.helpers.entity': module('homeassistant.helpers.entity', DeviceInfo=dict),
    'homeassistant.helpers.entity_registry': module('homeassistant.helpers.entity_registry',
        async_get=lambda hass:hass.registry,
        async_entries_for_config_entry=lambda registry, entry_id:registry.entries,
        RegistryEntryDisabler=Disabler),
    'homeassistant.helpers.entity_platform': module('homeassistant.helpers.entity_platform', AddEntitiesCallback=object),
    'homeassistant.helpers.update_coordinator': module('homeassistant.helpers.update_coordinator', CoordinatorEntity=CoordinatorEntity),
    'homeassistant.util': module('homeassistant.util', slugify=lambda value:value, dt=None),
    'homeassistant.util.unit_conversion': module('homeassistant.util.unit_conversion', EnergyConverter=None),
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
        entry=types.SimpleNamespace(entry_id='test',data={'username':'test','account_id':1},title='Test',options={})
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

class MeterProjectionTests(unittest.TestCase):
    """Bank, current and previous energy to pay come from one projection."""

    def projection(self, values, readings, previous_readings, now=(150, 0)):
        states={'sensor.imp':now[0],'sensor.exp':now[1]}
        hass=types.SimpleNamespace(config=types.SimpleNamespace(components={'recorder'}),
            states=types.SimpleNamespace(get=lambda e:types.SimpleNamespace(state=str(states[e]),attributes={})))
        coordinator=types.SimpleNamespace(data=values,last_update_success=True,name='PGE test')
        projection=sensors.MeterProjection(hass,coordinator,('sensor.imp','sensor.exp'),step=0.1)
        projection.start=date(2026,3,1)
        projection._readings=readings;projection._previous_readings=previous_readings
        clock=types.SimpleNamespace(now=lambda:types.SimpleNamespace(date=lambda:date(2026,3,20)),
                                    start_of_local_day=lambda day:day)
        with patch.object(sensors,'dt_util',clock), \
             patch.object(sensors,'EnergyConverter',types.SimpleNamespace(convert=lambda value,unit,to:value)):
            projection._recalculate()
            entities=[cls(coordinator,'test_1','test','Test',projection) for cls in
                      (sensors.PgeMeterBankSensor,sensors.PgeMeterDeficitSensor,sensors.PgeMeterPreviousDeficitSensor)]
            return [(e.native_value,e.extra_state_attributes,e.available) for e in entities], entities

    def test_bank_runs_out_then_energy_to_pay_counts(self):
        bank={'zones':{'Strefa 1':{'dataWarehouseSummary':{'leftEnergyAmountSum':50,'factor':.8},
              'dataWarehousePpm':[{'insertToGridDate':'2026-02-01','leftEnergyAmount':50}]}}}
        previous={'zones':{'Strefa 1':{'dataWarehouseSummary':{'leftEnergyAmountSum':100,'factor':.8},
              'dataWarehousePpm':[{'insertToGridDate':'2025-11-01','leftEnergyAmount':100}]}}}
        values=data(billing_period='2026-01-01 / 2026-02-28',energy_storage=bank,consumed_energy=120,feed_in_energy=50,
                    previous_energy_storage=previous,previous_billing_period='2025-07-01 / 2025-12-31')
        # Current: 40 kWh bank, 100 kWh used since 1 March. Previous: 80 kWh bank,
        # 120 kWh used and 50 kWh exported (40 after opust) in January–February.
        (bank_now,current,previous_period),entities=self.projection(values,
            [(date(2026,3,1),50,0)],
            [(date(2026,1,1),0,0),(date(2026,2,1),60,50),(date(2026,3,1),120,50)])
        self.assertEqual(bank_now[0],0.0)
        self.assertEqual((current[0],current[1]['deficyt_od'],current[1]['magazyn']),(60.0,'2026-03',0.0))
        with patch.object(sensors,'dt_util',types.SimpleNamespace(start_of_local_day=lambda day:day)):
            self.assertEqual(entities[1].last_reset,date(2026,3,1))
        self.assertEqual(previous_period[0],0.0)
        attrs=previous_period[1]
        self.assertEqual((attrs['pobrana_od_startu'],attrs['pobrana_faktura']),(120.0,120))
        self.assertEqual((attrs['oddana_od_startu'],attrs['oddana_faktura']),(50.0,50))
        # 80 + 40 − 120 = 0 kWh left; PGE's invoice says 40 kWh: the comparison exposes the gap.
        self.assertEqual((attrs['magazyn_wyliczony_na_koniec'],attrs['magazyn_z_faktury']),(0.0,40.0))
        self.assertIsNone(entities[2]._attr_state_class)

    def test_previous_period_needs_previous_bank_and_full_statistics(self):
        values=data(previous_energy_storage=None,previous_billing_period=None)
        results,_=self.projection(values,[(date(2026,3,1),0,0)],[])
        self.assertTrue(results[1][2])
        self.assertFalse(results[2][2])
        values=data(previous_energy_storage={'zones':{}},previous_billing_period='2025-07-01 / 2025-12-31')
        results,_=self.projection(values,[(date(2026,3,1),0,0)],[(date(2026,1,1),0,0)])
        self.assertFalse(results[2][2])

    def test_meters_create_three_entities_and_removal_drops_them(self):
        unsubscribed=[]
        hass=types.SimpleNamespace(config_entries=None,registry=Registry(),async_create_task=lambda coro:coro.close(),
            data={'pge_sensor':{'test':types.SimpleNamespace(data=data(),last_update_success=True,
                async_add_listener=lambda cb:lambda:unsubscribed.append('coordinator'))}})
        entry=types.SimpleNamespace(entry_id='test',data={'username':'test','account_id':1},title='Test',
            options={'meter_import_entity':'sensor.imp','meter_export_entity':'sensor.exp'},
            async_on_unload=lambda stop:unsubscribed.append(stop))
        added=[]
        with patch.object(sensors,'async_track_state_change_event',lambda *a:lambda:None), \
             patch.object(sensors,'async_track_time_interval',lambda *a:lambda:None):
            asyncio.run(sensors.async_setup_entry(hass,entry,added.extend))
        meter=[e for e in added if isinstance(e,sensors.PgeMeterSensor)]
        self.assertEqual(len(added),17)
        self.assertEqual(len({id(e._projection) for e in meter}),1)
        self.assertEqual(meter[1].entity_id,'sensor.pge_1_zuzycie_do_zaplaty_biezace')
        unsubscribed[0]()
        self.assertIn('coordinator',unsubscribed)

        registry=Registry([types.SimpleNamespace(entity_id=f'sensor.{k}',unique_id=f'test_1_{k}',disabled_by=None)
                           for k in ('meter_bank','meter_deficit','meter_deficit_previous')])
        hass.registry=registry;entry.options={}
        asyncio.run(sensors.async_setup_entry(hass,entry,[].extend))
        self.assertEqual(registry.entries,[])

if __name__=='__main__':unittest.main()
