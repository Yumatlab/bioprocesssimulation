"""Build a double-clickable launcher for the checked-out source.

Not the distribution build — that is `build/macos.spec`, and it packs a copy
of everything. This one is a four-file wrapper that starts the interpreter of
this working copy, so it always runs whatever is in the source tree right now.
For developing and for teaching off a checkout, that is the one you want.

    python tools/make_launcher.py            # ~/Applications (macOS)
    python tools/make_launcher.py --into ~/Desktop

On Windows it writes a .cmd file instead: a shortcut (.lnk) needs pywin32,
and a batch file works everywhere without it.
"""

import argparse
import os
import plistlib
import shutil
import stat
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_NAME = "Biofermentation Simulation"
BUNDLE_ID = "de.haw-hamburg.biofermentation"


def interpreter() -> Path:
    """The Python that runs the application — this project's, not the system's."""
    local = REPO / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    return local if local.is_file() else Path(sys.executable)


def version() -> str:
    for line in (REPO / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return "0.0"


def make_macos_app(target: Path) -> Path:
    """A minimal .app bundle: Info.plist, a launch script and the icon.

    macOS reads the bundle around a process, so the Dock entry gets the name
    and the icon from here even though what actually runs is a Python.
    """
    bundle = target / f"{APP_NAME}.app"
    contents = bundle / "Contents"
    macos, resources = contents / "MacOS", contents / "Resources"
    if bundle.exists():
        shutil.rmtree(bundle)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    launcher = macos / "launch"
    launcher.write_text(
        "#!/bin/sh\n"
        "# Written by tools/make_launcher.py — edit that, not this.\n"
        f'exec "{interpreter()}" -m biofermentation.gui.app "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    icon = REPO / "src" / "biofermentation" / "resources" / "icons" / "icon.icns"
    if icon.is_file():
        shutil.copy(icon, resources / "icon.icns")

    plist = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "launch",
        "CFBundleIconFile": "icon.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version(),
        "CFBundleVersion": version(),
        # Without this the window is drawn at half resolution and every label
        # in it looks like a screenshot of a label.
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
    return bundle


def make_windows_shortcut(target: Path) -> Path:
    """A .cmd file. A real .lnk would need pywin32 for one line of convenience."""
    script = target / f"{APP_NAME}.cmd"
    script.write_text(
        "@echo off\r\n"
        "rem Written by tools/make_launcher.py — edit that, not this.\r\n"
        f'start "" "{interpreter()}" -m biofermentation.gui.app %*\r\n',
        encoding="utf-8",
    )
    return script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--into",
        type=Path,
        default=None,
        help="where to put it (default: ~/Applications on macOS, the Desktop otherwise)",
    )
    arguments = parser.parse_args()

    if arguments.into is not None:
        target = arguments.into.expanduser()
    elif sys.platform == "darwin":
        target = Path.home() / "Applications"
    else:
        target = Path.home() / "Desktop"
    target.mkdir(parents=True, exist_ok=True)

    made = make_macos_app(target) if sys.platform == "darwin" else make_windows_shortcut(target)
    print(f"{made}\n  runs {interpreter()} -m biofermentation.gui.app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
