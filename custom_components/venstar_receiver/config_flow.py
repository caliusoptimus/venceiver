"""Config flow for Venstar WiFi sensor receiver."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LISTEN_IP,
    CONF_LISTEN_PORT,
    CONF_PAIRED_SENSOR_INFO,
    CONF_SENSOR_KEY_B64,
    CONF_UNIT_ID_FILTER,
    DEFAULT_LISTEN_IP,
    DEFAULT_LISTEN_PORT,
    DEFAULT_NAME,
    DEFAULT_PAIRING_WINDOW_SEC,
    DOMAIN,
)
from .listener import get_shared_listener_manager
from .protocol import decode_message, index_to_temp_c, normalize_mac

OptionsFlowBase = getattr(
    config_entries, "OptionsFlowWithReload", config_entries.OptionsFlow
)


def _unit_id_selector() -> selector.SelectSelector:
    options = [selector.SelectOptionDict(value="any", label="Any")]
    options.extend(
        selector.SelectOptionDict(value=str(n), label=str(n)) for n in range(1, 21)
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
            vol.Required(CONF_LISTEN_IP, default=defaults[CONF_LISTEN_IP]): str,
            vol.Required(CONF_LISTEN_PORT, default=defaults[CONF_LISTEN_PORT]): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(
                CONF_UNIT_ID_FILTER, default=defaults[CONF_UNIT_ID_FILTER]
            ): _unit_id_selector(),
        }
    )


def _normalize_ip(ip_text: str) -> str:
    ip_text = ip_text.strip()
    ipaddress.IPv4Address(ip_text)
    return ip_text


def _unit_id_allowed(selected: Any, unit_id: int) -> bool:
    if selected in (None, "", "any"):
        return True
    try:
        return unit_id == int(selected)
    except (TypeError, ValueError):
        return True


class VenstarReceiverConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle receiver integration setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._pending_title: str = DEFAULT_NAME
        self._pending_data: dict[str, Any] | None = None
        self._pairing_deadline: datetime | None = None
        self._pair_capture: dict[str, Any] | None = None
        self._pair_result: str | None = None
        self._pair_wait_task: asyncio.Task[None] | None = None
        self._pair_unsubscribe: Callable[[], Awaitable[None]] | None = None

    def _reset_pairing_state(self) -> None:
        self._pairing_deadline = None
        self._pair_capture = None
        self._pair_result = None

    def _on_pairing_datagram(self, payload: bytes, _addr: tuple[str, int]) -> None:
        if self._pending_data is None or self._pair_capture is not None:
            return
        try:
            decoded = decode_message(payload)
        except Exception:
            return
        if int(decoded["message_type"]) != 43:
            return

        fields = decoded["fields"]
        unit_id = int(fields["unit_id"])
        if not _unit_id_allowed(self._pending_data.get(CONF_UNIT_ID_FILTER), unit_id):
            return

        auth_b64 = str(decoded["auth_b64"])
        try:
            key = base64.b64decode(auth_b64, validate=True)
        except (ValueError, TypeError):
            return
        if len(key) != 32:
            return
        key_b64 = base64.b64encode(key).decode("ascii")

        mac_raw = str(fields["mac"]).strip()
        try:
            mac = normalize_mac(mac_raw)
        except ValueError:
            mac = mac_raw

        self._pair_capture = {
            CONF_SENSOR_KEY_B64: key_b64,
            CONF_PAIRED_SENSOR_INFO: {
                "unit_id": unit_id,
                "name": str(fields["name"]).strip(),
                "mac": mac,
                "sensor_type": int(fields["sensor_type"]),
                "battery_percent": int(fields["battery_percent"]),
            },
            "last_temperature_c": index_to_temp_c(int(fields["temperature_index"])),
            "last_sequence": int(fields["sequence"]),
            "last_seen_utc": dt_util.utcnow().isoformat(),
        }

    def _pairing_timed_out(self) -> bool:
        if self._pairing_deadline is None:
            return True
        return datetime.now(timezone.utc) >= self._pairing_deadline

    async def _async_stop_pair_listener(self) -> None:
        if self._pair_unsubscribe is None:
            return
        unsubscribe = self._pair_unsubscribe
        self._pair_unsubscribe = None
        await unsubscribe()

    async def _async_stop_pair_wait_task(self) -> None:
        if self._pair_wait_task is None:
            return
        self._pair_wait_task.cancel()
        try:
            await self._pair_wait_task
        except asyncio.CancelledError:
            pass
        self._pair_wait_task = None

    async def _async_start_pair_listener(self) -> None:
        if self._pending_data is None:
            return
        await self._async_stop_pair_listener()

        listen_ip = str(self._pending_data[CONF_LISTEN_IP]).strip()
        listen_port = int(self._pending_data[CONF_LISTEN_PORT])
        manager = get_shared_listener_manager(self.hass)
        self._pair_unsubscribe = await manager.async_subscribe(
            listen_ip, listen_port, self._on_pairing_datagram
        )
        self._pairing_deadline = datetime.now(timezone.utc) + timedelta(
            seconds=DEFAULT_PAIRING_WINDOW_SEC
        )

    async def _async_wait_for_pairing_result(self) -> None:
        """Wait until pairing packet is captured or timeout is reached."""
        try:
            while True:
                if self._pair_capture is not None:
                    self._pair_result = "complete"
                    break
                if self._pairing_timed_out():
                    self._pair_result = "timeout"
                    break
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            self._pair_result = None
            raise
        finally:
            await self._async_stop_pair_listener()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        defaults = {
            CONF_NAME: DEFAULT_NAME,
            CONF_LISTEN_IP: DEFAULT_LISTEN_IP,
            CONF_LISTEN_PORT: DEFAULT_LISTEN_PORT,
            CONF_UNIT_ID_FILTER: "any",
        }

        if user_input is not None:
            cleaned = dict(user_input)
            try:
                cleaned[CONF_LISTEN_IP] = _normalize_ip(str(cleaned[CONF_LISTEN_IP]))
            except ValueError:
                errors["base"] = "invalid_listen_ip"

            if not errors:
                self._pending_title = str(cleaned.pop(CONF_NAME)).strip() or DEFAULT_NAME
                self._pending_data = cleaned
                await self._async_stop_pair_wait_task()
                self._reset_pairing_state()
                await self._async_stop_pair_listener()
                return await self.async_step_pair_ready()

            defaults.update(user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(defaults),
            errors=errors,
        )

    async def async_step_pair_ready(self, user_input: dict[str, Any] | None = None):
        if self._pending_data is None:
            return self.async_abort(reason="pairing_context_missing")
        return self.async_show_menu(
            step_id="pair_ready",
            menu_options={"pair_start": "Pair", "pair_cancel": "Cancel"},
        )

    async def async_step_pair_start(self, user_input: dict[str, Any] | None = None):
        if self._pending_data is None:
            return self.async_abort(reason="pairing_context_missing")
        try:
            await self._async_start_pair_listener()
            await self._async_stop_pair_wait_task()
            self._pair_wait_task = self.hass.async_create_task(
                self._async_wait_for_pairing_result()
            )
        except OSError:
            await self._async_stop_pair_wait_task()
            await self._async_stop_pair_listener()
            self._pending_data = None
            self._reset_pairing_state()
            return self.async_abort(reason="pairing_listen_failed")
        return await self.async_step_pairing_active()

    async def async_step_pairing_active(
        self, user_input: dict[str, Any] | None = None
    ):
        if self._pending_data is None:
            return self.async_abort(reason="pairing_context_missing")
        if self._pair_wait_task is None:
            return self.async_abort(reason="pairing_context_missing")

        if self._pair_wait_task.done():
            await self._async_stop_pair_wait_task()
            if self._pair_result == "complete":
                return self.async_show_progress_done(next_step_id="pair_complete")
            if self._pair_result == "timeout":
                return self.async_show_progress_done(next_step_id="pair_timeout")
            return self.async_abort(reason="pairing_context_missing")

        return self.async_show_progress(
            step_id="pairing_active",
            progress_action="listening",
            progress_task=self._pair_wait_task,
        )

    async def async_step_pair_finish(self, user_input: dict[str, Any] | None = None):
        if self._pending_data is None or self._pair_capture is None:
            return self.async_abort(reason="pairing_context_missing")

        await self._async_stop_pair_wait_task()
        await self._async_stop_pair_listener()

        data = dict(self._pending_data)
        data[CONF_SENSOR_KEY_B64] = self._pair_capture[CONF_SENSOR_KEY_B64]
        data[CONF_PAIRED_SENSOR_INFO] = self._pair_capture[CONF_PAIRED_SENSOR_INFO]
        sensor_mac = str(self._pair_capture[CONF_PAIRED_SENSOR_INFO].get("mac", "")).strip()
        if sensor_mac:
            await self.async_set_unique_id(f"{DOMAIN}:{sensor_mac}")
            self._abort_if_unique_id_configured()

        title = self._pending_title
        self._pending_data = None
        self._reset_pairing_state()
        return self.async_create_entry(title=title, data=data)

    async def async_step_pair_complete(self, user_input: dict[str, Any] | None = None):
        if self._pending_data is None or self._pair_capture is None:
            return self.async_abort(reason="pairing_context_missing")
        return self.async_show_menu(
            step_id="pair_complete",
            menu_options={"pair_finish": "Finish"},
        )

    async def async_step_pair_timeout(self, user_input: dict[str, Any] | None = None):
        if self._pending_data is None:
            return self.async_abort(reason="pairing_context_missing")
        return self.async_show_menu(
            step_id="pair_timeout",
            menu_options={"pair_start": "Pair Again", "pair_cancel": "Cancel"},
        )

    async def async_step_pair_cancel(self, user_input: dict[str, Any] | None = None):
        await self._async_stop_pair_wait_task()
        await self._async_stop_pair_listener()
        self._pending_data = None
        self._reset_pairing_state()
        return self.async_abort(reason="pairing_cancelled")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VenstarReceiverOptionsFlow()


class VenstarReceiverOptionsFlow(OptionsFlowBase):
    """Handle options flow."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        defaults = {
            CONF_NAME: self.config_entry.title,
            CONF_LISTEN_IP: self.config_entry.options.get(
                CONF_LISTEN_IP, self.config_entry.data.get(CONF_LISTEN_IP, DEFAULT_LISTEN_IP)
            ),
            CONF_LISTEN_PORT: self.config_entry.options.get(
                CONF_LISTEN_PORT,
                self.config_entry.data.get(CONF_LISTEN_PORT, DEFAULT_LISTEN_PORT),
            ),
            CONF_UNIT_ID_FILTER: self.config_entry.options.get(
                CONF_UNIT_ID_FILTER,
                self.config_entry.data.get(CONF_UNIT_ID_FILTER, "any"),
            ),
        }
        errors: dict[str, str] = {}

        if user_input is not None:
            cleaned = dict(user_input)
            try:
                cleaned[CONF_LISTEN_IP] = _normalize_ip(str(cleaned[CONF_LISTEN_IP]))
            except ValueError:
                errors["base"] = "invalid_listen_ip"

            if not errors:
                title = str(cleaned.pop(CONF_NAME)).strip() or DEFAULT_NAME
                if title != self.config_entry.title:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, title=title
                    )
                return self.async_create_entry(title="", data=cleaned)

            defaults.update(user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(defaults),
            errors=errors,
        )
