r"""Reproduce the SetLegJointAngles wire-encoding finding (see docs/joint-encoding.md).

This disassembles the `UnstuffedLength` getters and `Encode` bodies straight out of the
official app's `libil2cpp.so` with Capstone (ELF32 ARM, A32 mode; in this binary the
dump.cs Offset == VA == file offset because the first PT_LOAD has vaddr==offset==0).

NOTE: `libil2cpp.so` is a decompile artifact of a copyrighted app and is **git-ignored**
(it is not redistributed here). To run this you must place your own `libil2cpp.so` at the
path below. Requires:  py -m pip install capstone
"""
import struct

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_LITTLE_ENDIAN, Cs

SO = r"il2cpp\libil2cpp.so"   # adjust to your local artifact path
data = open(SO, "rb").read()

e_phoff = struct.unpack_from("<I", data, 0x1C)[0]
e_phentsz = struct.unpack_from("<H", data, 0x2A)[0]
e_phnum = struct.unpack_from("<H", data, 0x2C)[0]
segs = []
for i in range(e_phnum):
    p_type, p_offset, p_vaddr, _pp, p_filesz, _pm, _pf, _pa = struct.unpack_from(
        "<8I", data, e_phoff + i * e_phentsz
    )
    if p_type == 1:  # PT_LOAD
        segs.append((p_vaddr, p_offset, p_filesz))


def va_to_off(va):
    for vaddr, off, fsz in segs:
        if vaddr <= va < vaddr + fsz:
            return va - vaddr + off
    return None


md = Cs(CS_ARCH_ARM, CS_MODE_ARM | CS_MODE_LITTLE_ENDIAN)

targets = [
    ("Transform.get_UnstuffedLength (calibration -> 5)", 0x5D45BC, 0x10),
    ("SetLegJointAngles.get_UnstuffedLength (-> 0xD = 13)", 0x5D3E2C, 0x10),
]

for name, va, size in targets:
    off = va_to_off(va)
    print(f"\n=== {name} @ VA 0x{va:X} -> off 0x{off:X} ===")
    for ins in md.disasm(data[off:off + size], va):
        print(f"  0x{ins.address:X}:\t{ins.mnemonic}\t{ins.op_str}")
