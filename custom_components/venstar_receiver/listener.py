"""Shared UDP listener manager for Venstar receiver endpoints."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from homeassistant.core import HomeAssistant

from .const import DOMAIN

DatagramCallback = Callable[[bytes, tuple[str, int]], None]


class _EndpointProtocol(asyncio.DatagramProtocol):
    """Datagram protocol that fans out packets to subscribers."""

    def __init__(self, binding: "_EndpointBinding") -> None:
        self._binding = binding

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        for callback in tuple(self._binding.subscribers):
            callback(data, addr)


@dataclass
class _EndpointBinding:
    """Socket/transport and subscriber set for one endpoint."""

    listen_ip: str
    listen_port: int
    transport: asyncio.DatagramTransport
    sock: socket.socket
    subscribers: set[DatagramCallback] = field(default_factory=set)


class SharedListenerManager:
    """Manages shared UDP listeners keyed by (listen_ip, listen_port)."""

    MULTICAST_GROUP = "224.0.0.1"

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._bindings: dict[tuple[str, int], _EndpointBinding] = {}
        self._lock = asyncio.Lock()

    async def async_subscribe(
        self,
        listen_ip: str,
        listen_port: int,
        callback: DatagramCallback,
    ) -> Callable[[], Awaitable[None]]:
        """Subscribe callback to endpoint datagrams."""
        key = (listen_ip, listen_port)
        async with self._lock:
            binding = self._bindings.get(key)
            if binding is None:
                binding = await self._async_create_binding(listen_ip, listen_port)
                self._bindings[key] = binding
            binding.subscribers.add(callback)

        async def _async_unsubscribe() -> None:
            await self.async_unsubscribe(listen_ip, listen_port, callback)

        return _async_unsubscribe

    async def async_unsubscribe(
        self,
        listen_ip: str,
        listen_port: int,
        callback: DatagramCallback,
    ) -> None:
        """Unsubscribe callback and close endpoint if no subscribers remain."""
        key = (listen_ip, listen_port)
        async with self._lock:
            binding = self._bindings.get(key)
            if binding is None:
                return
            binding.subscribers.discard(callback)
            if binding.subscribers:
                return

            binding.transport.close()
            try:
                binding.sock.close()
            except OSError:
                pass
            self._bindings.pop(key, None)

    async def _async_create_binding(
        self, listen_ip: str, listen_port: int
    ) -> _EndpointBinding:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((listen_ip, listen_port))

        group = socket.inet_aton(self.MULTICAST_GROUP)
        if listen_ip == "0.0.0.0":
            mreq = group + socket.inet_aton("0.0.0.0")
        else:
            mreq = group + socket.inet_aton(listen_ip)
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass

        sock.setblocking(False)
        binding = _EndpointBinding(
            listen_ip=listen_ip,
            listen_port=listen_port,
            transport=None,  # type: ignore[arg-type]
            sock=sock,
        )
        transport, _protocol = await self._hass.loop.create_datagram_endpoint(
            lambda: _EndpointProtocol(binding),
            sock=sock,
        )
        binding.transport = transport
        return binding


def get_shared_listener_manager(hass: HomeAssistant) -> SharedListenerManager:
    """Get or create the shared listener manager."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager = domain_data.get("listener_manager")
    if isinstance(manager, SharedListenerManager):
        return manager
    manager = SharedListenerManager(hass)
    domain_data["listener_manager"] = manager
    return manager
