"""High-level builders for Hermes command payloads.

Each function returns the *raw payload* (``bytes([cmd_id, *args])``) — wrap it with
:func:`mekamon.protocol.build_frame` before sending, or just hand it to
:class:`mekamon.controller.MekamonController`, which frames it for you.

Byte-exactness notes
--------------------
* ``connection_established``, ``game_state``, ``transform``, ``head_colour`` are
  byte-verified against the official app and the proven Hackaday driver.
* ``set_leg_joint_angles`` has a **confirmed structure**: 13-byte payload, 12 signed
  int8 joints (``UnstuffedLength == 13`` in the decompile). The angle *scaling/units*
  of each int8 still need live calibration on the robot — see ``docs/joint-encoding.md``.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from .protocol import PacketType, TransformMode, clamp_i8

# A per-leg joint triple: (hip, knee, thigh), each a signed int8 (-128..127).
JointTriple = Sequence[int]


def connection_established() -> bytes:
    """Handshake step 1 — tell the robot a controller has connected. Payload ``[16]``."""
    return bytes([PacketType.ConnectionEstablished])


def game_state(state: int = 1, force_defaults: int | None = None) -> bytes:
    """Handshake step 2 — set the game/control state (1 = active / free-drive).

    Payload ``[7, state]`` or ``[7, state, force_defaults]``.
    """
    if force_defaults is None:
        return bytes([PacketType.GameState, clamp_i8(state)])
    return bytes([PacketType.GameState, clamp_i8(state), clamp_i8(force_defaults)])


def transform(strafe: int, forward: int, turn: int,
              mode: int = TransformMode.Walking) -> bytes:
    """Drive command — body transform / locomotion vector.

    Wire form (confirmed from the app's ``TransformRequest.Encode``, 5 bytes)::

        [6, mode, strafe, forward, turn]

    ``mode`` is the byte **right after** the command id (default ``Walking`` = 3, which is
    what the app's ``BuildMovementRequest`` uses for joystick driving). ``strafe`` =
    AxisA (left/right), ``forward`` = AxisB, ``turn`` = AxisC — each a signed int8,
    clamped to ±127 (the app clamps to ±127.0 in dead-reckoning).
    """
    return bytes([
        PacketType.Transform,
        clamp_i8(int(mode)),
        clamp_i8(strafe),
        clamp_i8(forward),
        clamp_i8(turn),
    ])


def head_colour(r: int, g: int, b: int) -> bytes:
    """Set the head RGB LED. Payload ``[46, R, G, B]`` (each 0..255)."""
    return bytes([PacketType.HeadColourSet, r & 0xFF, g & 0xFF, b & 0xFF])


def set_leg_joint_angles(
    front_left: JointTriple,
    front_right: JointTriple,
    back_left: JointTriple,
    back_right: JointTriple,
) -> bytes:
    """Directly command all 12 joints (4 legs x {hip, knee, thigh}).

    Each ``leg`` argument is given in the **intuitive ``(hip, knee, thigh)`` order**, but
    the app serialises each leg on the wire as **knee, thigh, hip** (confirmed from
    ``SetLegJointAngles.Encode``: it reads struct offsets +4, +8, +0). So the 13-byte
    payload is::

        [58, FL.knee, FL.thigh, FL.hip,
             FR.knee, FR.thigh, FR.hip,
             BL.knee, BL.thigh, BL.hip,
             BR.knee, BR.thigh, BR.hip]

    Each joint is the low byte of the angle (signed int8); the app does no scaling in
    Encode (it clamps to an "acceptable range" beforehand). Units still need live
    calibration — start near 0 and move one joint at a time.
    """
    payload = [int(PacketType.SetLegJointAngles)]
    for leg in (front_left, front_right, back_left, back_right):
        if len(leg) != 3:
            raise ValueError("each leg needs exactly 3 joints: (hip, knee, thigh)")
        hip, knee, thigh = leg
        payload += [clamp_i8(knee), clamp_i8(thigh), clamp_i8(hip)]  # wire order
    return bytes(payload)


def setup_joint_angles(enable: bool = True) -> bytes:
    """Enable/disable joint-angle control mode before streaming ``set_leg_joint_angles``.

    Payload ``[60, enable]``. (Exact field layout unconfirmed; ``enable`` as a flag is
    the working hypothesis — see ``docs/joint-encoding.md``.)
    """
    return bytes([PacketType.SetupJointAngles, 1 if enable else 0])


def play_animation(animation_id: int) -> bytes:
    """Play a built-in animation by id. Payload ``[220, animation_id, ...]``.

    Only the leading ``animation_id`` byte is confirmed; blend/layer fields are
    appended as zeros by default.
    """
    return bytes([PacketType.PlayAnimation, clamp_i8(animation_id)])


def take_steps(count: int) -> bytes:
    """Walk a fixed number of steps. Payload ``[224, count]`` (structure unconfirmed)."""
    return bytes([PacketType.TakeSteps, clamp_i8(count)])


def kill_streams() -> bytes:
    """Tell the robot to stop all of its outgoing data streams. Payload ``[247]``."""
    return bytes([PacketType.KillStreams])


def setup_heartbeat(period_ms: int = 0) -> bytes:
    """Configure the heartbeat keep-alive. Payload ``[17, ...]`` (structure unconfirmed)."""
    return bytes([PacketType.SetupHeartbeat, clamp_i8(period_ms & 0x7F)])


def neutral_joint_angles() -> bytes:
    """All 12 joints at 0 (a safe-ish neutral). Calibrate the true rest pose live."""
    z = (0, 0, 0)
    return set_leg_joint_angles(z, z, z, z)


def raw(cmd_id: int, args: Iterable[int] = ()) -> bytes:
    """Escape hatch: build an arbitrary payload ``[cmd_id, *args]`` for experimentation."""
    return bytes([clamp_i8(cmd_id), *(clamp_i8(a) for a in args)])
