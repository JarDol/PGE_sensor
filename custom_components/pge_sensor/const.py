"""Constants for the PGE Sensor integration."""
from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

DOMAIN = "pge_sensor"
DEFAULT_TIMEOUT = 15
CONF_ACCOUNT_ID = "account_id"
CONF_METER_IMPORT = "meter_import_entity"
CONF_METER_EXPORT = "meter_export_entity"

__all__ = ["DOMAIN", "CONF_USERNAME", "CONF_PASSWORD", "DEFAULT_TIMEOUT", "CONF_ACCOUNT_ID",
           "CONF_METER_IMPORT", "CONF_METER_EXPORT"]
