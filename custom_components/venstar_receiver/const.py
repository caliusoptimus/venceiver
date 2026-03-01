"""Constants for WiFi sensor receiver for Venstar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .coordinator import VenstarReceiverCoordinator
    from .runtime import VenstarReceiverRuntime

DOMAIN: Final = "venstar_receiver"

CONF_LISTEN_IP: Final = "listen_ip"
CONF_LISTEN_PORT: Final = "listen_port"
CONF_UNIT_ID_FILTER: Final = "unit_id_filter"
CONF_SENSOR_KEY_B64: Final = "sensor_key_b64"
CONF_PAIRED_SENSOR_INFO: Final = "paired_sensor_info"

DEFAULT_NAME: Final = "WiFi Sensor Receiver for Venstar"
DEFAULT_LISTEN_IP: Final = "0.0.0.0"
DEFAULT_LISTEN_PORT: Final = 5001
DEFAULT_PAIRING_WINDOW_SEC: Final = 300

STORAGE_VERSION: Final = 1

ATTR_KEY_B64: Final = "key_b64"
ATTR_PAIRING_UNTIL: Final = "pairing_until"
ATTR_SENSOR_INFO: Final = "sensor_info"
ATTR_LAST_TEMP_C: Final = "last_temp_c"
ATTR_LAST_SEEN_UTC: Final = "last_seen_utc"
ATTR_LAST_SEQUENCE: Final = "last_sequence"

PLATFORMS: Final = ["sensor"]


@dataclass
class IntegrationData:
    """Runtime objects associated with a config entry."""

    runtime: VenstarReceiverRuntime
    coordinator: VenstarReceiverCoordinator
