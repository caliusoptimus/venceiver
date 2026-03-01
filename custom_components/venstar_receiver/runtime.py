"""Runtime state for WiFi sensor receiver for Venstar."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_KEY_B64,
    ATTR_LAST_SEEN_UTC,
    ATTR_LAST_SEQUENCE,
    ATTR_LAST_TEMP_C,
    ATTR_PAIRING_UNTIL,
    ATTR_SENSOR_INFO,
    CONF_LISTEN_IP,
    CONF_LISTEN_PORT,
    CONF_PAIRED_SENSOR_INFO,
    CONF_SENSOR_KEY_B64,
    CONF_UNIT_ID_FILTER,
    DEFAULT_LISTEN_IP,
    DEFAULT_LISTEN_PORT,
    DEFAULT_PAIRING_WINDOW_SEC,
    STORAGE_VERSION,
    DOMAIN,
)
from .listener import get_shared_listener_manager
from .protocol import decode_message, hmac_b64, index_to_temp_c, normalize_mac

class VenstarReceiverRuntime:
    """Stateful UDP receiver and pairing/auth logic."""

    DUPLICATE_WINDOW_SEC = 5.0
    MAX_RECENT_PACKET_HASHES = 512

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}"
        )

        self._key_b64: str | None = None
        self._pairing_until: datetime | None = None
        self._sensor_info: dict[str, Any] = {}
        self._last_temp_c: float | None = None
        self._last_seen_utc: str | None = None
        self._last_sequence: int | None = None

        self._listener_unsubscribe: Callable[[], Awaitable[None]] | None = None
        self._recent_packet_hashes: dict[str, float] = {}
        self._state_listener: Callable[[dict[str, Any]], None] | None = None

        self._persist_pending: bool = False
        self._persist_scheduled_unsub: CALLBACK_TYPE | None = None
        self._persist_task: asyncio.Task[None] | None = None

    def set_state_listener(
        self, listener: Callable[[dict[str, Any]], None] | None
    ) -> None:
        """Set callback for push-style state updates."""
        self._state_listener = listener

    def _entry_value(self, key: str, default: Any) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    @property
    def sensor_info(self) -> dict[str, Any]:
        return dict(self._sensor_info)

    def is_pairing_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self._pairing_until is None:
            return False
        if now >= self._pairing_until:
            self._pairing_until = None
            return False
        return True

    async def async_initialize(self) -> None:
        """Load persistent state."""
        stored = await self._store.async_load() or {}
        key_b64 = stored.get(ATTR_KEY_B64)
        if isinstance(key_b64, str):
            self._key_b64 = key_b64
        else:
            entry_key = self.entry.data.get(CONF_SENSOR_KEY_B64)
            if isinstance(entry_key, str):
                self._key_b64 = entry_key

        pairing_until = stored.get(ATTR_PAIRING_UNTIL)
        if isinstance(pairing_until, str):
            try:
                self._pairing_until = datetime.fromisoformat(pairing_until)
            except ValueError:
                self._pairing_until = None

        sensor_info = stored.get(ATTR_SENSOR_INFO)
        if isinstance(sensor_info, dict):
            self._sensor_info = dict(sensor_info)
        else:
            paired_info = self.entry.data.get(CONF_PAIRED_SENSOR_INFO)
            if isinstance(paired_info, dict):
                self._sensor_info = dict(paired_info)

        last_temp = stored.get(ATTR_LAST_TEMP_C)
        if isinstance(last_temp, (int, float)):
            self._last_temp_c = float(last_temp)

        last_seen = stored.get(ATTR_LAST_SEEN_UTC)
        if isinstance(last_seen, str):
            self._last_seen_utc = last_seen

        last_sequence = stored.get(ATTR_LAST_SEQUENCE)
        if isinstance(last_sequence, int):
            self._last_sequence = last_sequence

        # Once paired, runtime should never remain in pairing mode.
        if self._key_b64:
            self._pairing_until = None

        await self._persist_state()
        self._publish_state()

    async def _persist_state(self) -> None:
        await self._store.async_save(
            {
                ATTR_KEY_B64: self._key_b64,
                ATTR_PAIRING_UNTIL: self._pairing_until.isoformat()
                if self._pairing_until
                else None,
                ATTR_SENSOR_INFO: self._sensor_info,
                ATTR_LAST_TEMP_C: self._last_temp_c,
                ATTR_LAST_SEEN_UTC: self._last_seen_utc,
                ATTR_LAST_SEQUENCE: self._last_sequence,
            }
        )

    def _schedule_persist(self) -> None:
        """Debounce state persistence to avoid write bursts."""
        self._persist_pending = True
        if self._persist_scheduled_unsub is not None:
            return

        async def _async_persist_later(_now: datetime) -> None:
            self._persist_scheduled_unsub = None
            if not self._persist_pending:
                return
            if self._persist_task is not None and not self._persist_task.done():
                self._persist_scheduled_unsub = async_call_later(
                    self.hass, 1.0, _async_persist_later
                )
                return

            self._persist_pending = False

            async def _async_run_persist() -> None:
                try:
                    await self._persist_state()
                finally:
                    self._persist_task = None
                    if self._persist_pending and self._persist_scheduled_unsub is None:
                        self._persist_scheduled_unsub = async_call_later(
                            self.hass, 1.0, _async_persist_later
                        )

            self._persist_task = self.hass.async_create_task(_async_run_persist())

        self._persist_scheduled_unsub = async_call_later(self.hass, 1.0, _async_persist_later)

    async def _flush_persist(self) -> None:
        """Force-save pending state changes."""
        if self._persist_scheduled_unsub is not None:
            self._persist_scheduled_unsub()
            self._persist_scheduled_unsub = None
        if self._persist_task is not None:
            await self._persist_task
            self._persist_task = None
        if self._persist_pending:
            self._persist_pending = False
            await self._persist_state()

    async def async_start_listener(self) -> None:
        """Start UDP listening."""
        await self.async_stop_listener()
        listen_ip = str(self._entry_value(CONF_LISTEN_IP, DEFAULT_LISTEN_IP)).strip()
        port = int(self._entry_value(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT))
        manager = get_shared_listener_manager(self.hass)
        self._listener_unsubscribe = await manager.async_subscribe(
            listen_ip, port, self.on_datagram
        )

    async def async_stop_listener(self) -> None:
        """Stop UDP listener."""
        if self._listener_unsubscribe is None:
            return
        unsubscribe = self._listener_unsubscribe
        self._listener_unsubscribe = None
        await unsubscribe()

    async def async_shutdown(self) -> None:
        """Stop background runtime work."""
        await self.async_stop_listener()
        await self._flush_persist()

    async def async_enter_pairing_mode(self) -> None:
        """Enable pairing window."""
        self._pairing_until = datetime.now(timezone.utc) + timedelta(
            seconds=DEFAULT_PAIRING_WINDOW_SEC
        )
        await self._persist_state()

    def _unit_id_allowed(self, unit_id: int) -> bool:
        selected = self._entry_value(CONF_UNIT_ID_FILTER, None)
        if selected in (None, "", "any"):
            return True
        try:
            return unit_id == int(selected)
        except (TypeError, ValueError):
            return True

    def _matches_paired_sensor(self, fields: dict[str, Any]) -> bool:
        """Ensure packets are from the paired sensor identity."""
        if not self._sensor_info:
            return True

        expected_unit_id = self._sensor_info.get("unit_id")
        if expected_unit_id is not None:
            try:
                if int(fields["unit_id"]) != int(expected_unit_id):
                    return False
            except (TypeError, ValueError, KeyError):
                return False

        expected_mac = self._sensor_info.get("mac")
        if expected_mac:
            try:
                expected_mac_norm = normalize_mac(str(expected_mac))
                packet_mac_norm = normalize_mac(str(fields.get("mac", "")))
            except ValueError:
                return False
            if packet_mac_norm != expected_mac_norm:
                return False

        return True

    def _apply_decoded_packet(self, decoded: dict[str, Any], *, auth_ok: bool) -> None:
        fields = decoded["fields"]
        unit_id = int(fields["unit_id"])
        if not self._unit_id_allowed(unit_id):
            return

        temperature_index = int(fields["temperature_index"])
        self._last_temp_c = index_to_temp_c(temperature_index)
        self._last_sequence = int(fields["sequence"])
        self._last_seen_utc = dt_util.utcnow().isoformat()

        sensor_name = str(fields["name"]).strip()
        raw_mac = str(fields["mac"]).strip()
        try:
            mac = normalize_mac(raw_mac)
        except ValueError:
            mac = raw_mac

        self._sensor_info = {
            "unit_id": unit_id,
            "name": sensor_name,
            "mac": mac,
            "sensor_type": int(fields["sensor_type"]),
            "battery_percent": int(fields["battery_percent"]),
            "auth_valid": auth_ok,
        }

        self._schedule_persist()
        self._publish_state()

    def _handle_pair_packet(self, decoded: dict[str, Any]) -> None:
        if not self.is_pairing_active():
            return
        # Runtime re-pairing is not exposed; never overwrite an existing key.
        if self._key_b64:
            return
        auth_b64 = str(decoded["auth_b64"])
        try:
            key = base64.b64decode(auth_b64, validate=True)
        except (ValueError, TypeError):
            return
        if len(key) != 32:
            return
        self._key_b64 = base64.b64encode(key).decode("ascii")
        self._apply_decoded_packet(decoded, auth_ok=True)
        self._schedule_persist()

    def _handle_update_packet(self, decoded: dict[str, Any]) -> None:
        if not self._key_b64:
            return
        if not self._matches_paired_sensor(decoded["fields"]):
            return
        try:
            key = base64.b64decode(self._key_b64, validate=True)
        except (ValueError, TypeError):
            return
        expected = hmac_b64(key, bytes.fromhex(str(decoded["info_hex"])))
        auth_ok = expected == str(decoded["auth_b64"])
        if not auth_ok:
            return
        self._apply_decoded_packet(decoded, auth_ok=True)

    def _prune_recent_hashes(self, now_monotonic: float) -> None:
        """Drop expired entries and cap memory usage."""
        cutoff = now_monotonic - self.DUPLICATE_WINDOW_SEC
        expired = [k for k, ts in self._recent_packet_hashes.items() if ts < cutoff]
        for key in expired:
            self._recent_packet_hashes.pop(key, None)

        if len(self._recent_packet_hashes) <= self.MAX_RECENT_PACKET_HASHES:
            return

        by_age = sorted(self._recent_packet_hashes.items(), key=lambda item: item[1])
        drop_count = len(self._recent_packet_hashes) - self.MAX_RECENT_PACKET_HASHES
        for key, _ts in by_age[:drop_count]:
            self._recent_packet_hashes.pop(key, None)

    def _is_duplicate_packet(self, data: bytes) -> bool:
        """Return True when the exact payload was seen very recently."""
        now_monotonic = time.monotonic()
        self._prune_recent_hashes(now_monotonic)

        digest = hashlib.blake2s(data, digest_size=16).hexdigest()
        seen_at = self._recent_packet_hashes.get(digest)
        self._recent_packet_hashes[digest] = now_monotonic
        if seen_at is None:
            return False
        return now_monotonic - seen_at <= self.DUPLICATE_WINDOW_SEC

    def on_datagram(self, data: bytes, _addr: tuple[str, int]) -> None:
        """Receive and process a datagram."""
        if self._is_duplicate_packet(data):
            return

        try:
            decoded = decode_message(data)
        except Exception:
            return

        msg_type = int(decoded["message_type"])
        if msg_type == 43:
            self._handle_pair_packet(decoded)
        elif msg_type == 42:
            self._handle_update_packet(decoded)

    def _publish_state(self) -> None:
        """Push latest state to coordinator when available."""
        if self._state_listener is None:
            return
        self._state_listener(self.snapshot())

    def snapshot(self) -> dict[str, Any]:
        """Current runtime state for coordinator consumers."""
        listen_ip = str(self._entry_value(CONF_LISTEN_IP, DEFAULT_LISTEN_IP)).strip()
        port = int(self._entry_value(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT))
        try:
            listen_ip = str(ipaddress.ip_address(listen_ip))
        except ValueError:
            pass

        return {
            "entry_id": self.entry.entry_id,
            "name": self.entry.title,
            "listen_ip": listen_ip,
            "listen_port": port,
            "pairing_active": self.is_pairing_active(),
            "pairing_until": self._pairing_until.isoformat()
            if self._pairing_until
            else None,
            "sensor_info": dict(self._sensor_info),
            "last_temperature_c": self._last_temp_c,
            "last_seen_utc": self._last_seen_utc,
            "last_sequence": self._last_sequence,
            "paired": bool(self._key_b64),
        }
