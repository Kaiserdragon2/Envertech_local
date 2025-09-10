import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_IP_ADDRESS, CONF_PORT, CONF_UNIQUE_ID
from homeassistant.helpers import config_validation as cv

from .sensor import InverterSocketCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict):
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Setting up envertech_local entry")

    ip = entry.data[CONF_IP_ADDRESS]
    sn = entry.data[CONF_UNIQUE_ID]
    port = entry.data[CONF_PORT]

    coordinator = InverterSocketCoordinator(hass, ip, port, sn)

    # Store the coordinator reference so sensors and diagnostics can use it
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    coordinator: InverterSocketCoordinator = hass.data[entry.domain][entry.entry_id]
    return {
        "device_id": coordinator.device_id,
        "module_ids": coordinator.module_ids,
        "latest_values": coordinator.data,
    }
