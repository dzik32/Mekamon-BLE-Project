# MekaMon BLE Protocol ("Hermes") — reverse-engineered reference

Source: decompiled **MekaMon Android app v2.3.0** (`com.reachrobotics.mekamon`, Unity IL2CPP),
dumped with Il2CppDumper. Raw artifacts in `il2cpp/out/` (`dump.cs`, `Mekamon.dll`,
`MekaMotion.dll`, `stringliteral.json`). Cross-checked against Wes Freeman's working
Hackaday driver, which matches exactly.

The robot's internal name for this protocol is **Hermes**. Every command is an
`IHermesRequest` with a matching `…AcknowledgeResponse`.

---

## 1. Transport (Nordic UART Service)

`dump.cs:432868`
- Service:  `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- Write  (app→robot): `6e400002-b5a3-f393-e0a9-e50e24dcca9e`  ← send command frames here
- Notify (robot→app): `6e400003-b5a3-f393-e0a9-e50e24dcca9e`  ← subscribe for responses

Advertised name is the robot's name (the app scans for NUS devices).

## 2. Frame format (verified, byte-exact)

```
wire = COBS( [cmd_id, payload_bytes...] )  ++  checksum  ++  0x00
```
- `cmd_id` and payload are written as **signed** bytes (`-128..127`).
- **COBS** = Constant Overhead Byte Stuffing (removes all 0x00 from the body).
- **checksum** = `(sum(of the COBS-encoded bytes) mod 255) + 1`  → always in **1..255**.
  - Confirmed by disassembling `HermesPacket.CalculateChecksum` (native uses the
    `0x80808081` magic-number divide-by-255). Being 1..255 it can never equal the `0x00`
    terminator. (A `(sum + 1) mod 256` approximation only holds while the byte sum < 255;
    it diverges for bigger frames, e.g. a bright head colour.)
- trailing `0x00` = frame terminator.

Verified frames (computed == documented):
| meaning              | payload      | full wire frame              |
|----------------------|--------------|------------------------------|
| ConnectionEstablished| `[16]`       | `02 10 13 00`                |
| GameState = 1        | `[7,1]`      | `03 07 01 0C 00`             |
| Transform neutral    | `[6,0,0,0]`  | `02 06 01 01 01 0C 00`       |

## 3. Connect handshake (from the working driver)

Send, ~0.5 s apart:
1. `ConnectionEstablished` → payload `[16]`
2. `GameState` → payload `[7, 1]`   (GameStateType=1, "active/freedrive")
3. `Transform` neutral → `[6, 0, 0, 0]`

Then stream `Transform` at ~5 Hz. A heartbeat (`SetupHeartbeat=17`) may be needed to
avoid timeout on some firmware.

---

## 4. Key command payloads

Field types/offsets are from `dump.cs`. Simple ones are byte-exact; multi-byte ones
(joint angles, gaits) have field order known but the exact per-field width/scaling is
inside the native `Encode()` (needs Ghidra on `libil2cpp.so` to confirm — see §6).

### Transform — `cmd 6`  (drive)  `dump.cs:448152`
App struct: `float AxisA, AxisB, AxisC; Mode`. **Confirmed wire form** (from
`TransformRequest.Encode` @ `0x1866DE8`, 5 bytes — note **Mode is byte #1**):
```
[6, Mode, AxisA, AxisB, AxisC]
#     Mode = TransformMode (Rotation=0, Translation=1, CenterPoint=2, Walking=3, DeadReckoning=4)
#     AxisA = strafe (x), AxisB = forward (y), AxisC = turn (rotation)
```
Each axis is a **plain `(byte)(int)float`** — *no scale factor*; the float values are
already in robot units. The app clamps axes to **±127.0** (`0x42FE0000`/`0xC2FE0000`
constants in `BuildDeadReckoningRequest`). For joystick driving the app calls
`BuildMovementRequest(translation, rotation)` which sets **Mode = Walking (3)**.
The proven minimal Hackaday frame `[6, strafe, fwd, turn]` is the same axes with the
Mode byte omitted (robot tolerates the shorter packet).

### HeadColourSet — `cmd 46`  (head RGB LED)  `dump.cs:446407`
```
[46, R, G, B]            # each 0..255
```

### GameState — `cmd 7`  `dump.cs:446328`
Fields: `GameStateType GameState; bool ForceDefaults`. Wire: `[7, state, forceDefaults]`.

### SetLegJointAngles — `cmd 58`  (DIRECT per-joint control)  `dump.cs:447719`
Fields: 4× `JointAngles{int Hip,Knee,Thigh}` = FrontLeft, FrontRight, BackLeft, BackRight
→ robot is **12-DOF**. **Confirmed wire form** (from `SetLegJointAngles.Encode` @
`0x185DAA8`, 13 bytes — the per-leg order on the wire is **Knee, Thigh, Hip**, i.e. it reads
struct offsets +4, +8, +0):
```
[58, FL.Knee, FL.Thigh, FL.Hip,
     FR.Knee, FR.Thigh, FR.Hip,
     BL.Knee, BL.Thigh, BL.Hip,
     BR.Knee, BR.Thigh, BR.Hip]
```
Each joint = the **low byte (int8)** of the angle; Encode does no scaling (the app clamps
to an acceptable range first via `JointAngles.ClampToAcceptableRange`). The int8→physical
angle mapping (units/sign per joint) still needs live calibration on the robot.
Related: `SetLegControlPoint=59` (Cartesian foot target), `SetLegCompliance=61`,
`SetupJointAngles=60` (enable joint-angle streaming), `StreamJointAngles=195`.

### Gait — `GaitSetAll=13`, `GaitSet=4`, `GaitGetAll=14`  `dump.cs:446222`
`GaitSetAll` carries a `GaitParameters` struct (stride length/height/period/etc.).
`GaitSet` sets one `GaitParameterType` on one `GaitId`.

### Animations — `PlayAnimation=220`  `dump.cs:447289`
Fields: `AnimationId, BlendInTime, BlendOutTime, LayeringPercent, TransformType`.
Also: `PlayAnimationHold=221`, `PlayAnimationLoop=222`, `AnimationControls=229`,
`AnimationComponent=9`.

### Posture / misc
- `KinematicStance=8`, `KinematicStanceExtended=232` — set body pose (height/lean/tilt).
- `TakeSteps=224` — walk a fixed number of steps.
- `Twitch=31`, `DirectionalReaction=237`, `TriggerLinearMotion=238`, `SetLegDamage=236`.
- `HeadModeSet=230`, `HeadFlashingSet=234`.

---

## 5. Full PacketType command table (`dump.cs:440705`)

**Requests (host→robot):**
0 Unknown · 1 AddonGet · 3 SetupCompass · 4 GaitSet · 5 SetupInfrared · **6 Transform** ·
7 GameState · 8 KinematicStance · 9 AnimationComponent · 10 SetupBattery ·
11 RobotFirmwareVersion · **13 GaitSetAll** · 14 GaitGetAll · **16 ConnectionEstablished** ·
17 SetupHeartbeat · 31 Twitch · 34 RobotSerialNumber · 35 LegSerialNumber ·
36 AddonSerialNumber · 37 LegVersion · 39 InfraredIntensitySet · 40 InfraredIntensityGet ·
43 RobotStatisticGet · 44 LegStatisticsTriggerGetAll · 45 LegStatisticGet ·
**46 HeadColourSet** · 47 HeadColourGet · 48-56 ImuCalibration* · 57 BluetoothVersion ·
**58 SetLegJointAngles** · 59 SetLegControlPoint · 60 SetupJointAngles · 61 SetLegCompliance ·
199 EventEducational · 208 ImuReset · 218 SetupIsOnFloor · **220 PlayAnimation** ·
221 PlayAnimationHold · 222 PlayAnimationLoop · 224 TakeSteps · 225 ClearOdometry ·
227 SetupOdometry · 229 AnimationControls · 230 HeadModeSet · 232 KinematicStanceExtended ·
234 HeadFlashingSet · 236 SetLegDamage · 237 DirectionalReaction · 238 TriggerLinearMotion ·
247 KillStreams · 250 InfraredModeSet · 251 InfraredMessageConfig · 252 InfraredSendMessageBurst

**Firmware-update (OTA over BLE!) group:**
18 FirmwareStatus · 19 FirmwareOpen · 20 FirmwareClose · 21 FirmwareSectorOpen ·
22 FirmwareStreamData · 23 FirmwareSectorClose · 24 FirmwareSectorCheck ·
25 FirmwareAbandon · 28 FirmwareValid · 29 FirmwareSectorVerify · 30 FirmwareSectorReject ·
**32 FirmwareForceBootload** · 33 FirmwareSoftReset

**Responses/streams (robot→host):** 128 ChecksumError · 129 CommandError ·
130 GaitSetAck · 131 AnimationAck · 132 KinematicStanceAck · 133 GameStateAck ·
134 StreamBattery · 136 StreamInfrared · 140 StreamCompass · 143 GaitSetAllAck ·
145 ConnectionEstablishedAck · 147 StreamHeartbeat · 176 HeadColourSetAck ·
192 SetLegJointAnglesAck · 195 StreamJointAngles · 219 StreamIsOnFloor · 228 StreamOdometry …
(many `*DataAcknowledge` carry returned data; full list in `dump.cs`.)

---

## 6. Getting byte-exact payloads for the complex commands

`dump.cs` gives signatures, not the native `Encode()` bodies (and the dummy DLLs are stubs).
You do NOT need Ghidra — disassemble specific functions with **Capstone** straight from the
.so (see `il2cpp/analyze*.py`). Notes confirmed during the CRC analysis:
- `libil2cpp.so` is **ELF32 ARM, code is A32 (ARM mode, not Thumb)** → Capstone `CS_MODE_ARM`.
- First PT_LOAD has vaddr==offset==0, so the `Offset`/`VA`/`RVA` in `dump.cs` == file offset.
- IL2CPP `byte[]` layout: `Length` at `+0xC`, element data at `+0x10`.
For exact joint-angle / gait / animation wire bytes, disassemble the relevant
`…Request.Encode()` at its `dump.cs` offset. Or, easier for simple commands: send & observe.

## 7. Firmware-over-BLE (OTA) — analysis

PIC32 part = **PIC32MX250F256L-I/PT**, ICSP confirmed alive (not PDID-locked).

### Verdict: the OTA path is UNAUTHENTICATED (CRC32 integrity only — no signature)
Searched the whole decompile. The firmware-upload path uses **no signature, no public key,
no encryption**. Integrity is a per-sector **CRC32** that the robot computes and reports back;
the app compares it. (The RSA/SHA classes in the dump are stock .NET `mscorlib`, unused here.)
On all available evidence the bootloader checks *integrity, not authenticity* → **unsigned
custom firmware is feasible in principle.**

### Upload state machine (`FirmwareUpdater : MonoBehaviour`, `IFirmwareUploadState`)
`Status → Open(maj,min) → [per sector: SectorOpen(i) → StreamData(bytes…) → SectorClose →
SectorVerify(robot returns uint CRC) → (SectorReject⟳ on mismatch)] → Valid(numSectors) →
Close → ForceBootload`. Supports resume (`ShouldResume`) and rate-limiting. `SoftReset`
needs magic bytes `0x55,0xAA`.

### Firmware image format (fully known) — `class Firmware` (ns MekaCentral)
- `SECTOR_SIZE = 4096` (4 KB logical sectors; sequential, sector i ⇒ bytes [i*4096:(i+1)*4096]).
- Loaded at runtime from `{persistentDataPath}/data/firmware.json` (downloaded from Reach's
  now-dead servers — **NOT bundled in the APK**, so we don't have an official image).
- JSON schema: `{ MajorVersion:int, MinorVersion:int, UUID:string, Description:string,
  Content:string }` where **`Content` = base64 of the raw firmware binary**.
- `GetBinaryData()` = `Convert.FromBase64String(Content)` (confirmed in disasm).
- `GetFirmwareSectors()` (confirmed in disasm): **requires `binary.Length % 4096 == 0`** — if
  not a whole number of 4 KB sectors it returns empty (NO auto-padding; pad the image yourself,
  conventionally with 0xFF). Then `Array.Copy` into sequential 4 KB `FirmwareSector` chunks.
- `FirmwareSector` = just `byte[] Data` (no per-sector address or signature).

### CRC confirmed by disassembly (Capstone, ARM) — `Firmware.CyclicRedundancyCheck`
**Standard CRC-32**: init `0xFFFFFFFF`, reflected poly `0xEDB88320`, final XOR `0xFFFFFFFF`
(`mvn r5,#0` init; `movw/movt r4,#0xEDB88320` poly; `mvn r0,r5` final-not). Equivalent to
**Python `zlib.crc32(sector_bytes) & 0xFFFFFFFF`**. The CRC32 table (`...07 77` = 0x77073096)
and poly constant were also found verbatim in the binary. This is what the robot returns in
`FirmwareSectorVerify` and the app compares — so per-sector verify = `zlib.crc32`.

### Caveats / unknowns before attempting a custom flash
1. **Bootloader is unseen** — everything above is the *app* side. No evidence of a signature
   check, and the protocol has no field to carry one, but the robot-side bootloader can't be
   100% proven safe from the app alone.
2. **No official image** → unknown flash base address / which sector is the resident
   bootloader (must NOT be overwritten) / any expected image header.
3. ~~Exact CRC32 params~~ **RESOLVED**: standard CRC-32 = `zlib.crc32` (see above). The only
   remaining unknown from #2 is the flash **base address** for sector 0 (lives in the
   bootloader; comes from the stock-firmware dump).

### Recommended de-risking (uses the alive ICSP as a safety net)
Dump the stock PIC32 firmware via PICkit first (ICSP is alive). That yields: the bootloader
(→ sector→address mapping + any checks), the flash memory map, and a **guaranteed-restorable
backup**. With that map + the unauthenticated OTA protocol above, custom firmware over BLE
becomes low-risk. Also worth hunting for an official `firmware.json` (old device backup under
`/Android/data/com.reachrobotics.mekamon/files/`, or an Android backup) as a reference image.
