"""MekaMon "Hermes" wire protocol: COBS framing, checksum, and the PacketType enum.

Reverse-engineered from the official MekaMon Android app (v2.3.0, Unity IL2CPP) and
cross-checked against Wes Freeman's working Hackaday driver. See ``MEKAMON_PROTOCOL.md``.

Frame on the wire::

    wire = COBS(payload) + checksum + 0x00

where::

    payload  = bytes([cmd_id, *args])        # each value a signed byte, -128..127
    checksum = (sum(cobs_encoded_bytes) + 1) & 0xFF
    0x00     = frame terminator

The COBS step removes every 0x00 from the body so the single trailing 0x00 is an
unambiguous frame delimiter.

These three frames are verified byte-exact (see ``tests/test_protocol.py``)::

    ConnectionEstablished  [16]        -> 02 10 13 00
    GameState(1)           [7, 1]      -> 03 07 01 0C 00
    Transform neutral      [6, 0, 0, 0]-> 02 06 01 01 01 0C 00
"""
from __future__ import annotations

from enum import IntEnum

FRAME_DELIMITER = 0x00


# --------------------------------------------------------------------------- #
#  COBS (Constant Overhead Byte Stuffing)
# --------------------------------------------------------------------------- #
def cobs_encode(data: bytes) -> bytes:
    """Encode *data* with COBS, removing all zero bytes from the body."""
    out = bytearray([0])          # placeholder for the first code byte
    code_idx = 0
    code = 1
    for b in data:
        if b == 0:
            out[code_idx] = code
            code_idx = len(out)
            out.append(0)         # next placeholder
            code = 1
        else:
            out.append(b)
            code += 1
            if code == 0xFF:      # max run length reached
                out[code_idx] = code
                code_idx = len(out)
                out.append(0)
                code = 1
    out[code_idx] = code
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """Decode a COBS body (the bytes *before* the checksum/terminator)."""
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        code = data[i]
        if code == 0:             # unexpected delimiter inside the body
            break
        i += 1
        for _ in range(code - 1):
            if i >= n:
                break
            out.append(data[i])
            i += 1
        if code < 0xFF and i < n:
            out.append(0)
    return bytes(out)


# --------------------------------------------------------------------------- #
#  Framing
# --------------------------------------------------------------------------- #
def checksum(cobs_bytes: bytes) -> int:
    """Hermes checksum = (sum(cobs bytes) mod 255) + 1.

    Confirmed by disassembling ``HermesPacket.CalculateChecksum`` (the native code uses
    the 0x80808081 magic-number divide-by-255). The result is always in **1..255**, so it
    can never equal the 0x00 frame terminator. (An earlier ``(sum + 1) mod 256`` guess is
    only correct while the byte sum stays below 255 — it diverges for larger frames such as
    a bright head colour.)
    """
    return (sum(cobs_bytes) % 255) + 1


def build_frame(payload: bytes | list[int]) -> bytes:
    """Wrap a raw *payload* (``[cmd_id, *args]``) into a full on-wire frame.

    Each value is masked to a byte (``& 0xFF``); negatives are taken as two's
    complement (``-5`` -> ``0xFB``). Signed-range clamping belongs to the command
    builders, not here, so that unsigned fields (colours, ids) survive intact.
    """
    payload = bytes(b & 0xFF for b in payload)
    cobs = cobs_encode(payload)
    return cobs + bytes([checksum(cobs), FRAME_DELIMITER])


def parse_frame(frame_without_terminator: bytes) -> tuple[bytes, bool]:
    """Decode one received frame (COBS body + checksum, terminator already stripped).

    Returns ``(payload, checksum_ok)``.
    """
    if not frame_without_terminator:
        return b"", False
    cobs, chk = frame_without_terminator[:-1], frame_without_terminator[-1]
    ok = checksum(cobs) == chk
    return cobs_decode(cobs), ok


def split_frames(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Split a notification *buffer* into complete frames on the 0x00 delimiter.

    Returns ``(frames, remainder)`` where each frame still includes its checksum
    byte (pass it to :func:`parse_frame`) and *remainder* is the trailing partial
    frame to carry over to the next read.
    """
    frames, start = [], 0
    for i, b in enumerate(buffer):
        if b == FRAME_DELIMITER:
            if i > start:
                frames.append(buffer[start:i])
            start = i + 1
    return frames, buffer[start:]


def clamp_i8(value: int) -> int:
    """Clamp to signed int8 range and return the unsigned byte (0..255)."""
    v = max(-128, min(127, int(round(value))))
    return v & 0xFF


# --------------------------------------------------------------------------- #
#  PacketType enum  (full command table from dump.cs:440705)
# --------------------------------------------------------------------------- #
class PacketType(IntEnum):
    """Hermes command / response identifiers (the first byte of every payload)."""

    # ---- requests (host -> robot) ----
    Unknown = 0
    AddonGet = 1
    SetupCompass = 3
    GaitSet = 4
    SetupInfrared = 5
    Transform = 6                 # drive / body transform
    GameState = 7
    KinematicStance = 8
    AnimationComponent = 9
    SetupBattery = 10
    RobotFirmwareVersion = 11
    GaitSetAll = 13
    GaitGetAll = 14
    ConnectionEstablished = 16
    SetupHeartbeat = 17
    Twitch = 31
    RobotSerialNumber = 34
    LegSerialNumber = 35
    AddonSerialNumber = 36
    LegVersion = 37
    InfraredIntensitySet = 39
    InfraredIntensityGet = 40
    RobotStatisticGet = 43
    LegStatisticsTriggerGetAll = 44
    LegStatisticGet = 45
    HeadColourSet = 46            # head RGB LED
    HeadColourGet = 47
    SetLegJointAngles = 58        # DIRECT 12-DOF per-joint control
    SetLegControlPoint = 59       # Cartesian foot target
    SetupJointAngles = 60         # enable joint-angle streaming
    SetLegCompliance = 61
    EventEducational = 199
    ImuReset = 208
    SetupIsOnFloor = 218
    PlayAnimation = 220
    PlayAnimationHold = 221
    PlayAnimationLoop = 222
    TakeSteps = 224
    ClearOdometry = 225
    SetupOdometry = 227
    AnimationControls = 229
    HeadModeSet = 230
    KinematicStanceExtended = 232
    HeadFlashingSet = 234
    SetLegDamage = 236
    DirectionalReaction = 237
    TriggerLinearMotion = 238
    KillStreams = 247
    InfraredModeSet = 250
    InfraredMessageConfig = 251
    InfraredSendMessageBurst = 252

    # ---- firmware OTA-over-BLE group (NOT used by this project) ----
    FirmwareStatus = 18
    FirmwareOpen = 19
    FirmwareClose = 20
    FirmwareSectorOpen = 21
    FirmwareStreamData = 22
    FirmwareSectorClose = 23
    FirmwareSectorCheck = 24
    FirmwareAbandon = 25
    FirmwareValid = 28
    FirmwareSectorVerify = 29
    FirmwareSectorReject = 30
    FirmwareForceBootload = 32
    FirmwareSoftReset = 33

    # ---- responses / streams (robot -> host) ----
    ChecksumError = 128
    CommandError = 129
    GaitSetAck = 130
    AnimationAck = 131
    KinematicStanceAck = 132
    GameStateAck = 133
    StreamBattery = 134
    StreamInfrared = 136
    StreamCompass = 140
    GaitSetAllAck = 143
    ConnectionEstablishedAck = 145
    StreamHeartbeat = 147
    HeadColourSetAck = 176
    SetLegJointAnglesAck = 192
    StreamJointAngles = 195
    StreamIsOnFloor = 219
    StreamOdometry = 228

    @classmethod
    def _missing_(cls, value):          # tolerate unknown ids from the robot
        obj = int.__new__(cls, value)
        obj._name_ = f"Unknown_{value}"
        obj._value_ = value
        return obj


class TransformMode(IntEnum):
    """``Transform`` (cmd 6) mode byte. The app drives with ``Walking``
    (``BuildMovementRequest`` sets mode 3); ``BuildDeadReckoning`` uses mode 4."""

    Rotation = 0
    Translation = 1
    CenterPoint = 2
    Walking = 3
    DeadReckoning = 4
