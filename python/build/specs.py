"""Shared parts of the PyInstaller spec files (plan section 7.1).

Both platforms bundle the same thing — the Python runtime, the dependencies
and the resources — and differ only in what comes out at the end: a single
.exe on Windows, an .app bundle on macOS. Keeping the common half here means
a resource added to the package has to be declared once, not twice.

Run from the repository root:

    pyinstaller build/windows.spec
    pyinstaller build/macos.spec
"""

import os
from pathlib import Path

APP_NAME = "Biofermentation Simulation"
EXECUTABLE_NAME = "BiofermentationSimulation"
BUNDLE_ID = "de.haw-hamburg.biofermentation"

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "biofermentation"
ENTRY_POINT = str(ROOT / "build" / "entry.py")


def target_arch() -> str | None:
    """Which architecture the macOS bundle is built for.

    None means the one the build runs on. universal2 sounds better and often
    is not possible: it needs *every* dependency as a universal wheel, and a
    single-architecture numpy fails the build outright with
    "is not a fat binary". Set BIOFERMENTATION_TARGET_ARCH=universal2 when the
    environment can actually do it.
    """
    value = os.environ.get("BIOFERMENTATION_TARGET_ARCH", "").strip()
    return value or None


def data_files() -> list[tuple[str, str]]:
    """Everything the application reads at runtime and does not import.

    The destination paths mirror the package layout, so
    resources.resource_root() finds them at the same relative place whether
    the code runs from the source tree or from a bundle.
    """
    resources = PACKAGE / "resources"
    return [
        (str(resources / "SimulationAppDB_template.db"), "biofermentation/resources"),
        (str(resources / "defaults"), "biofermentation/resources/defaults"),
        (str(resources / "styles"), "biofermentation/resources/styles"),
        (str(resources / "layouts"), "biofermentation/resources/layouts"),
        (str(resources / "icons"), "biofermentation/resources/icons"),
        # Die beiden Hochschullogos des Info-Tabs. Fehlen sie, zeigt der
        # Tab eine leere Zeile statt eines kaputten Bildes - aber eine
        # ausgelieferte Anwendung soll sagen, woher sie kommt.
        (str(resources / "logos"), "biofermentation/resources/logos"),
        # Organism plugins ship their parameter definitions as YAML.
        (
            str(PACKAGE / "organisms" / "escherichia_coli" / "definition.yaml"),
            "biofermentation/organisms/escherichia_coli",
        ),
    ]


def icon_file() -> str | None:
    """The application icon PyInstaller stamps on the executable.

    .icns on macOS, .ico on Windows — PyInstaller takes only the native
    format, and a missing one is a build failure rather than a warning, so it
    is reported as None when it is not there.
    """
    from biofermentation.resources import platform_icon_path

    path = platform_icon_path()
    return str(path) if path.is_file() else None


def hidden_imports() -> list[str]:
    """Modules PyInstaller's analysis cannot see.

    The organism plugins are the reason this list exists: they are found at
    runtime by pkgutil.iter_modules, never imported by name, so nothing in
    the source tells the analysis they are needed. A missing one turns into
    an empty organism list in the built application and nothing else — the
    kind of failure that only shows up after the release.
    """
    return [
        "biofermentation.organisms.escherichia_coli",
        "biofermentation.organisms.escherichia_coli.model",
        "biofermentation.organisms.escherichia_coli.ode",
        "biofermentation.organisms.pichia_pastoris",
        "biofermentation.organisms.pichia_pastoris.model",
        "biofermentation.organisms.pichia_pastoris.ode",
        # scipy picks its integrator at runtime, the same way.
        "scipy.integrate",
        "scipy.integrate._ivp",
    ]


def excludes() -> list[str]:
    """Left out to keep the download from doubling for nothing."""
    return [
        "tkinter",
        "matplotlib",
        "pandas",  # only the reference comparison in the tests needs it
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.QtMultimedia",
        "PySide6.QtBluetooth",
    ]
