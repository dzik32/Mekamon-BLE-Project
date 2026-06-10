"""High-level MekaMon controller with a background asyncio loop.

The GUI runs on the main thread; Bleak needs an asyncio event loop. This class owns a
private event loop on a daemon thread and exposes **synchronous** methods the GUI can
call directly. A streaming task continuously re-sends the current drive vector (or joint
pose) at a fixed rate, which is how the robot expects to be driven.

Typical use::

    ctl = MekamonController()
    for dev in ctl.scan():
        print(dev.name, dev.address, dev.likely_mekamon)
    ctl.connect(dev.address)        # runs the handshake, starts streaming
    ctl.set_drive(strafe=0, forward=60, turn=0)   # walk forward
    ctl.set_head_colour(0, 80, 255)
    ...
    ctl.stop()                      # neutral + kill streams
    ctl.shutdown()
"""
from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional, Sequence

from . import commands
from .ble import FoundDevice, MekamonBLE, scan as _scan
from .protocol import PacketType

Mode = str  # "drive" | "joint" | "idle"


class MekamonController:
    def __init__(self, stream_hz: float = 10.0) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="mekamon-ble", daemon=True
        )
        self._thread.start()

        self.ble = MekamonBLE(
            on_response=self._handle_response,
            on_disconnect=self._handle_disconnect,
        )
        self._stream_period = 1.0 / stream_hz
        self._stream_task: Optional[asyncio.Task] = None

        # streamed state
        self._mode: Mode = "idle"
        self._drive = (0, 0, 0)                       # forward, strafe, turn
        self._joints = ((0, 0, 0),) * 4               # FL, FR, BL, BR

        # user callbacks (called from the BLE thread — marshal to GUI yourself)
        self.on_response: Optional[Callable[[PacketType, bytes, bool], None]] = None
        self.on_connection_changed: Optional[Callable[[bool], None]] = None

    # ------------------------------------------------------------------ #
    #  event-loop plumbing
    # ------------------------------------------------------------------ #
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout: Optional[float] = 30.0):
        """Schedule *coro* on the BLE loop and block until it finishes."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _spawn(self, coro) -> None:
        """Fire-and-forget *coro* on the BLE loop (no waiting)."""
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ------------------------------------------------------------------ #
    #  connection
    # ------------------------------------------------------------------ #
    def scan(self, timeout: float = 6.0) -> list[FoundDevice]:
        return self._call(_scan(timeout), timeout=timeout + 10)

    def connect(self, address_or_device, do_handshake: bool = True) -> None:
        self._call(self._connect(address_or_device, do_handshake), timeout=40)

    async def _connect(self, address_or_device, do_handshake: bool) -> None:
        await self.ble.connect(address_or_device)
        if self.on_connection_changed:
            self.on_connection_changed(True)
        if do_handshake:
            await self._handshake()
        self._start_stream()

    async def _handshake(self) -> None:
        # ConnectionEstablished -> GameState(1) -> Transform neutral, ~0.5 s apart.
        await self.ble.send_payload(commands.connection_established())
        await asyncio.sleep(0.5)
        await self.ble.send_payload(commands.game_state(1))
        await asyncio.sleep(0.5)
        await self.ble.send_payload(commands.transform(0, 0, 0))
        await asyncio.sleep(0.2)
        self._mode = "drive"

    def disconnect(self) -> None:
        self._stop_stream()
        self._call(self.ble.disconnect(), timeout=10)

    @property
    def is_connected(self) -> bool:
        return self.ble.is_connected

    # ------------------------------------------------------------------ #
    #  streaming
    # ------------------------------------------------------------------ #
    def _start_stream(self) -> None:
        if self._stream_task is None or self._stream_task.done():
            self._stream_task = self._loop.create_task(self._stream())

    def _stop_stream(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            self._stream_task = None

    async def _stream(self) -> None:
        try:
            while self.ble.is_connected:
                if self._mode == "drive":
                    forward, strafe, turn = self._drive
                    await self.ble.send_payload(
                        commands.transform(forward, strafe, turn)
                    )
                elif self._mode == "joint":
                    fl, fr, bl, br = self._joints
                    await self.ble.send_payload(
                        commands.set_leg_joint_angles(fl, fr, bl, br)
                    )
                await asyncio.sleep(self._stream_period)
        except asyncio.CancelledError:
            pass
        except Exception:
            # link dropped mid-send; the disconnect callback handles UI state.
            pass

    # ------------------------------------------------------------------ #
    #  high-level commands (safe to call from the GUI thread)
    # ------------------------------------------------------------------ #
    def set_mode(self, mode: Mode) -> None:
        """Switch the streamed command between 'drive', 'joint', and 'idle'."""
        self._mode = mode
        if mode == "joint":
            # best-effort: enable joint-angle control before streaming poses
            self._spawn(self.ble.send_payload(commands.setup_joint_angles(True)))

    def set_drive(self, forward: int, strafe: int, turn: int) -> None:
        """Set the streamed drive vector. forward(+)/back(-), strafe right(+)/left(-), turn."""
        self._drive = (int(forward), int(strafe), int(turn))
        if self._mode != "drive":
            self.set_mode("drive")

    def set_joints(
        self,
        front_left: Sequence[int],
        front_right: Sequence[int],
        back_left: Sequence[int],
        back_right: Sequence[int],
    ) -> None:
        self._joints = (
            tuple(front_left), tuple(front_right),
            tuple(back_left), tuple(back_right),
        )
        if self._mode != "joint":
            self.set_mode("joint")

    def set_head_colour(self, r: int, g: int, b: int) -> None:
        self.send_payload(commands.head_colour(r, g, b))

    def play_animation(self, animation_id: int, blend_in: int = 0, blend_out: int = 0,
                       layering: int = 100, transform: int = 0) -> None:
        self.send_payload(commands.play_animation(
            animation_id, blend_in, blend_out, layering, transform))

    def take_steps(self, count: int) -> None:
        self.send_payload(commands.take_steps(count))

    def kinematic_stance(self, stance: int) -> None:
        self.send_payload(commands.kinematic_stance(stance))

    def gait_set_all(self, params) -> None:
        self.send_payload(commands.gait_set_all(params))

    def twitch(self, direction: int, severity: int) -> None:
        self.send_payload(commands.twitch(direction, severity))

    def send_payload(self, payload: bytes) -> None:
        """Send any raw payload (no-op if not connected). See ``commands.raw``."""
        if self.is_connected:
            self._spawn(self.ble.send_payload(payload))

    def stop(self) -> None:
        """Emergency stop: zero the drive vector and ask the robot to halt streams."""
        self._drive = (0, 0, 0)
        self._mode = "drive"
        self._spawn(self.ble.send_payload(commands.transform(0, 0, 0)))
        self._spawn(self.ble.send_payload(commands.kill_streams()))

    # ------------------------------------------------------------------ #
    #  internal callbacks
    # ------------------------------------------------------------------ #
    def _handle_response(self, ptype: PacketType, payload: bytes, ok: bool) -> None:
        if self.on_response:
            self.on_response(ptype, payload, ok)

    def _handle_disconnect(self) -> None:
        self._mode = "idle"
        if self.on_connection_changed:
            self.on_connection_changed(False)

    # ------------------------------------------------------------------ #
    #  lifecycle
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """Stop streaming, disconnect, and tear down the background loop."""
        try:
            if self.ble.is_connected:
                self.disconnect()
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
