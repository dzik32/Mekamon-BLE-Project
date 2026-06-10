"""Build a single self-contained Windows .exe of the MekaMon GUI.

Run:  python build.py
Output:  dist/MekamonController.exe

The .exe embeds Python, bleak, PySide6 and the app, so the end user needs nothing
installed — they just double-click it. (Requires PyInstaller to *build*:
``python -m pip install pyinstaller``.)
"""
import os

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(ROOT, "assets", "icon.ico")

# WinRT is split across PEP-420 namespace packages that PyInstaller can miss; name
# the Bluetooth-related ones explicitly so Bleak's Windows backend works when frozen.
WINRT_MODULES = [
    "winrt.windows.devices.bluetooth",
    "winrt.windows.devices.bluetooth.advertisement",
    "winrt.windows.devices.bluetooth.genericattributeprofile",
    "winrt.windows.devices.enumeration",
    "winrt.windows.devices.radios",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt.windows.storage.streams",
    "winrt.system",
]


def build_args(name="MekamonController", entry=os.path.join("gui", "app.py"),
               windowed=True, onefile=True):
    args = [
        entry,
        "--name", name,
        "--paths", ".",
        "--collect-all", "bleak",
        "--collect-all", "winrt",
        "--noconfirm",
        "--clean",
    ]
    args.append("--onefile" if onefile else "--onedir")
    args.append("--windowed" if windowed else "--console")
    for m in WINRT_MODULES:
        args += ["--hidden-import", m]
    # bundle the recovered animations + gait presets so the GUI can play them
    for sub in ("motions", "gaits"):
        d = os.path.join(ROOT, "assets", sub)
        if os.path.isdir(d):
            args += ["--add-data", f"{d}{os.pathsep}assets/{sub}"]
    if os.path.exists(ICON):
        args += ["--icon", ICON]
    return args


def main():
    PyInstaller.__main__.run(build_args())
    print("\nBuilt: dist/MekamonController.exe")


if __name__ == "__main__":
    main()
