"""Scan for nearby MekaMon robots.  Run:  python examples/scan.py

Equivalent to ``python -m mekamon``. Power the robot on first.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mekamon import scan


async def main():
    print("Scanning for 6 s…")
    devices = await scan(6.0)
    if not devices:
        print("No devices found. Is the robot powered on and in range?")
        return
    for d in devices:
        star = "  ★ likely MekaMon (advertises NUS)" if d.likely_mekamon else ""
        print(f"{d.name[:28]:28} {d.address:20} {d.rssi} dBm{star}")


if __name__ == "__main__":
    asyncio.run(main())
