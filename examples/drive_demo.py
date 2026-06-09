"""Headless demo: connect, flash the head LED, walk forward, turn, stop.

Run:  python examples/drive_demo.py
Make sure the robot has clear space around it before running.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mekamon import MekamonController


def main():
    ctl = MekamonController()
    try:
        print("Scanning…")
        devices = ctl.scan(6.0)
        target = next((d for d in devices if d.likely_mekamon), None) or (
            devices[0] if devices else None
        )
        if target is None:
            print("No robot found.")
            return
        print(f"Connecting to {target.name} [{target.address}]…")
        ctl.connect(target.device)
        time.sleep(0.5)

        ctl.set_head_colour(0, 80, 255)     # blue
        print("Walking forward 2 s…")
        ctl.set_drive(strafe=0, forward=60, turn=0)
        time.sleep(2.0)

        print("Turning 1.5 s…")
        ctl.set_drive(strafe=0, forward=0, turn=40)
        time.sleep(1.5)

        print("Stop.")
        ctl.stop()
        ctl.set_head_colour(0, 0, 0)
        time.sleep(0.3)
    finally:
        ctl.disconnect()
        ctl.shutdown()


if __name__ == "__main__":
    main()
