# PyInstaller spec for Windows — a single .exe (plan section 7.1).
#
#     pyinstaller build/windows.spec
#
# The result is dist/BiofermentationSimulation.exe: no Python installation,
# no administrator rights, no unpacking.
#
# It is not signed. Windows will warn about an unknown publisher on first
# start; see docs/installation.md for what to tell a user about that.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).resolve()))

from specs import (  # noqa: E402
    ENTRY_POINT,
    EXECUTABLE_NAME,
    data_files,
    excludes,
    hidden_imports,
    icon_file,
)

analysis = Analysis(
    [ENTRY_POINT],
    pathex=[str(Path(SPECPATH).parent / "src")],
    binaries=[],
    datas=data_files(),
    hiddenimports=hidden_imports(),
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes(),
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=EXECUTABLE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # No console window behind the application.
    console=False,
    disable_windowed_traceback=False,
    icon=icon_file(),
)
