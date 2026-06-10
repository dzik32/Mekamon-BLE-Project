# Movement command reference (decoded)

Every movement-related Hermes command, decoded from the app's native `Encode()` bodies
(`il2cpp/analyze_send.py`). All payloads are framed as
`COBS(payload) + checksum + 0x00` (see [command-pipeline.md](command-pipeline.md)).
Each field below is one byte unless noted.

## Drive — `Transform` (cmd 6), 5 bytes

```
[6, Mode, AxisA, AxisB, AxisC]
```

**Axis meanings (verified live on the robot):**

| axis | byte | meaning |
|------|------|---------|
| AxisA | data[2] | **forward (+) / back (−)** |
| AxisB | data[3] | **strafe: right (+) / left (−)** |
| AxisC | data[4] | **turn** |

`Mode` (byte #1) is a `TransformMode`: Rotation 0, Translation 1, CenterPoint 2,
**Walking 3** (used for joystick driving), DeadReckoning 4. Each axis is a signed int8
clamped to ±127, sent as a raw `(byte)(int)` (no scaling). The robot is driven by
streaming this at ~10 Hz. `mekamon.commands.transform(forward, strafe, turn)`.

> The earlier code had AxisA/AxisB swapped, which is why W drove the robot sideways —
> fixed in v0.3.0.

## Walk a set distance — `TakeSteps` (cmd 224), 2 bytes

```
[224, StepCycleCount]      # count 0..255 step cycles
```

## Animations — `PlayAnimation` (cmd 220), 6 bytes

```
[220, AnimationId, BlendInTime, BlendOutTime, LayeringPercent, TransformType]
```

* **AnimationId** (0..255) is **content-driven** — there is no fixed enum; the app loads
  animation content (incl. user-generated, `LocalAnimationStorage`) and references it by
  id, so which id is which move is best found by **experiment**.
* `BlendInTime`/`BlendOutTime` — blend ramp (byte units).
* `LayeringPercent` — 0..100.
* `TransformType` — `AnimationTransformType`: NoTransform 0, MirrorLeftRight 1,
  MirrorFrontBack 2, Rotate90CCW 3, Rotate180CCW 4, Rotate270CCW 5.

Related: `PlayAnimationHold` 221, `PlayAnimationLoop` 222, `AnimationControls` 229.

## Body pose mode — `KinematicStance` (cmd 8), 2 bytes

```
[8, KinematicStanceType]
```

`KinematicStanceType`: Gyrate 0, Mimic 1, Linear 2, Kinematic 3, LegControlPoint 4,
**LegJointAngles 5**, Create 6. `LegControlPoint`/`LegJointAngles` are the modes that put
the robot under Cartesian-foot / direct-joint control (relevant to limb control).
Also `KinematicStanceExtended` (cmd 232): None 0, BodyTilt 7.

## Gait tuning — `GaitSetAll` (cmd 13, 11 bytes) and `GaitSet` (cmd 4, 4 bytes)

```
GaitSetAll: [13, StanceAngle, StanceDistance, WalkingSpeed, StepDuration, StepShift,
                 StepHeight, GaitType, BodyHeight, CrankRandomness, StanceRandomness]
GaitSet:    [4, GaitId, GaitParameterType, value]
```

The 10 parameters are the `GaitParameterType` enum **in this order** (0..9). The app
derives each byte from a float via per-parameter conversions (`GaitConversions`); this
project sends **raw bytes (0..255)** to tune by experiment. The **GaitType** slot takes a
`GaitType` value: **Trot 2, Crawl 4**.

| # | parameter | rough effect |
|---|-----------|--------------|
| 0 | StanceAngle | leg splay angle |
| 1 | StanceDistance | how far the feet sit from the body |
| 2 | WalkingSpeed | gait speed |
| 3 | StepDuration | time per step |
| 4 | StepShift | step phase offset |
| 5 | StepHeight | how high feet lift |
| 6 | GaitType | 2 = Trot, 4 = Crawl |
| 7 | BodyHeight | ride height |
| 8 | CrankRandomness | randomisation |
| 9 | StanceRandomness | randomisation |

## Reactions / misc

| cmd | name | payload |
|----:|------|---------|
| 31 | Twitch | `[31, Direction, Severity]` |
| 237 | DirectionalReaction | `[237, dirX, dirY, dirZ(Vector3), rotation, decayRate, decayThreshold]` (floats — layout TBD) |
| 238 | TriggerLinearMotion | `[238, cycles, InitialDirection, MotionRange, speed]` |
| 224 | TakeSteps | see above |

## Still needing live calibration
* Gait parameter **float→byte scaling** (raw bytes work; meaningful units TBD).
* Direct joint-angle **scaling** (`SetLegJointAngles`) — see the limb-control work
  (likely needs `KinematicStance(LegJointAngles=5)` active first).
