# PyInstaller spec for macOS — an .app bundle (plan section 7.1).
#
#     pyinstaller build/macos.spec
#
# The result is dist/Biofermentation Simulation.app, which can be dragged
# into /Applications.
#
# It is neither signed nor notarised. Gatekeeper refuses to open it on first
# double-click; the user has to allow it once through the context menu. See
# docs/installation.md.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).resolve()))

from specs import (  # noqa: E402
    APP_NAME,
    BUNDLE_ID,
    ENTRY_POINT,
    EXECUTABLE_NAME,
    data_files,
    excludes,
    hidden_imports,
    icon_file,
    target_arch,
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
    [],
    exclude_binaries=True,
    name=EXECUTABLE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    # The build machine's architecture unless told otherwise; see
    # specs.target_arch for why universal2 is not the default.
    target_arch=target_arch(),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=EXECUTABLE_NAME,
)

bundle = BUNDLE(
    collection,
    name=f"{APP_NAME}.app",
    icon=icon_file(),
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleShortVersionString": "3.0",
        "NSHighResolutionCapable": True,
        # Nothing here talks to the network or reads documents on its own.
        "LSApplicationCategoryType": "public.app-category.education",
    },
)
