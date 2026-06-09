"""mekamon — a Bleak-based controller for Reach Robotics MekaMon robots.

No firmware modification: this talks to the stock robot over its Nordic UART Service
using the reverse-engineered "Hermes" protocol (see ``MEKAMON_PROTOCOL.md``).
"""
from . import commands, protocol
from .protocol import PacketType, build_frame

__version__ = "0.1.0"

__all__ = [
    "commands",
    "protocol",
    "PacketType",
    "build_frame",
]

# The BLE transport needs `bleak`. Keep the pure protocol/commands layer importable
# (and testable) even when bleak isn't installed.
try:
    from .ble import NUS_RX, NUS_SERVICE, NUS_TX, FoundDevice, MekamonBLE, scan
    from .controller import MekamonController

    __all__ += [
        "MekamonController",
        "MekamonBLE",
        "FoundDevice",
        "scan",
        "NUS_SERVICE",
        "NUS_RX",
        "NUS_TX",
    ]
except ModuleNotFoundError as _e:  # pragma: no cover - bleak not installed
    _BLE_IMPORT_ERROR = _e
