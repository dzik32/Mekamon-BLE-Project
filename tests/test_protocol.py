"""Byte-exact tests for the Hermes framing. Run: ``py -m pytest`` (or ``py tests/test_protocol.py``)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mekamon import commands
from mekamon.protocol import (
    build_frame,
    cobs_decode,
    cobs_encode,
    parse_frame,
    split_frames,
)

# (name, payload, expected full wire frame) — verified against the app + Hackaday driver.
KNOWN_FRAMES = [
    ("ConnectionEstablished", [16], bytes.fromhex("02 10 13 00".replace(" ", ""))),
    ("GameState(1)", [7, 1], bytes.fromhex("03 07 01 0C 00".replace(" ", ""))),
    ("Transform neutral", [6, 0, 0, 0], bytes.fromhex("02 06 01 01 01 0C 00".replace(" ", ""))),
]


def test_known_frames_byte_exact():
    for name, payload, expected in KNOWN_FRAMES:
        got = build_frame(payload)
        assert got == expected, f"{name}: {got.hex()} != {expected.hex()}"


def test_command_builders_match_known_frames():
    assert build_frame(commands.connection_established()) == KNOWN_FRAMES[0][2]
    assert build_frame(commands.game_state(1)) == KNOWN_FRAMES[1][2]
    # The raw [6,0,0,0] payload still frames to the known neutral-Transform frame.
    assert build_frame([6, 0, 0, 0]) == KNOWN_FRAMES[2][2]


def test_checksum_is_mod_255_plus_1():
    from mekamon.protocol import checksum, cobs_encode

    # Small sums: (sum%255)+1 == (sum+1) for sum < 255 (matches the verified frames).
    assert checksum(cobs_encode(bytes([6, 0, 0, 0]))) == 0x0C
    # Large sum (bright head colour): the old (sum+1)&0xFF guess would give 0x31; correct
    # value is (816 % 255) + 1 = 52 = 0x34.
    body = cobs_encode(bytes([46, 255, 255, 255]))
    assert sum(body) == 816
    assert checksum(body) == 0x34
    # Checksum must never be 0x00 (would collide with the frame terminator).
    for n in range(0, 2000, 7):
        assert checksum(bytes([255]) * n) != 0x00


def test_transform_official_5byte_form():
    # [6, mode, strafe, forward, turn]; default mode = Walking (3).
    assert commands.transform(0, 0, 0) == bytes([6, 3, 0, 0, 0])
    assert commands.transform(10, 20, 30, mode=0) == bytes([6, 0, 10, 20, 30])
    # negative axes -> two's-complement bytes
    assert commands.transform(-1, -2, -3, mode=4) == bytes([6, 4, 0xFF, 0xFE, 0xFD])


def test_cobs_roundtrip():
    for data in [b"", b"\x06\x00\x00\x00", b"\x10", bytes(range(256)), b"\x00" * 10]:
        assert cobs_decode(cobs_encode(data)) == data


def test_cobs_removes_zeros_from_body():
    for data in [b"\x06\x00\x00\x00", b"\x00\x00", bytes(300)]:
        body = cobs_encode(data)
        assert 0 not in body  # body must be free of the frame delimiter


def test_frame_parse_roundtrip():
    payload = bytes([6, 12, -5 & 0xFF, 40])
    frame = build_frame(payload)
    assert frame[-1] == 0x00
    parsed, ok = parse_frame(frame[:-1])  # strip terminator
    assert ok
    assert parsed == payload


def test_set_leg_joint_angles_wire_order_knee_thigh_hip():
    # Inputs are (hip, knee, thigh); wire order per leg is knee, thigh, hip.
    payload = commands.set_leg_joint_angles((1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12))
    assert len(payload) == 13            # cmd(1) + 12 int8 joints (UnstuffedLength == 13)
    assert payload[0] == 58
    assert list(payload[1:]) == [2, 3, 1, 5, 6, 4, 8, 9, 7, 11, 12, 10]


def test_split_frames_handles_multiple_and_partial():
    f1 = build_frame([16])
    f2 = build_frame([7, 1])
    frames, remainder = split_frames(f1 + f2 + b"\x02\x06")  # trailing partial
    assert len(frames) == 2
    assert remainder == b"\x02\x06"


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
            print("ok:", fn.__name__)
    print("All protocol tests passed.")
