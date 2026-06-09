r"""Reproduce the command-send findings in docs/command-pipeline.md.

Disassembles (Capstone, ARM/A32) the checksum, framing and key `Encode()` bodies out of
the official app's `libil2cpp.so`, following the `add r0,#8 ; b <real>` thunks and
resolving PC-relative constant loads (so float scaling factors, if any, are visible).

NOTE: `libil2cpp.so` is a copyrighted decompile artifact and is **git-ignored** — place
your own copy at the path below. Requires:  py -m pip install capstone
"""
import struct

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN, Cs
from capstone.arm import ARM_OP_MEM, ARM_REG_PC

SO = r"il2cpp\libil2cpp.so"   # adjust to your local artifact path
data = open(SO, "rb").read()

e_phoff = struct.unpack_from("<I", data, 0x1C)[0]
e_phentsz = struct.unpack_from("<H", data, 0x2A)[0]
e_phnum = struct.unpack_from("<H", data, 0x2C)[0]
segs = []
for i in range(e_phnum):
    t, off, va, _pp, fsz, _pm, _pf, _pa = struct.unpack_from("<8I", data, e_phoff + i*e_phentsz)
    if t == 1:
        segs.append((va, off, fsz))

def va_to_off(va):
    for va0, off, fsz in segs:
        if va0 <= va < va0 + fsz:
            return va - va0 + off
    return None

md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN)
md.detail = True

def const_at(va):
    off = va_to_off(va)
    if off is None:
        return None
    raw = data[off:off+4]
    return int.from_bytes(raw, "little"), struct.unpack("<f", raw)[0]

def disasm(va, n=0x200, depth=0):
    off = va_to_off(va)
    if off is None:
        print("  (VA 0x%X not mapped)" % va); return
    insns = list(md.disasm(data[off:off+n], va))
    if depth < 3 and len(insns) >= 2:
        bidx = next((i for i, ins in enumerate(insns[:3]) if ins.mnemonic == "b"), None)
        if bidx is not None:
            print("    -> THUNK to 0x%X" % insns[bidx].operands[0].imm)
            disasm(insns[bidx].operands[0].imm, n, depth+1); return
    for ins in insns:
        line = "    %08X  %-8s %s" % (ins.address, ins.mnemonic, ins.op_str)
        for op in ins.operands:
            if op.type == ARM_OP_MEM and op.mem.base == ARM_REG_PC:
                c = const_at(ins.address + 8 + op.mem.disp)
                if c:
                    line += "   ; = 0x%08X f=%g" % (c[0], c[1])
        print(line)
        if (ins.mnemonic == "bx" and "lr" in ins.op_str) or \
           (ins.mnemonic == "pop" and "pc" in ins.op_str):
            print("    --- ret ---"); break

TARGETS = [
    ("HermesPacket.CalculateChecksum", 0x5E6568),
    ("HermesPacket.CreateRequest",     0x5E6558),
    ("TransformRequest.Encode",        0x5D45F8),
    ("SetLegJointAngles.Encode",       0x185DAA8),
    ("TransformRequest.BuildMovementRequest", 0x186675C),
]
for name, va in TARGETS:
    print("\n=== %s @ 0x%X ===" % (name, va))
    disasm(va)
