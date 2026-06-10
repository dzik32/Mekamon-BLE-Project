# SetLegJointAngles (cmd 58) — wire encoding

Confirmed 2026-06-09 by disassembling the official app's `libil2cpp.so` (ELF32 ARM,
A32 mode) with Capstone. This is the command behind **full per-limb control**.

## Structures (from `il2cpp/out/dump.cs`)

```csharp
// dump.cs:447655
public struct JointAngles {
    public int Hip;    // 0x0
    public int Knee;   // 0x4
    public int Thigh;  // 0x8
    // + NormalizedHip/Knee/Thigh (float), HasValue, ClampToAcceptableRange()
}

// dump.cs:447719
public struct SetLegJointAnglesRequest : IHermesRequest {
    JointAngles FrontLeft;   // 0x00
    JointAngles FrontRight;  // 0x0C
    JointAngles BackLeft;    // 0x18
    JointAngles BackRight;   // 0x24
    IHermesPacket Encode();
    int UnstuffedLength { get; }
}
```

## The key number: `UnstuffedLength`

Each request reports the length of its **pre-COBS payload** (`[cmd_id, *fields]`, one
signed byte per field). Disassembling the getters:

```
Transform.get_UnstuffedLength      @0x5D45BC:  mov r0, #5  ; cmd + AxisA,B,C,Mode (int8)
SetLegJointAngles.get_UnstuffedLength @0x5D3E2C:  mov r0, #0xD = 13
```

* Transform = 5 calibrates the rule: payload byte count = cmd(1) + one int8 per field.
  (The proven Hackaday `[6,strafe,fwd,turn]` simply omits the trailing `Mode` byte.)
* **SetLegJointAngles = 13 = cmd(1) + 12 joints → each joint is one signed int8.**

### Confirmed wire order (from `SetLegJointAngles.Encode` @ `0x185DAA8`)

Disassembly shows Encode allocates `byte[13]`, writes cmd `0x3A`=58, then for each leg
reads struct offsets **+4 (Knee), +8 (Thigh), +0 (Hip)** and `strb`s the low byte:

```
ldr r6,[r5,#4]  ; strb -> data[1]   = FL.Knee
ldr r6,[r5,#8]  ; strb -> data[2]   = FL.Thigh
ldr r6,[r5]     ; strb -> data[3]   = FL.Hip
ldr r6,[r5,#0x10]; ...              = FR.Knee   (FrontRight base = 0x0C)
... (FR.Thigh, FR.Hip, then BackLeft @0x18, BackRight @0x24)
```

So the on-wire payload is — note the **per-leg order is Knee, Thigh, Hip**:

```
[58, FL.Knee, FL.Thigh, FL.Hip,
     FR.Knee, FR.Thigh, FR.Hip,
     BL.Knee, BL.Thigh, BL.Hip,
     BR.Knee, BR.Thigh, BR.Hip]      # 13 bytes, each joint int8 (low byte, no scaling)
```

(`mekamon.commands.set_leg_joint_angles` still takes intuitive `(hip, knee, thigh)`
tuples and reorders to this wire layout for you.)

then framed as usual: `COBS(payload) + checksum + 0x00`.

## The scaling/units — RESOLVED from recovered animations

Recovered `.motion` files (see [recovered-data.md](recovered-data.md)) store real joint
keyframes, which settle the scaling: **joint values are unsigned (~0..255), not signed
−128..127.** Measured across 24 animations:

| joint | range | neutral (standing) |
|-------|-------|--------------------|
| Hip   | 100..200 | **150** |
| Knee  | 107..200 | **180** |
| Thigh | 50..150  | **125** |

Standing pose `(hip 150, knee 180, thigh 125)` is verified (all four legs identical in
"Little Wave" frame 0). So the byte stored by `strb` is an **unsigned** joint position.
This is why early limb control failed: signed `clamp_i8` capped real values (>127) to 127,
and 0 was treated as neutral (it's actually an extreme). The code now uses `clamp_u8`,
real per-joint ranges, the standing pose as neutral, and enters
`KinematicStance(LegJointAngles=5)` before streaming. See `mekamon/commands.py`
(`JOINT_RANGES`, `NEUTRAL_POSE`) and `mekamon/motion.py`.

## Related joint commands (for later)
* `SetupJointAngles=60` — enable joint-angle control/streaming (sent before poses).
* `SetLegControlPoint=59` — Cartesian foot target instead of raw joint angles.
* `SetLegCompliance=61`, `StreamJointAngles=195` (robot→host feedback).
