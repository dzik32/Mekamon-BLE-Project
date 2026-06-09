# How the MekaMon app sends commands (deep dive)

A byte-level trace of the official app's command path, from a high-level request down to
the bytes on the BLE wire. Reverse-engineered from `com.reachrobotics.mekamon` v2.3.0
(Unity IL2CPP) — managed structure from `il2cpp/out/dump.cs`, exact behaviour from
disassembling `libil2cpp.so` (ELF32 ARM, A32) with Capstone (`il2cpp/analyze_send.py`).
The protocol's internal name is **Hermes**.

## 1. The pipeline at a glance

```
 your code / UI
      │  builds a request struct (e.g. TransformRequest{AxisB=60, Mode=Walking})
      ▼
 HermesManager.Robot  (HermesRobotTransactionManager)        dump.cs:443908
      │  raises ImmediateRequest / AsynchronousRequest / SynchronousRequest events
      ▼
 request.Encode()  : IHermesRequest -> IHermesPacket          (per-struct, native)
      │  allocates byte[UnstuffedLength] = [cmd_id, field0, field1, ...]
      ▼
 HermesPacket.CreateRequest()                                 VA 0x1B01C90
      │  COBS-stuff the payload, append checksum, append 0x00
      ▼
 BluetoothLEHardwareInterface.WriteCharacteristic(...)        dump.cs:308853
      │  Shatalmic "Bluetooth LE for iOS/Android" Unity plugin
      ▼  android: androidWriteCharacteristic (JNI)
 GATT write to characteristic 6e400002 (Nordic UART RX) on the robot
```

Three managers exist (`HermesManager`, dump.cs:443530): **Robot**, **Firmware**,
**Calibration**. We only use Robot. Responses arrive on a notify subscription to
`6e400003` and are dispatched by `HermesResponseParser` (dump.cs:443627).

## 2. Transport — Nordic UART Service via the Shatalmic plugin

The app uses the off-the-shelf **`BluetoothLEHardwareInterface`** asset. Relevant string
literals in the dump: `androidBluetoothScanForPeripheralsWithServices`,
`androidWriteCharacteristic`, `DidWriteCharacteristic`, `SubscribeCharacteristic`, …

```
Service  6e400001-b5a3-f393-e0a9-e50e24dcca9e
RX write 6e400002-b5a3-f393-e0a9-e50e24dcca9e   <- command frames go here (app -> robot)
TX notify 6e400003-b5a3-f393-e0a9-e50e24dcca9e  <- responses (robot -> app)
```

The write call is:

```csharp
void WriteCharacteristic(string name, string service, string characteristic,
                         byte[] data, int length, bool withResponse, Action<string> action)
```

Frames are small (≤ ~16 bytes after COBS) so each command is a single GATT write — no
fragmentation/MTU handling is needed. (Our Python client uses write-without-response,
which is how the Hackaday driver works in practice.)

## 3. Framing — `HermesPacket.CreateRequest()` and the checksum

A `HermesPacket` (dump.cs:443587) holds the raw payload `byte[] data` plus static
`ChecksumLength`/`TerminatorLength`. The wire frame is:

```
wire = COBS(payload) ++ checksum ++ 0x00
```

* **COBS** (Constant Overhead Byte Stuffing) removes every `0x00` from the body so the
  single trailing `0x00` is an unambiguous delimiter.
* **checksum** = `(sum(cobs_bytes) mod 255) + 1`. Confirmed from
  `HermesPacket.CalculateChecksum` (VA `0x1B01F34`): it sums the bytes, then the
  `movw/movt r0,#0x80808081 ; smmla ; … ; rsb r0,r0,r0,lsl#8 ; sub` sequence is the
  classic *divide-by-255* → it computes `sum mod 255`, then `+1`, then `uxtb`. The result
  is always **1..255**, so the checksum can never be mistaken for the `0x00` terminator.

Verified byte-exact (computed == captured):

| meaning               | payload       | wire frame               |
|-----------------------|---------------|--------------------------|
| ConnectionEstablished | `[16]`        | `02 10 13 00`            |
| GameState(1)          | `[7,1]`       | `03 07 01 0C 00`         |
| Transform neutral     | `[6,0,0,0]`   | `02 06 01 01 01 0C 00`   |

## 4. Encoding a request — the `Encode()` pattern

Every `…Request.Encode()` follows the same shape (the dump's RVA is a tiny thunk
`add r0,r0,#8 ; b <real>` that fixes the struct `this` pointer, then tail-calls the real
body):

```
r4 = new byte[UnstuffedLength]      // IL2CPP byte[]: length @ +0xC, data @ +0x10
data[0] = cmd_id
data[1..] = each field, low byte (strb).  floats go through vcvt.s32.f32 first.
return HermesPacket(data)
```

`UnstuffedLength` is a per-request constant (the pre-COBS payload size). `Transform`
returns 5; `SetLegJointAngles` returns 13; etc. There is **no sequence number** and **no
per-field scaling** — fields are emitted as raw low bytes in struct order.

## 5. Confirmed per-command encodings

| cmd | name | bytes | wire layout (each value = signed int8 low byte) | Encode @ |
|----:|------|------:|--------------------------------------------------|----------|
| 16  | ConnectionEstablished | 1 | `[16]` | — |
| 7   | GameState | 2–3 | `[7, GameState, ForceDefaults?]` | — |
| 6   | **Transform** (drive) | 5 | `[6, Mode, AxisA(strafe), AxisB(fwd), AxisC(turn)]` — Mode is byte #1; driving Mode=Walking=3; axes clamp ±127; floats via `vcvt` (no scale) | `0x1866DE8` |
| 46  | HeadColourSet | 4 | `[46, R, G, B]` | — |
| 8   | KinematicStance | 2 | `[8, KinematicStanceType]` | — |
| 58  | **SetLegJointAngles** | 13 | `[58, FL.Knee, FL.Thigh, FL.Hip, FR.Knee, FR.Thigh, FR.Hip, BL.Knee, BL.Thigh, BL.Hip, BR.Knee, BR.Thigh, BR.Hip]` — per-leg order **Knee, Thigh, Hip**; legs FL,FR,BL,BR | `0x185DAA8` |
| 220 | PlayAnimation | ≥2 | `[220, AnimationId, …]` (blend/layer fields follow) | — |
| 247 | KillStreams | 1 | `[247]` | — |

### Notes that bit us
* **Transform `Mode` is byte #1**, not appended at the end — easy to get wrong.
* **SetLegJointAngles is Knee, Thigh, Hip per leg** (struct offsets +4,+8,+0), not the
  declaration order Hip,Knee,Thigh.
* **Checksum is `mod 255`**, not `mod 256` — only matters once a frame's byte sum reaches
  255 (e.g. a bright `HeadColourSet(255,255,255)`), where the naive version sends a wrong
  (or `0x00`-colliding) checksum and the robot rejects the frame.

`mekamon/protocol.py` and `mekamon/commands.py` implement all of the above;
`il2cpp/analyze_send.py` reproduces the disassembly.
