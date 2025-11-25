import logging
import asyncio

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

class InverterSocketCoordinator(DataUpdateCoordinator):
    """Coordinator using envertech_local.stream_inverter_data()."""

    def __init__(self, hass, ip: str, port: int, sn: str):
        super().__init__(
            hass,
            _LOGGER,
            name="inverter_stream",
        )
        self.ip = ip
        self.port = port
        self.sn = sn

        self.data = {}
        self.number_of_panels = 0
        self.data_ready = False
        self.connected = False
        self.running = True

        # Start streaming
        asyncio.create_task(self._stream_loop())

    async def _stream_loop(self):
        """Consume inverter data from stream_inverter_data()."""

        from envertech_local import stream_inverter_data

        device = {
            "ip": self.ip,
            "port": self.port,
            "serial_number": self.sn,
        }

        while self.running:
            try:
                async for update in stream_inverter_data(device, interval=5):

                    if isinstance(update, dict) and "error" in update:
                        self.connected = False
                        continue

                    parsed_data = update

                    # Count panels
                    panel_ids = [
                        key.split("_")[0]
                        for key in parsed_data.keys()
                        if "_" in key and key[0].isdigit()
                    ]
                    self.number_of_panels = len(set(panel_ids))

                    # Store all values
                    for key, val in parsed_data.items():
                        if isinstance(val, (int, float)):
                            self.data[key] = round(val, 2)
                        else:
                            self.data[key] = val

                    self.connected = True
                    self.data_ready = True

                    # Notify HA
                    self.async_set_updated_data(self.data)

            except Exception as e:
                self.connected = False
                await asyncio.sleep(10)


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
        # Check the connection status
        return self.coordinator.connected and self.coordinator.last_update_success

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Wait for initial data
    for _ in range(60):
        if coordinator.data_ready:
            break
        await asyncio.sleep(1)

    if not coordinator.data_ready:
        _LOGGER.error("Failed to load inverter data within 60 seconds")
        return

    entities = []

    # Add per-panel sensors
    for i in range(coordinator.number_of_panels):
        for description in SENSOR_TYPES:
            entities.append(InverterSensor(coordinator, description, module_index=i))

    # Add single (global) sensors
    for description in SENSOR_TYPES_SINGLE:
        entities.append(InverterSensor(coordinator, description))

    async_add_entities(entities)