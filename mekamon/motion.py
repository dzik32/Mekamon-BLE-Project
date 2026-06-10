"""Load and play recovered MekaMotion (``.motion``) animations.

A ``.motion`` file is JSON with a base64 ``data`` field = ``[uint32 size][gzip]`` of::

    {"Frames":[{"Legs":[{"Hip":..,"Knee":..,"Thigh":..,"HasValue":true}, x4],"Frame":n}, ...],
     "NumFrames": N}

Only keyframes carry values (``HasValue``); we linearly interpolate per leg/joint to a
full pose for every frame, then stream them as ``SetLegJointAngles`` at a fixed rate.
"""
from __future__ import annotations

import base64
import glob
import gzip
import json
import os
import sys
from dataclasses import dataclass

from .commands import NEUTRAL_POSE

LEG_NAMES = ("FrontLeft", "FrontRight", "BackLeft", "BackRight")
DEFAULT_FPS = 30


@dataclass
class Motion:
    title: str
    poses: list   # one (FL, FR, BL, BR) tuple per frame, each leg = (hip, knee, thigh)
    fps: int = DEFAULT_FPS

    @property
    def num_frames(self) -> int:
        return len(self.poses)

    @property
    def duration(self) -> float:
        return self.num_frames / self.fps if self.fps else 0.0


def _interp(keys, i):
    """Linear-interpolate a leg's (hip,knee,thigh) at frame *i* from its keyframes."""
    if not keys:
        return NEUTRAL_POSE
    if i <= keys[0][0]:
        return keys[0][1]
    if i >= keys[-1][0]:
        return keys[-1][1]
    for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
        if f0 <= i <= f1:
            t = (i - f0) / (f1 - f0) if f1 > f0 else 0.0
            return tuple(round(a + (b - a) * t) for a, b in zip(v0, v1))
    return keys[-1][1]


def load_motion(path: str, fps: int = DEFAULT_FPS) -> Motion:
    """Load a ``.motion`` file into a fully-sampled :class:`Motion`."""
    j = json.load(open(path, encoding="utf-8"))
    data = base64.b64decode(j["data"])
    off = data.find(b"\x1f\x8b")          # gzip magic, after the 4-byte size prefix
    doc = json.loads(gzip.decompress(data[off:]).decode("utf-8"))
    frames = doc.get("Frames", [])
    n = doc.get("NumFrames") or ((max(f["Frame"] for f in frames) + 1) if frames else 0)

    keys = [[] for _ in range(4)]         # per-leg list of (frame, (hip,knee,thigh))
    for f in frames:
        for li, leg in enumerate(f.get("Legs", [])[:4]):
            if leg.get("HasValue"):
                keys[li].append((f["Frame"], (leg["Hip"], leg["Knee"], leg["Thigh"])))

    poses = [tuple(_interp(keys[li], i) for li in range(4)) for i in range(n)]
    return Motion(title=j.get("title", os.path.basename(path)), poses=poses, fps=fps)


def bundled_motions_dir() -> str:
    # In a PyInstaller bundle the assets live under sys._MEIPASS.
    base = getattr(sys, "_MEIPASS",
                   os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", "motions")


def list_motions(directory: str | None = None) -> list:
    """Return ``[(title, path)]`` for the ``.motion`` files in *directory*
    (defaults to the bundled ``assets/motions``)."""
    directory = directory or bundled_motions_dir()
    out = []
    for p in sorted(glob.glob(os.path.join(directory, "*.motion"))):
        try:
            title = json.load(open(p, encoding="utf-8")).get("title") or os.path.basename(p)
        except Exception:
            title = os.path.basename(p)
        out.append((title, p))
    return out
