# Recovered app data (old phone) — what it gave us

A backup of both apps' Android data (`com.reachrobotics.mekamon` and
`com.reachrobotics.reachedu`) was recovered from an old phone. It resolved the two biggest
open questions — **joint-angle scaling** and **gait scaling** — and yielded the official
firmware image. None of this raw data is committed (it's personal/copyrighted); only the
distilled facts and the user's own animation/gait presets (`assets/`) are.

## 1. `firmware.json` — official PIC32 firmware (the long-sought image)

`…/com.reachrobotics.mekamon/files/data/firmware.json`

| field | value |
|-------|-------|
| version | **V02.17.03** (majorVersion 2, minorVersion 17) |
| description | `Filename: firmwares/V02.17.03_4fe4862.bin` |
| decoded size | **192,512 bytes = exactly 47 × 4096-byte sectors** |
| first bytes | `DC AC DC 56 5C 83 9C 5E …` |
| sha256 (json) | `D524C781…E13A7DA3` |

`Content` is base64 of the raw binary; `192512 % 4096 == 0` confirms the sectored
OTA-image format (`GetFirmwareSectors` requires a 4 KB multiple). This is the
**guaranteed-restorable backup** the OTA analysis wanted. Backed up (json + decoded `.bin`)
to `C:\Users\barto\Mekamon-Backups\`. **Per the project directive we do NOT flash firmware**
— it's kept purely as a reference/safety net. (Still unknown without a stock dump: the flash
*base address* for sector 0, which lives in the bootloader.)

## 2. `.gait` presets — decoded the gait scaling

`…/files/Gaits/<account>/*.gait` (JSON). Example ("szybko" = Polish "fast"):

```json
{ "kinematicStanceType": 3,
  "gaitParameters": { "stanceAngle":0.5, "stanceDistance":0.55, "walkingSpeed":1.0,
    "stepDuration":0.533, "stepShift":0.733, "stepHeight":0.698, "gaitType":2,
    "bodyHeight":0.344, "crankRandomness":0.0, "stanceRandomness":0.0 } }
```

So every gait parameter is a **normalised float 0..1** → wire byte = **`round(value*255)`**,
except `gaitType` which is the raw `GaitType` enum (2=Trot, 4=Crawl). This is exactly the
`GaitSetAll` order. Two presets are bundled (`assets/gaits/`) and exposed in the GUI.
Implemented by `commands.gait_params_to_bytes`.

## 3. `.motion` files — decoded animations AND the joint-angle scaling

`…/Accounts/<id>/AnimationsSub|AnimationsUnpushed/*.motion` (JSON). The `data` field is
base64 of `[uint32 uncompressed_size][gzip]`; decompressed it is:

```json
{"Frames":[{"Legs":[{"Hip":150,"Knee":180,"Thigh":125,"HasValue":true}, x4],"Frame":0}, …],
 "NumFrames":80}
```

This was the key to **limb control**. The joint values are **unsigned, ~0..255** (NOT signed
−128..127), measured across 24 recovered animations:

| joint | observed range | neutral (standing) |
|-------|----------------|--------------------|
| Hip   | 100 .. 200 | **150** |
| Knee  | 107 .. 200 | **180** |
| Thigh | 50 .. 150  | **125** |

The standing pose `(hip 150, knee 180, thigh 125)` is verified — "Little Wave" frame 0 has
all four legs exactly there. **This is why limb control did nothing before:** the code used
signed `clamp_i8` (so any real value >127 was clamped to 127) and treated 0 as neutral (it's
an extreme). Fixed in v0.4.0: joints are unsigned `clamp_u8`, sliders use the real ranges,
neutral = the standing pose, and joint mode first sends `KinematicStance(LegJointAngles)`.

**Animation playback:** `mekamon.motion` loads a `.motion`, linearly interpolates the sparse
per-leg keyframes to a pose per frame, and streams them as `SetLegJointAngles` (~30 fps).
Eight of the user's own animations are bundled in `assets/motions/` and playable from the GUI.

## 4. Other files (not committed — personal)

`bluetoothdevices.json` (paired robots), `units.json`, `account.json`, `player.json`,
`authentication.json` — account/identity data, deliberately kept out of the repo.
