# MekaMon BLE Project

Reviving the abandoned **Reach Robotics MekaMon** quadruped by talking to it over
Bluetooth Low Energy — **no firmware modification**. This drives the *stock* robot
through its Nordic UART Service using the reverse-engineered **"Hermes"** protocol, with
a Python library, a desktop **GUI**, and **direct control of all 12 leg joints**.

> Reach Robotics is defunct and the official app/servers are gone. This is an
> independent interoperability project for hardware you own. Not affiliated with Reach
> Robotics. No copyrighted app binaries are redistributed here.

---

## Features

- 🦿 **Full limb control** — command all 12 joints directly (4 legs × hip/knee/thigh).
- 🎮 **Drive** — virtual joystick + keyboard (WASD / Q-E / Space).
- 💡 **Head LED** — set any RGB colour.
- 🎬 **Animations** — trigger built-in animations by id.
- 🧩 **Clean Python API** — `bleak`-based, byte-exact framing, fully scriptable.
- 🛑 **Emergency stop** baked into the controller and GUI.

## Requirements

- Windows 10/11 (tested) with a working BLE adapter — macOS/Linux should work via `bleak`.
- **Python 3.11 or 3.12** recommended (PySide6 wheels can lag the newest CPython).
- A powered-on MekaMon in range.

## Install

```powershell
python -m pip install -r requirements.txt
# or, as a package:  python -m pip install -e .[gui]
```

## Quick start

**1. Find your robot**

```powershell
python -m mekamon          # or: python examples/scan.py
```

**2. Launch the GUI**

```powershell
python gui/app.py
```

Click **Scan**, pick your robot (likely-MekaMon devices are flagged ★), click
**Connect** (this runs the handshake automatically), then drive / pose / light it up.

**3. Or script it**

```python
from mekamon import MekamonController

ctl = MekamonController()
dev = next(d for d in ctl.scan() if d.likely_mekamon)
ctl.connect(dev.device)              # handshake + start streaming

ctl.set_head_colour(0, 80, 255)      # blue head
ctl.set_drive(strafe=0, forward=60, turn=0)   # walk forward
# direct limb control (each joint is a signed int8, -128..127):
ctl.set_joints(front_left=(0, 20, -10), front_right=(0, 20, -10),
               back_left=(0, 20, -10), back_right=(0, 20, -10))
ctl.stop(); ctl.shutdown()
```

## How it works

```
GUI (PySide6, main thread)
        │  thread-safe calls
        ▼
MekamonController ──► asyncio loop on a daemon thread
        │                     │ streams Transform / SetLegJointAngles @ ~10 Hz
        ▼                     ▼
   commands.py          ble.py (bleak)  ──BLE──►  MekaMon (Nordic UART Service)
   protocol.py  (COBS + checksum framing)
```

The robot expects to be **driven continuously**, so the controller re-sends the current
drive vector (or joint pose) on a timer; the UI/your script just sets the target.

### Protocol in one paragraph

Transport is the **Nordic UART Service** (`6e400001-…`, write `…0002`, notify `…0003`).
Each command is `wire = COBS(payload) + checksum + 0x00`, where
`payload = [cmd_id, *signed_bytes]` and `checksum = (sum(cobs_bytes) + 1) mod 256`.
Connect handshake: `ConnectionEstablished[16]` → `GameState[7,1]` → `Transform[6,0,0,0]`,
then stream `Transform`. Full details in **[`MEKAMON_PROTOCOL.md`](MEKAMON_PROTOCOL.md)**;
the 12-joint encoding is in **[`docs/joint-encoding.md`](docs/joint-encoding.md)**.

## Status & roadmap

| Area | State |
|------|-------|
| COBS + checksum framing | ✅ byte-exact, unit-tested against known frames |
| Scan / connect / handshake | ✅ implemented |
| Drive (Transform) | ✅ implemented (proven wire form) |
| Head LED | ✅ implemented (proven wire form) |
| 12-joint control (`SetLegJointAngles`) | ✅ **structure confirmed** (13-byte, int8×12); ⚠️ angle **scaling needs live calibration** |
| Animations / gaits / stance | 🟡 command ids known; payload layouts to verify live |
| Response parsing (battery, acks) | 🟡 framing done; per-type decoders TBD |

**Next:** live-calibrate joint scaling on the robot, then add a calibration table so the
limb sliders read real degrees; decode telemetry responses (battery, IMU, on-floor).

## Repository layout

```
mekamon/            the Python package
  protocol.py       COBS, checksum, framing, PacketType enum
  commands.py       payload builders (transform, head_colour, set_leg_joint_angles, …)
  ble.py            bleak transport (scan, connect, notify, write)
  controller.py     threaded high-level controller used by the GUI
gui/app.py          PySide6 control panel
examples/           scan.py, drive_demo.py
tests/              byte-exact protocol tests
docs/               joint-encoding.md and other findings
tools/disasm/       reproducible reverse-engineering scripts (Capstone)
MEKAMON_PROTOCOL.md full reverse-engineered protocol reference
```

The reverse-engineering inputs (the APK and the `il2cpp/` decompile, ~230 MB and
copyrighted) are intentionally **git-ignored** — only the distilled findings are tracked.

## Safety

- Give the robot clear space; start joint values near 0 and move one at a time.
- **Space** (or the red button) is an emergency stop.
- This project never touches firmware — the robot stays stock and recoverable.

## License

MIT — see [`LICENSE`](LICENSE).
