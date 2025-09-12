import socket
import binascii
import logging
import threading
import time
from datetime import timedelta

from .const import DOMAIN

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorEntityDescription,
    SensorDeviceClass,
)
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfElectricPotential,
    UnitOfFrequency,
    EntityCategory,
)
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="input_voltage",
        translation_key="input_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    SensorEntityDescription(
        key="power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(
        key="energy",
        translation_key="energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="grid_voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    SensorEntityDescription(
        key="frequency",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.FREQUENCY,
    ),
    SensorEntityDescription(
        key="mi_sn",
        translation_key="module_serial",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

_LOGGER = logging.getLogger(__name__)


def check_cs(byte_array):
    return (sum(byte_array) + 85) & 0xFF


def hex_string_to_bytes(hex_str):
    """Convert hex string to byte array."""
    hex_str = hex_str.strip().replace(" ", "")
    return bytes.fromhex(hex_str)


def to_int16(byte1, byte2):
    return byte1 * 256 + byte2


def to_int32(byte1, byte2, byte3, byte4):
    return (byte1 << 24) + (byte2 << 16) + (byte3 << 8) + byte4


def start_send_data(current_id_hex: str) -> bytes:
    data = bytearray()

    # Fixed header
    data += bytes([0x68, 0x00, 0x20, 0x68, 0x10, 0x77])

    # Add currentID bytes
    try:
        current_id_bytes = hex_string_to_bytes(current_id_hex)
        data += current_id_bytes
    except ValueError as e:
        print(f"Invalid hex string for currentID: {e}")
        return b""

    # Pad with 20 zero bytes
    data += bytes([0x00] * 20)

    # Compute and add checksum
    checksum = check_cs(data)
    data.append(checksum)

    # End byte
    data.append(0x16)

    return bytes(data)


def parse_module_data(data, offset):
    try:
        return {
            "mi_sn": "".join(f'{data[offset["mi_sn"]+i]:02x}' for i in range(4)),
            "input_voltage": to_int16(
                data[offset["input_voltage"]], data[offset["input_voltage"] + 1]
            )
            * 64
            / 32768,
            "power": to_int16(data[offset["power"]], data[offset["power"] + 1])
            * 512
            / 32768,
            "energy": to_int32(
                data[offset["energy"]],
                data[offset["energy"] + 1],
                data[offset["energy"] + 2],
                data[offset["energy"] + 3],
            )
            * 4
            / 32768,
            "temperature": to_int16(
                data[offset["temperature"]], data[offset["temperature"] + 1]
            )
            * 256
            / 32768
            - 40,
            "grid_voltage": to_int16(
                data[offset["grid_voltage"]], data[offset["grid_voltage"] + 1]
            )
            * 512
            / 32768,
            "frequency": to_int16(
                data[offset["frequency"]], data[offset["frequency"] + 1]
            )
            * 128
            / 32768,
        }
    except IndexError:
        return None


class InverterSocketCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, ip: str, port: int, sn: str):
        super().__init__(
            hass,
            _LOGGER,
            name="inverter_socket",
        )
        self.ip = ip
        self.port = port
        self.sn = sn

        self.data = {}
        self.module_ids = {}
        self.sock = None
        self.running = True
        threading.Thread(target=self.reader_loop, daemon=True).start()

    def reader_loop(self):
        while self.running:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(300)
                self.sock.connect((self.ip, self.port))
                _LOGGER.info("Connected to inverter.")
                while self.running:
                    raw = self.sock.recv(1024)

                    if not raw:
                        _LOGGER.warning("Socket closed by inverter.")
                        break
                        # Check length and headers
                    if len(raw) < 16:
                        _LOGGER.warning(
                            "Received incomplete packet: length=%d, expected=%d",
                            len(raw),
                            16,
                        )
                        continue
                    # Check headers
                    if raw[0] != 0x68 or raw[3] != 0x68:
                        _LOGGER.warning("Invalid packet header")
                        continue

                    expected_length = int.from_bytes(raw[1:3], "big")
                    if len(raw) != expected_length:
                        _LOGGER.warning(
                            "Length mismatch: expected %d bytes from length field, got %d",
                            expected_length,
                            len(raw),
                        )
                        continue
                    if len(raw) == 32:
                        self.sock.sendall(start_send_data(self.sn))
                        raw = self.sock.recv(1024)
                    control_code = int.from_bytes(raw[4:6], "big")
                    if control_code == 4177:
                        data = list(raw)
                        device_id = "".join(f"{b:02x}" for b in data[6:10])
                        number_of_panels = (len(raw) - 22) // 32
                        for i in range(number_of_panels):
                            base_offset = 20 + i * 32
                            offset = {
                                "mi_sn": base_offset + 0,
                                "input_voltage": base_offset + 6,
                                "power": base_offset + 8,
                                "energy": base_offset + 10,
                                "temperature": base_offset + 14,
                                "grid_voltage": base_offset + 16,
                                "frequency": base_offset + 18,
                            }
                            parsed = parse_module_data(data, offset)
                            if parsed:
                                for key, val in parsed.items():
                                    if isinstance(val, (int, float)):
                                        self.data[f"{i}_{key}"] = round(val, 2)
                                    else:
                                        self.data[f"{i}_{key}"] = val

                        self.hass.loop.call_soon_threadsafe(
                            self.async_set_updated_data, self.data
                        )
            except Exception as e:
                _LOGGER.error(f"Inverter socket error: {e}")
                time.sleep(5)

    async def async_close(self):
        self.running = False
        if self.sock:
            self.sock.close()


class InverterModuleSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self, coordinator, module_index: int, description: SensorEntityDescription
    ):
        super().__init__(coordinator)
        self.entity_description = description
        self._module_index = module_index
        self._attr_name = f"P{module_index + 1} {description.translation_key.replace('_', ' ').title()}"
        self._attr_unique_id = (
            f"EVT_{self.coordinator.sn}_P{module_index}_{description.key}"
        )
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category

    @property
    def native_value(self):
        return self.coordinator.data.get(
            f"{self._module_index}_{self.entity_description.key}"
        )

    @property
    def extra_state_attributes(self):
        return {
            "serial_number": self.coordinator.data.get(f"{self._module_index}_mi_sn")
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"EVT_{self.coordinator.sn}")},  # unique device id
            name="EVT",
            manufacturer="Envertech",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class InverterCombinedSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, key, name, unit):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"EVT_{self.coordinator.sn}_combined_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        total = 0.0
        valid = False
        for i in range(4):
            val = self.coordinator.data.get(f"{i}_{self._key}")
            if isinstance(val, (int, float)):
                total += val
                valid = True
        return round(total, 2) if valid else None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"EVT_{self.coordinator.sn}")},
            name="EVT",
            manufacturer="Envertech",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


async def async_setup_entry(hass, entry, async_add_entities):
    # Get the coordinator from hass.data where it was stored in __init__.py
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    for i in range(16):
        for description in SENSOR_TYPES:
            entities.append(InverterModuleSensor(coordinator, i, description))

    # Add combined sensors manually
    entities.append(
        InverterCombinedSensor(coordinator, "power", "Total Power", UnitOfPower.WATT)
    )
    entities.append(
        InverterCombinedSensor(
            coordinator, "energy", "Total Energy", UnitOfEnergy.KILO_WATT_HOUR
        )
    )

    async_add_entities(entities)
