"""Coordinator for Venstar receiver UI state."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .runtime import VenstarReceiverRuntime


class VenstarReceiverCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll runtime snapshot for entities."""

    def __init__(self, hass: HomeAssistant, runtime: VenstarReceiverRuntime) -> None:
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=f"{DOMAIN}_{runtime.entry.entry_id}",
            update_interval=None,
        )
        self.runtime = runtime

    async def _async_update_data(self) -> dict[str, Any]:
        return self.runtime.snapshot()
