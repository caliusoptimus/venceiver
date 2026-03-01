"""Sensor entities for WiFi sensor receiver for Venstar."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import IntegrationData
from .entity import VenstarReceiverBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = entry.runtime_data
    if not isinstance(data, IntegrationData):
        raise RuntimeError("Runtime data missing on config entry")

    async_add_entities(
        [
            VenstarReceivedTemperatureSensor(data, entry),
            VenstarReceivedTemperatureCSensor(data, entry),
            VenstarLastSeenSensor(data, entry),
            VenstarBatteryPercentSensor(data, entry),
            VenstarUnitIdSensor(data, entry),
            VenstarSensorTypeSensor(data, entry),
            VenstarSensorNameSensor(data, entry),
        ]
    )


class VenstarReceivedTemperatureSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Latest authenticated temperature from paired sensor."""

    _attr_name = "Received Temperature F"
    _attr_unique_id = None
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_icon = "mdi:thermometer"

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_temperature"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.get("last_temperature_c")
        if value is None:
            return None
        value_c = float(value)
        value_f = value_c * (9.0 / 5.0) + 32.0
        return round(value_f, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.data.get("sensor_info") or {}
        return {
            "paired": self.coordinator.data.get("paired"),
            "unit_id": info.get("unit_id"),
            "sensor_name": info.get("name"),
            "sensor_mac": info.get("mac"),
            "sensor_type": info.get("sensor_type"),
            "battery_percent": info.get("battery_percent"),
            "sequence": self.coordinator.data.get("last_sequence"),
        }


class VenstarReceivedTemperatureCSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Latest authenticated temperature, fixed Celsius display."""

    _attr_name = "Received Temperature C"
    _attr_unique_id = None
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_temperature_c"

    @property
    def native_value(self) -> float | None:
        value = self.coordinator.data.get("last_temperature_c")
        if value is None:
            return None
        return round(float(value), 2)


class VenstarLastSeenSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Timestamp of the last valid packet."""

    _attr_name = "Last Seen"
    _attr_unique_id = None
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_last_seen"

    @property
    def native_value(self) -> datetime | None:
        raw = self.coordinator.data.get("last_seen_utc")
        if not isinstance(raw, str):
            return None
        try:
            return dt_util.parse_datetime(raw)
        except (TypeError, ValueError):
            return None


class VenstarBatteryPercentSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Battery percent from sensor packets."""

    _attr_name = "Battery"
    _attr_unique_id = None
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_battery"

    @property
    def native_value(self) -> int | None:
        info = self.coordinator.data.get("sensor_info") or {}
        value = info.get("battery_percent")
        if value is None:
            return None
        return int(value)


class VenstarUnitIdSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Unit ID from sensor packets."""

    _attr_name = "Unit ID"
    _attr_unique_id = None

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_unit_id"

    @property
    def native_value(self) -> int | None:
        info = self.coordinator.data.get("sensor_info") or {}
        value = info.get("unit_id")
        if value is None:
            return None
        return int(value)


class VenstarSensorTypeSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Sensor type decoded from packets."""

    _attr_name = "Sensor Type"
    _attr_unique_id = None

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_sensor_type"

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.data.get("sensor_info") or {}
        sensor_type = info.get("sensor_type")
        if sensor_type is None:
            return None
        sensor_type_map = {
            1: "Outdoor",
            2: "Return",
            3: "Remote",
            4: "Supply",
        }
        try:
            return sensor_type_map.get(int(sensor_type), str(sensor_type))
        except (TypeError, ValueError):
            return str(sensor_type)


class VenstarSensorNameSensor(VenstarReceiverBaseEntity, SensorEntity):
    """Sensor name decoded from packets."""

    _attr_name = "Sensor Name"
    _attr_unique_id = None

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data, entry)
        self._attr_unique_id = f"{entry.entry_id}_sensor_name"

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.data.get("sensor_info") or {}
        name = info.get("name")
        if name is None:
            return None
        return str(name)
