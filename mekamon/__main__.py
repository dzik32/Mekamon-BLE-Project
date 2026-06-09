"""``python -m mekamon`` — scan for nearby MekaMon robots and print them."""
import asyncio


def scan_cli() -> None:
    from .ble import scan

    async def _run():
        print("Scanning for BLE devices (6 s)…  Power on the robot.")
        devices = await scan(6.0)
        if not devices:
            print("No BLE devices found.")
            return
        print(f"\n{'name':24} {'address':20} {'rssi':>6}")
        print("-" * 56)
        for d in devices:
            star = "  ★ likely MekaMon (NUS)" if d.likely_mekamon else ""
            print(f"{d.name[:24]:24} {d.address:20} {str(d.rssi):>6}{star}")

    asyncio.run(_run())


if __name__ == "__main__":
    scan_cli()
