import socket
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_UNIQUE_ID

from .const import DOMAIN, DEVICE_NAME

# Set up logging for debugging
logging.basicConfig(level=logging.DEBUG)

# The message that we will send out in the broadcast (matching the app logic)
udp_dicovery_msg = "LOCALCON-1508-READ"  # Discovery message 
udp_dicovery_msg_wifi = "www.usr.cn"  # Discovery message WIFI

# Broadcast address and ports
broadcast_ip = '255.255.255.255'
broadcast_ports = [48889, 48899]  # Ports for the broadcast (48899 Wifi)

# Function to discover devices with a timeout
def discover_devices(timeout=5):
    discovered_devices = []

    # Create a new socket each time discovery is attempted
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)  # Set timeout for the socket

    # Encode the messages as bytes before sending
    encoded_msg = udp_dicovery_msg.encode('utf-8')
    encoded_msg_wifi = udp_dicovery_msg_wifi.encode('utf-8')

    # Send the broadcast message to all devices on the network
    for port in broadcast_ports:
        message_to_send = encoded_msg if port == 48889 else encoded_msg_wifi
        logging.info(f"Sending broadcast message: {message_to_send.decode()} to {broadcast_ip}:{port}")
        sock.sendto(message_to_send, (broadcast_ip, port))

    # Listen for replies from devices for a short period of time
    try:
        while True:
            data, addr = sock.recvfrom(1024)  # Buffer size of 1024 bytes
            logging.info(f"Received data from {addr}: {data}")

            # If the device sends a valid response, extract the information
            if data:
                device_info = data.decode('utf-8', errors='ignore')
                logging.info(f"Device response: {device_info}")

                # Parse the response: "IP,MAC,SN"
                parts = device_info.split(',')

                if len(parts) == 3:
                    ip = parts[0]
                    mac = parts[1]
                    serial_number = parts[2]

                    discovered_devices.append({
                        'ip': ip,
                        'mac': mac,
                        'serial_number': serial_number,
                    })

    except socket.timeout:
        # Timeout reached, stop listening
        logging.info("Discovery timed out.")
    finally:
        # Close the socket once the discovery is done
        sock.close()
    return discovered_devices


class InverterMonitorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.discovered_devices = []

    async def async_step_user(self, user_input=None):
        self.discovered_devices = await self.hass.async_add_executor_job(discover_devices)

        # Get the list of existing devices in Home Assistant
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        existing_ips = {entry.data[CONF_IP_ADDRESS] for entry in existing_entries}
        existing_ids = {entry.data[CONF_UNIQUE_ID] for entry in existing_entries}

        # Filter out already existing devices from the discovered list
        filtered_devices = [
            device for device in self.discovered_devices
            if device['ip'] not in existing_ips and device['serial_number'] not in existing_ids
        ]

        if not filtered_devices:
            # No new devices found, exit early or inform the user
            return self.async_show_form(
                step_id="user",
                errors={"base": "no_new_devices"},
                description_placeholders={
                    "discovered_devices": "No new devices found."
                }
            )
        # Create a mapping of IP to serial number
        ip_to_sn = {d["ip"]: d["serial_number"] for d in self.discovered_devices}

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
            d["ip"]: f"{d['ip']} - {d['serial_number']}" for d in self.discovered_devices
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
