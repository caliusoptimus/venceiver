"""Base entity helpers for Venstar receiver."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, IntegrationData


class VenstarReceiverBaseEntity(CoordinatorEntity):
    """Base class for all integration entities."""

    _attr_has_entity_name = True

    def __init__(self, data: IntegrationData, entry: ConfigEntry) -> None:
        super().__init__(data.coordinator)
        self._data = data
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Venstar",
            model="ACC-TSENWIFI Receiver",
            sw_version="1.0",
        )

    @property
    def runtime(self):
        return self._data.runtime
