import socket
import binascii
import logging
import asyncio
from datetime import timedelta

from .const import DOMAIN, MANUFACTURER, DEVICE_NAME

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
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="power",
        translation_key="power",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="energy",
        translation_key="energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="temperature",
        translation_key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="grid_voltage",
        translation_key="grid_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="frequency",
        translation_key="frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.FREQUENCY,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="mi_sn",
        translation_key="module_serial",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

SENSOR_TYPES_SINGLE: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="total_power",
        translation_key="total_power",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        suggested_display_precision=2,
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
        self.number_of_panels = 0
        self.data_ready = False  # Add a flag to track data readiness

    async def reader_loop(self):
        while self.running:
            try:
                reader, writer = await asyncio.open_connection(self.ip, self.port)
                _LOGGER.info("Connected to inverter.")

                while self.running:
                    raw = await asyncio.wait_for(reader.read(1024), timeout=300)

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
                        writer.write(start_send_data(self.sn))
                        await writer.drain()
                        raw = await asyncio.wait_for(reader.read(1024), timeout=300)

                    control_code = int.from_bytes(raw[4:6], "big")
                    if control_code == 4177:
                        data = list(raw)
                        self.number_of_panels = (len(raw) - 22) // 32
                        self.data["firmware_version"] = f"{data[10]}/{data[12]}"
                        for i in range(self.number_of_panels):
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

                        # Update combined sensors
                        for key in ["power", "energy"]:
                            total = 0.0
                            valid = False
                            for i in range(self.number_of_panels):
                                val = self.data.get(f"{i}_{key}")
                                if isinstance(val, (int, float)):
                                    total += val
                                    valid = True
                            self.data[f"total_{key}"] = round(total, 2) if valid else None

                        # Set the data_ready flag once we have the data
                        self.data_ready = True
                        self.hass.loop.call_soon_threadsafe(
                            self.async_set_updated_data, self.data
                        )
            except Exception as e:
                _LOGGER.error(f"Inverter socket error: {e}")
                await asyncio.sleep(5)

    async def async_close(self):
        self.running = False
        if self.sock:
            self.sock.close()


class InverterSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self, coordinator, description: SensorEntityDescription, module_index: int = None
    ):
        super().__init__(coordinator)
        self.entity_description = description
        self._module_index = module_index

        # If module_index is provided, it's a module sensor, otherwise it's a single sensor
        if module_index is not None:
            self._attr_name = f"P{module_index + 1} {description.translation_key.replace('_', ' ').title()}"
            self._attr_unique_id = f"{DEVICE_NAME}_{self.coordinator.sn}_P{module_index}_{description.key}"
        else:
            self._attr_name = description.translation_key.replace('_', ' ').title()
            self._attr_unique_id = f"{DEVICE_NAME}_{self.coordinator.sn}_{description.key}"

        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_device_class = description.device_class
        self._attr_entity_category = description.entity_category

    @property
    def native_value(self):
        if self._module_index is not None:
            # Module-specific data retrieval
            return self.coordinator.data.get(f"{self._module_index}_{self.entity_description.key}")
        else:
            # Single sensor data retrieval
            return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        if self._module_index is not None:
            return {
                "serial_number": self.coordinator.data.get(f"{self._module_index}_mi_sn")
            }
        else:
            return {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"{DEVICE_NAME}_{self.coordinator.sn}")},  # unique device id
            name=f"{DEVICE_NAME} {self.coordinator.sn}",
            manufacturer=MANUFACTURER,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

async def async_setup_entry(hass, entry, async_add_entities):
    # Get the coordinator from hass.data where it was stored in __init__.py
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Wait for the coordinator's reader_loop to set data_ready to True
    while not coordinator.data_ready:
        _LOGGER.debug("Waiting for inverter data to be ready...")
        await asyncio.sleep(1)  # Sleep for a short time and check again

    if coordinator.number_of_panels == 0:
        _LOGGER.error("No panels detected.")
        return
    
    entities = []

    for i in range(coordinator.number_of_panels):
        for description in SENSOR_TYPES:
            entities.append(InverterSensor(coordinator, description, module_index=i))

    for description in SENSOR_TYPES_SINGLE:
        entities.append(InverterSensor(coordinator, description))

    async_add_entities(entities)
