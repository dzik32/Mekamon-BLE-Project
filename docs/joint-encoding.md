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

## What is still unknown — the scaling/units

The struct stores joints as `int` with `NormalizedHip/Knee/Thigh` getters and a
`ClampToAcceptableRange()`, so the wire int8 is a quantised/clamped angle, but the
exact mapping (degrees? a normalised step? per-joint offset and sign) lives in the
native `Encode()` body and is **not** recoverable as a constant. Plan: calibrate live.

### Live calibration plan
1. Connect, enable joint mode (`SetupJointAngles` best-effort), stream a neutral pose.
2. Move **one joint by a small amount** (e.g. ±10) and observe the limb.
3. Record the int8 → physical-angle relationship per joint; note sign and safe range.
4. Fill a calibration table so the GUI can show real degrees.

Stay near 0 and step gently — the robot clamps internally but mechanical limits are real.

## Related joint commands (for later)
* `SetupJointAngles=60` — enable joint-angle control/streaming (sent before poses).
* `SetLegControlPoint=59` — Cartesian foot target instead of raw joint angles.
* `SetLegCompliance=61`, `StreamJointAngles=195` (robot→host feedback).
