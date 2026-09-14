"""What a frozen build needs (plan section 7).

A packaging mistake does not fail here — it fails after the release, in a
window that opens with an empty organism list or no database at all. These
tests check the two things that go wrong most easily: a resource that stops
being collected, and a plugin the analysis cannot see because nothing
imports it by name.
"""

import ast
import sys
from pathlib import Path

import pytest

from biofermentation.resources import (
    DEFAULTS_DIR,
    STYLES_DIR,
    TEMPLATE_DB,
    bundled_files,
    resource_root,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build"
SPECS = BUILD_DIR / "specs.py"


@pytest.fixture(scope="module")
def specs():
    """build/specs.py, imported without PyInstaller being installed."""
    sys.path.insert(0, str(BUILD_DIR))
    try:
        import specs as module

        return module
    finally:
        sys.path.remove(str(BUILD_DIR))


# ------------------------------------------------------------ the version --


def test_the_bundle_is_stamped_with_the_package_version():
    """The .app takes its stamp from the same line the window reads.

    Three places held a copy and two of them said 0.1.0 while the window said
    3.0. pyproject.toml has no number of its own any more either — hatch
    reads it from `biofermentation.__version__`, and so does this.
    """
    import biofermentation

    sys.path.insert(0, str(BUILD_DIR.parent / "tools"))
    try:
        import make_launcher
    finally:
        sys.path.pop(0)

    assert make_launcher.version() == biofermentation.__version__

    pyproject = (BUILD_DIR.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'path = "src/biofermentation/__init__.py"' in pyproject


def test_the_licence_is_declared_where_anyone_would_look():
    """Four places, and the port was missing from all of them.

    The Information tab carried the MATLAB application's CC BY 4.0 paragraph
    and nothing about this implementation, which left the port under "all
    rights reserved" in the one place someone would look it up.
    """
    from biofermentation.gui.windows.control_app import ABOUT_TEXT

    root = BUILD_DIR.parent
    licence = (root / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("MIT License")
    # The attribution CC BY asks for has to travel with the MIT text.
    assert "Creative Commons Attribution 4.0" in licence
    assert "Lesser General Public" in licence, "a packaged build carries Qt"
    # The lineage CC BY asks to be named, and what each name did.
    assert "Lena Sophia Kaletsch" in licence
    assert "previous developer" in licence
    assert "Luttmann" in licence

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'license = { file = "LICENSE" }' in pyproject

    assert "MIT License" in ABOUT_TEXT
    assert "creativecommons.org/licenses/by/4.0" in ABOUT_TEXT
    assert "Lena Sophia Kaletsch" in ABOUT_TEXT
    assert "previous developer" in ABOUT_TEXT
    assert "## Lizenz" in (root / "README.md").read_text(encoding="utf-8")


# --------------------------------------------------------- the resources --


def test_every_bundled_file_exists():
    missing = [name for name, path in bundled_files().items() if not path.exists()]
    assert missing == [], f"not shipped: {missing}"


def test_the_resource_root_follows_the_bundle(monkeypatch, tmp_path):
    """PyInstaller unpacks into sys._MEIPASS; the paths have to follow."""
    assert resource_root() == TEMPLATE_DB.parent

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert resource_root() == tmp_path / "biofermentation" / "resources"


def test_the_default_set_is_complete():
    from biofermentation.db.seed import DEFAULT_TABLES

    missing = [t for t in DEFAULT_TABLES if not (DEFAULTS_DIR / f"{t}.csv").is_file()]
    assert missing == []


def test_the_stylesheet_ships():
    assert (STYLES_DIR / "default.qss").is_file()


def test_the_panel_layout_ships_with_the_bundle(specs):
    """The arrangement of Control Options is a file the user may replace.

    A frozen build without it would fall back to five panels in a row and
    nobody would know why.
    """
    from biofermentation.gui.panel_layout import BUNDLED_LAYOUT

    assert BUNDLED_LAYOUT.is_file()
    destinations = {destination for _, destination in specs.data_files()}
    assert "biofermentation/resources/layouts" in destinations


# ------------------------------------------------------------- the specs --


def test_both_spec_files_exist():
    assert (BUILD_DIR / "windows.spec").is_file()
    assert (BUILD_DIR / "macos.spec").is_file()


def test_the_specs_parse():
    """A spec is Python; a syntax error in one only shows during a build."""
    for name in ("windows.spec", "macos.spec", "specs.py", "entry.py"):
        source = (BUILD_DIR / name).read_text(encoding="utf-8")
        ast.parse(source, filename=name)


def test_every_declared_data_file_exists(specs):
    missing = [source for source, _ in specs.data_files() if not Path(source).exists()]
    assert missing == [], f"declared but not present: {missing}"


def test_the_data_files_land_where_the_code_looks_for_them(specs):
    """The destinations mirror the package, so resource_root() finds them."""
    destinations = {destination for _, destination in specs.data_files()}
    assert "biofermentation/resources" in destinations
    assert "biofermentation/resources/defaults" in destinations
    assert "biofermentation/resources/styles" in destinations


def test_every_organism_plugin_is_a_hidden_import(specs):
    """The registry finds plugins with pkgutil, so nothing imports them.

    PyInstaller's analysis follows imports. A plugin that is only discovered
    at runtime is invisible to it, and the built application comes up with an
    empty organism list — no error, just nothing to pick.
    """
    from biofermentation.organisms import discover_organisms

    declared = set(specs.hidden_imports())
    for name in discover_organisms():
        assert f"biofermentation.organisms.{name}" in declared, name


def test_a_plugin_without_a_definition_is_not_declared_as_data(specs):
    """Pichia ships no definition.yaml; declaring it would break the build.

    The separators are normalised before the comparison, and that is the
    whole point of this line. Under Windows these paths come back with
    backslashes, the needle never matches, and `assert not any(...)` passes
    for the wrong reason — a test that stops testing instead of failing.
    """
    declared = [str(source).replace("\\", "/") for source, _ in specs.data_files()]
    assert declared, "the specs declare no data files at all"
    assert not any("pichia_pastoris/definition.yaml" in source for source in declared)


def test_nothing_the_application_needs_is_excluded(specs):
    excluded = set(specs.excludes())
    for required in ("PySide6", "pyqtgraph", "numpy", "scipy", "yaml", "sqlite3"):
        assert required not in excluded


# ------------------------------------------------------- the entry point --


def test_the_console_script_points_at_something_callable():
    import tomllib

    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    target = config["project"]["scripts"]["biofermentation"]
    module_name, _, attribute = target.partition(":")

    import importlib

    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute))


def test_the_module_entry_point_exists():
    assert (REPO_ROOT / "src" / "biofermentation" / "__main__.py").is_file()


def test_the_target_architecture_defaults_to_the_build_machine(specs, monkeypatch):
    """universal2 needs every dependency as a universal wheel.

    A single-architecture numpy fails the build outright with "is not a fat
    binary", so it cannot be the default.
    """
    monkeypatch.delenv("BIOFERMENTATION_TARGET_ARCH", raising=False)
    assert specs.target_arch() is None

    monkeypatch.setenv("BIOFERMENTATION_TARGET_ARCH", "universal2")
    assert specs.target_arch() == "universal2"


# ------------------------------------------------------ application mark --


def test_the_icons_ship_with_the_bundle():
    """A resource that is missing in a frozen build is found after release."""
    from specs import data_files

    destinations = {destination for _, destination in data_files()}
    assert "biofermentation/resources/icons" in destinations


def test_the_icon_files_are_there():
    from biofermentation.resources import ICONS_DIR, app_icon_path, platform_icon_path

    assert app_icon_path().is_file()
    for size in (32, 64, 128, 256, 512):
        assert app_icon_path(size).is_file(), size
    assert (ICONS_DIR / "icon.ico").is_file()
    assert (ICONS_DIR / "icon.icns").is_file()
    assert platform_icon_path().is_file()


def test_the_spec_stamps_an_icon():
    """PyInstaller takes only the native format, and a missing one fails the
    build rather than warning."""
    from specs import icon_file

    path = icon_file()
    assert path is not None
    assert Path(path).suffix in (".icns", ".ico")


def test_the_logo_has_a_transparent_ground():
    """It sits on the starting screen and in the About box, both of which have
    a background of their own."""
    from PIL import Image

    from biofermentation.resources import app_icon_path

    image = Image.open(app_icon_path()).convert("RGBA")
    assert image.size == (1024, 1024)
    corners = [
        image.getpixel(point)
        for point in (
            (0, 0),
            (image.width - 1, 0),
            (0, image.height - 1),
            (image.width - 1, image.height - 1),
        )
    ]
    assert all(pixel[3] == 0 for pixel in corners), corners
