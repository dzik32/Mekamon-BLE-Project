# MekaMon BLE Project

Reviving the abandoned **Reach Robotics MekaMon** quadruped by talking to it over
Bluetooth Low Energy — **no firmware modification**. This drives the *stock* robot
through its Nordic UART Service using the reverse-engineered **"Hermes"** protocol, with
a Python library, a desktop **GUI**, and **direct control of all 12 leg joints**.

> Reach Robotics is defunct and the official app/servers are gone. This is an
> independent interoperability project for hardware you own. Not affiliated with Reach
> Robotics. No copyrighted app binaries are redistributed here.

---

## ⬇️ Just want to use it? (no Python, nothing to install)

The app ships as **one self-contained `MekamonController.exe`** — Python, the BLE stack
and the GUI are all bundled inside it. There is nothing to install.

1. Download **`MekamonController.exe`** from the **[Releases page](../../releases)**
   (or the newest **[Actions build](../../actions)** → artifacts).
2. Turn **Bluetooth on** and power up the robot.
3. **Double-click** `MekamonController.exe`. Click **Scan**, select your robot, **Connect**.

> Windows SmartScreen may say "unknown publisher" (the app isn't code-signed yet) —
> click **More info → Run anyway**. You need a working **Bluetooth LE** adapter; most
> laptops have one built in, otherwise use a cheap USB BLE dongle.

The rest of this README is for developers who want to run from source or rebuild the exe.

## Features

- 🎮 **Drive** — virtual joystick + keyboard (WASD / Q-E / Space).
- 🦿 **Full limb control** — all 12 joints directly, with the **real 0–255 ranges** and
  standing pose recovered from the app data (this is what makes it actually move).
- 💃 **Play your saved animations** — replays recovered MekaMotion `.motion` files by
  streaming joint poses (8 of the user's animations bundled).
- 🦗 **Gait tuning** — all 10 gait parameters with the float→byte scaling decoded, plus
  recovered presets (fast trot / slow crawl).
- 🎬 **Animations / steps / body modes** — `PlayAnimation`, `TakeSteps`, `KinematicStance`.
- 💡 **Head LED** — set any RGB colour.
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
then stream `Transform`. Full details in **[`MEKAMON_PROTOCOL.md`](MEKAMON_PROTOCOL.md)**,
the end-to-end send path (app → BLE) in **[`docs/command-pipeline.md`](docs/command-pipeline.md)**,
every movement command in **[`docs/movement.md`](docs/movement.md)**,
the 12-joint encoding in **[`docs/joint-encoding.md`](docs/joint-encoding.md)**,
and what the recovered phone data unlocked in **[`docs/recovered-data.md`](docs/recovered-data.md)**.

## Status & roadmap

| Area | State |
|------|-------|
| COBS + `mod-255` checksum framing | ✅ byte-exact (confirmed from native `CalculateChecksum`), unit-tested |
| Scan / connect / handshake | ✅ implemented |
| Drive (Transform) | ✅ confirmed `[6, Mode, forward, strafe, turn]` (axes verified live), Mode=Walking, ±127 |
| Head LED | ✅ confirmed `[46, R, G, B]` |
| Walk steps / animations / stance | ✅ decoded: TakeSteps `[224,n]`, PlayAnimation `[220,id,…]`, KinematicStance `[8,type]` |
| Gait tuning (`GaitSetAll`) | ✅ 11-byte layout + 10 params + **float→byte scaling decoded** (0..1 × 255); presets bundled |
| 12-joint control (`SetLegJointAngles`) | ✅ wire order + **scaling solved** (unsigned 0–255, real ranges + neutral from recovered animations) |
| Animation playback | ✅ recovered `.motion` files replayed by streaming joint poses |
| Official firmware image | ✅ `firmware.json` V02.17.03 recovered + backed up (reference only — no flashing) |
| Animations / gaits / stance | 🟡 command ids known; payload layouts to verify live |
| Response parsing (battery, acks) | 🟡 framing done; per-type decoders TBD |

**Next:** verify limb control + animation playback on the robot (Bluetooth required);
decode telemetry responses (battery, IMU, on-floor); optional gamepad driving.

## Build the .exe yourself

```powershell
python -m pip install -r requirements.txt pyinstaller Pillow
python tools/make_icon.py     # regenerate assets/icon.ico (optional)
python build.py               # -> dist/MekamonController.exe (single file)
```

`build.py` bundles the WinRT Bluetooth backend that Bleak needs on Windows. CI does the
same automatically — see `.github/workflows/build.yml` (push a `vX.Y.Z` tag to publish a
Release with the exe attached, or run the workflow manually for a downloadable artifact).

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
