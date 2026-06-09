"""Bleak transport for the MekaMon's Nordic UART Service (NUS).

The robot exposes a standard Nordic UART Service. We write command frames to the RX
characteristic and subscribe to the TX characteristic for responses.

    Service : 6e400001-b5a3-f393-e0a9-e50e24dcca9e
    RX write: 6e400002-b5a3-f393-e0a9-e50e24dcca9e   (app -> robot)
    TX notify: 6e400003-b5a3-f393-e0a9-e50e24dcca9e  (robot -> app)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from . import protocol
from .protocol import PacketType

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # write (app -> robot)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # notify (robot -> app)


@dataclass
class FoundDevice:
    """A discovered BLE device and whether it looks like a MekaMon."""

    name: str
    address: str
    rssi: Optional[int]
    has_nus: bool
    device: BLEDevice

    @property
    def likely_mekamon(self) -> bool:
        name = (self.name or "").lower()
        return self.has_nus or "meka" in name or "reach" in name


async def scan(timeout: float = 6.0) -> list[FoundDevice]:
    """Scan for BLE devices and flag the ones advertising the Nordic UART Service.

    MekaMons may or may not advertise NUS in the advertisement packet depending on
    state, so this returns *all* devices with ``likely_mekamon`` computed; the caller
    can show the full list and let the user pick.
    """
    found: dict[str, FoundDevice] = {}

    def callback(device: BLEDevice, adv) -> None:
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        found[device.address] = FoundDevice(
            name=device.name or adv.local_name or "(unknown)",
            address=device.address,
            rssi=getattr(adv, "rssi", None),
            has_nus=NUS_SERVICE in uuids,
            device=device,
        )

    scanner = BleakScanner(detection_callback=callback)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    # Sort: likely Mekamons first, then by signal strength.
    return sorted(
        found.values(),
        key=lambda d: (not d.likely_mekamon, -(d.rssi or -999)),
    )


# Callback signature: (PacketType, payload_bytes, checksum_ok) -> None
ResponseHandler = Callable[[PacketType, bytes, bool], None]


class MekamonBLE:
    """A thin async wrapper around a connected MekaMon's NUS link."""

    def __init__(self, on_response: Optional[ResponseHandler] = None,
                 on_disconnect: Optional[Callable[[], None]] = None) -> None:
        self._client: Optional[BleakClient] = None
        self._rx_buffer = bytearray()
        self.on_response = on_response
        self.on_disconnect = on_disconnect
        self._write_response = False   # NUS is write-without-response

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    async def connect(self, address_or_device, timeout: float = 20.0) -> None:
        def _disc(_client):
            if self.on_disconnect:
                self.on_disconnect()

        self._client = BleakClient(
            address_or_device, timeout=timeout, disconnected_callback=_disc
        )
        await self._client.connect()
        await self._client.start_notify(NUS_TX, self._on_notify)
        # Probe whether the RX characteristic supports write-without-response.
        try:
            svcs = self._client.services
            ch = svcs.get_characteristic(NUS_RX)
            self._write_response = "write-without-response" not in (ch.properties or [])
        except Exception:
            self._write_response = False

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                if self._client.is_connected:
                    await self._client.stop_notify(NUS_TX)
                    await self._client.disconnect()
            finally:
                self._client = None

    async def send_payload(self, payload: bytes) -> None:
        """Frame and write a raw payload (``[cmd_id, *args]``) to the robot."""
        await self.send_frame(protocol.build_frame(payload))

    async def send_frame(self, frame: bytes) -> None:
        """Write an already-built on-wire frame to the RX characteristic."""
        if not self.is_connected:
            raise RuntimeError("not connected")
        await self._client.write_gatt_char(NUS_RX, frame, response=self._write_response)

    def _on_notify(self, _sender, data: bytearray) -> None:
        self._rx_buffer.extend(data)
        frames, remainder = protocol.split_frames(bytes(self._rx_buffer))
        self._rx_buffer = bytearray(remainder)
        if not self.on_response:
            return
        for raw in frames:
            payload, ok = protocol.parse_frame(raw)
            if payload:
                self.on_response(PacketType(payload[0]), payload, ok)
