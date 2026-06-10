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

from .protocol import (
    AnimationTransformType,
    GaitParameterType,
    GaitType,
    KinematicStanceType,
    PacketType,
    TransformMode,
    clamp_i8,
    clamp_u8,
)

# A per-leg joint triple: (hip, knee, thigh), each an UNSIGNED byte (0..255).
JointTriple = Sequence[int]

# Real operating ranges + a verified standing pose, recovered from the app's saved
# MekaMotion animations (joint values are unsigned, ~0..255, NOT signed -128..127).
JOINT_RANGES = {"hip": (100, 200), "knee": (100, 200), "thigh": (50, 150)}
NEUTRAL_POSE = (150, 180, 125)   # (hip, knee, thigh) — all four legs at this = stand


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


def transform(forward: int, strafe: int, turn: int,
              mode: int = TransformMode.Walking) -> bytes:
    """Drive command — body transform / locomotion vector.

    Wire form (confirmed from the app's ``TransformRequest.Encode``, 5 bytes)::

        [6, mode, AxisA=forward, AxisB=strafe, AxisC=turn]

    Axis meanings were verified live on the robot:
    **AxisA = forward(+)/back(-)**, **AxisB = right(+)/left(-) strafe**, **AxisC = turn**.
    ``mode`` is the byte right after the command id (default ``Walking`` = 3, what the app's
    ``BuildMovementRequest`` uses). Each value is a signed int8, clamped to ±127.
    """
    return bytes([
        PacketType.Transform,
        clamp_i8(int(mode)),
        clamp_i8(forward),
        clamp_i8(strafe),
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

    Each joint is an **unsigned byte (0..255)** — recovered MekaMotion animations use
    Hip ~100..200, Knee ~107..200, Thigh ~50..150, with a standing pose of
    ``(hip=150, knee=180, thigh=125)`` (see :data:`NEUTRAL_POSE` / :data:`JOINT_RANGES`).
    Sending 0 is an extreme, not neutral. The app does no scaling in Encode.
    """
    payload = [int(PacketType.SetLegJointAngles)]
    for leg in (front_left, front_right, back_left, back_right):
        if len(leg) != 3:
            raise ValueError("each leg needs exactly 3 joints: (hip, knee, thigh)")
        hip, knee, thigh = leg
        payload += [clamp_u8(knee), clamp_u8(thigh), clamp_u8(hip)]  # wire order
    return bytes(payload)


def setup_joint_angles(enable: bool = True) -> bytes:
    """Enable/disable joint-angle control mode before streaming ``set_leg_joint_angles``.

    Payload ``[60, enable]``. (Exact field layout unconfirmed; ``enable`` as a flag is
    the working hypothesis — see ``docs/joint-encoding.md``.)
    """
    return bytes([PacketType.SetupJointAngles, 1 if enable else 0])


def play_animation(animation_id: int, blend_in: int = 0, blend_out: int = 0,
                   layering: int = 100,
                   transform: int = AnimationTransformType.NoTransform) -> bytes:
    """Play an animation by id. Payload (6 bytes, confirmed from ``PlayAnimation.Encode``)::

        [220, AnimationId, BlendInTime, BlendOutTime, LayeringPercent, TransformType]

    Each field is a single byte. ``animation_id`` is 0..255 (content-driven, so which ids
    map to which moves is best found by experiment). ``layering`` is a 0..100 percent;
    ``transform`` is an :class:`AnimationTransformType` (mirror/rotate the move).
    """
    return bytes([
        PacketType.PlayAnimation,
        animation_id & 0xFF,
        blend_in & 0xFF,
        blend_out & 0xFF,
        layering & 0xFF,
        int(transform) & 0xFF,
    ])


def take_steps(count: int) -> bytes:
    """Walk a fixed number of step cycles. Payload ``[224, count]`` (count 0..255)."""
    return bytes([PacketType.TakeSteps, count & 0xFF])


def kinematic_stance(stance: int = KinematicStanceType.Kinematic) -> bytes:
    """Set the body control mode. Payload ``[8, KinematicStanceType]`` (confirmed).

    ``LegJointAngles`` (5) is the mode that enables direct per-joint control.
    """
    return bytes([PacketType.KinematicStance, int(stance) & 0xFF])


def gait_set_all(params: Sequence[int]) -> bytes:
    """Set all 10 gait parameters at once. Payload (11 bytes, confirmed)::

        [13, StanceAngle, StanceDistance, WalkingSpeed, StepDuration, StepShift,
             StepHeight, GaitType, BodyHeight, CrankRandomness, StanceRandomness]

    ``params`` must be 10 bytes (0..255) in :class:`GaitParameterType` order. The app
    derives these from floats via per-parameter conversions; here they are raw bytes to
    tune by experiment (the ``GaitType`` slot uses :class:`GaitType` values, e.g. 2=Trot).
    """
    params = list(params)
    if len(params) != 10:
        raise ValueError("gait_set_all needs exactly 10 parameter bytes")
    return bytes([PacketType.GaitSetAll, *(p & 0xFF for p in params)])


def gait_set(gait_id: int, parameter: int, value: int) -> bytes:
    """Set one gait parameter. Payload ``[4, GaitId, GaitParameterType, value]`` (confirmed).

    ``parameter`` is a :class:`GaitParameterType`; ``value`` is the raw converted byte.
    """
    return bytes([PacketType.GaitSet, gait_id & 0xFF,
                  int(parameter) & 0xFF, value & 0xFF])


def twitch(direction: int, severity: int) -> bytes:
    """A small reactive jolt. Payload ``[31, Direction, Severity]`` (from struct fields)."""
    return bytes([PacketType.Twitch, clamp_i8(direction), clamp_i8(severity)])


def kill_streams() -> bytes:
    """Tell the robot to stop all of its outgoing data streams. Payload ``[247]``."""
    return bytes([PacketType.KillStreams])


def setup_heartbeat(period_ms: int = 0) -> bytes:
    """Configure the heartbeat keep-alive. Payload ``[17, ...]`` (structure unconfirmed)."""
    return bytes([PacketType.SetupHeartbeat, clamp_i8(period_ms & 0x7F)])


def neutral_joint_angles() -> bytes:
    """All four legs at the recovered standing pose (:data:`NEUTRAL_POSE`)."""
    return set_leg_joint_angles(NEUTRAL_POSE, NEUTRAL_POSE, NEUTRAL_POSE, NEUTRAL_POSE)


def gait_params_to_bytes(stance_angle=0.5, stance_distance=0.55, walking_speed=1.0,
                         step_duration=0.5, step_shift=0.7, step_height=0.7,
                         gait_type=GaitType.Trot, body_height=0.5,
                         crank_randomness=0.0, stance_randomness=0.0) -> list:
    """Convert the 10 gait parameters (floats 0..1, plus the GaitType enum) to wire bytes.

    Recovered ``.gait`` presets store these as normalised floats; the wire byte is
    ``round(value * 255)`` for every parameter except ``gait_type`` (raw enum: 2=Trot,
    4=Crawl). Order matches :class:`GaitParameterType`. Pass the result to
    :func:`gait_set_all`.
    """
    def f(x):
        return clamp_u8(max(0.0, min(1.0, float(x))) * 255)

    return [f(stance_angle), f(stance_distance), f(walking_speed), f(step_duration),
            f(step_shift), f(step_height), int(gait_type) & 0xFF, f(body_height),
            f(crank_randomness), f(stance_randomness)]


def raw(cmd_id: int, args: Iterable[int] = ()) -> bytes:
    """Escape hatch: build an arbitrary payload ``[cmd_id, *args]`` for experimentation."""
    return bytes([clamp_i8(cmd_id), *(clamp_i8(a) for a in args)])
