import socket
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_UNIQUE_ID
from envertech_local import discover_devices_async, get_inverter_data

from .const import DOMAIN, DEVICE_NAME

# Set up logging for debugging
logging.basicConfig(level=logging.DEBUG)

class InverterMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.discovered_devices = []

    async def async_step_user(self, user_input=None):
        self.discovered_devices = await discover_devices_async(timeout=5)

        # Get the list of existing devices in Home Assistant
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        existing_ids = {entry.data[CONF_UNIQUE_ID] for entry in existing_entries}

        # Filter out already existing devices from the discovered list
        filtered_devices = [
            device for device in self.discovered_devices
            if device['serial_number'] not in existing_ids
        ]

        # Create a mapping of IP to serial number
        ip_to_sn = {d["ip"]: d["serial_number"] for d in filtered_devices}

        # Show second step if manual was selected
        if user_input is not None:
            selected_ip = user_input[CONF_IP_ADDRESS]

            if selected_ip == "manual":
                return await self.async_step_manual()

            sn = ip_to_sn.get(selected_ip, "unknown")

            return self.async_create_entry(
                title=f"{DEVICE_NAME} {sn}",
                data={
                    CONF_IP_ADDRESS: selected_ip,
                    CONF_UNIQUE_ID: sn,
                    CONF_PORT: user_input[CONF_PORT],
                },
            )

        # Device dropdown + "Manual" option
        device_choices = {
            d["ip"]: f"{d['ip']} - {d['serial_number']}" for d in filtered_devices
        }
        device_choices["manual"] = "Manual entry"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): vol.In(device_choices),
                vol.Required(CONF_PORT, default=14889): int,
            }),
            description_placeholders={
                "discovered_devices": ", ".join(
                    [f"{d['ip']} - {d['serial_number']} (MAC: {d['mac']})" for d in self.discovered_devices]
                )
            }
        )

    async def async_step_manual(self, user_input=None):
        """Handle manual entry of device details."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"{DEVICE_NAME} {user_input[CONF_UNIQUE_ID]}",
                data={
                    CONF_IP_ADDRESS: user_input[CONF_IP_ADDRESS],
                    CONF_UNIQUE_ID: user_input[CONF_UNIQUE_ID],
                    CONF_PORT: user_input[CONF_PORT],
                },
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Required(CONF_UNIQUE_ID): str,
                vol.Required(CONF_PORT, default=14889): int,
            }),
        )
