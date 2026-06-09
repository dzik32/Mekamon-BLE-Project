"""Frozen-build sanity check for the Bleak + WinRT backend.

    python tools/ble_selftest.py

Distinguishes a *bundling* failure (the WinRT backend didn't get packaged) from a
harmless runtime issue (no/disabled Bluetooth adapter). As long as you don't see
IMPORT-FAIL, the Windows BLE stack froze correctly.
"""
import asyncio


def main():
    try:
        from bleak import BleakScanner
        import bleak.backends.winrt.scanner  # the Windows backend module
    except Exception as e:  # pragma: no cover
        print("IMPORT-FAIL:", repr(e))
        return

    async def run():
        try:
            devs = await BleakScanner.discover(timeout=1.0)
            print(f"BLE-OK ({len(devs)} device(s) seen)")
        except Exception as e:
            print("BLE-IMPORT-OK (scan raised, likely no adapter):", repr(e))

    asyncio.run(run())


if __name__ == "__main__":
    main()
