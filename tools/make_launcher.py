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
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_NAME = "Biofermentation Simulation"
BUNDLE_ID = "de.haw-hamburg.biofermentation"
#: Where a launch that fails before its first window says what happened.
LOG = "/tmp/biofermentation-launch.log"


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


#: The C the launcher is built from. It does two things — write a timestamp
#: into the log and exec the interpreter — and exists in this form for one
#: reason: it has to be a Mach-O. See `_build_launcher`.
LAUNCHER_C = r"""
/* Written by tools/make_launcher.py — edit that, not this. */
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/sysctl.h>

/* Am I running under Rosetta? The hardware is not asked, the process is:
   this binary carries a native slice, so being translated at all means
   something forced it, and the interpreter must be pulled back by hand or
   numpy's extension modules will not load. */
static int translated(void) {
    int value = 0;
    size_t size = sizeof(value);
    if (sysctlbyname("sysctl.proc_translated", &value, &size, NULL, 0) != 0)
        return 0;
    return value;
}

int main(int argc, char *argv[]) {
    /* A bundle that dies before its first window has nowhere to say why. */
    freopen(LOGFILE, "a", stdout);
    freopen(LOGFILE, "a", stderr);
    time_t now = time(NULL);
    char stamp[64];
    strftime(stamp, sizeof stamp, "%Y-%m-%d %H:%M:%S", localtime(&now));
    fprintf(stderr, "=== %s ===\n", stamp);
    fflush(stderr);

    char **args = calloc((size_t)argc + 6, sizeof *args);
    int n = 0;
    if (translated()) {
        args[n++] = (char *)"/usr/bin/arch";
        args[n++] = (char *)"-arm64";
    }
    args[n++] = (char *)INTERPRETER;
    args[n++] = (char *)"-m";
    args[n++] = (char *)MODULE;
    for (int i = 1; i < argc; i++)
        args[n++] = argv[i];
    args[n] = NULL;

    execv(args[0], args);
    fprintf(stderr, "could not start %s: ", args[0]);
    perror(NULL);
    return 127;
}
"""


def make_macos_app(target: Path) -> Path:
    """A minimal .app bundle: Info.plist, a launcher and the icon.

    macOS reads the bundle around a process, so the Dock entry gets the name
    and the icon from here even though what actually runs is a Python.
    """
    bundle = target / f"{APP_NAME}.app"
    contents = bundle / "Contents"
    macos, resources = contents / "MacOS", contents / "Resources"
    # Written into, not deleted and recreated: a bundle that is replaced gets
    # a new inode, and anything pointing at the old one — a Dock entry above
    # all — points at nothing afterwards.
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    _build_launcher(macos / "launch")

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
        # Never under Rosetta: see the note in the launcher.
        "LSRequiresNativeExecution": True,
        "LSMinimumSystemVersion": "11.0",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist))
    _sign(bundle)
    _register(bundle)
    return bundle


def _build_launcher(launcher: Path) -> None:
    """Compile the launcher, and fall back to a shell script if that fails.

    **The executable of a bundle has to be a Mach-O.** A shell script works
    when it is started by hand and fails in the Finder: LaunchServices reads
    the architectures out of the main executable, a script has none, and an
    application that declares no architecture is taken for an Intel one.
    Under macOS 26, where Rosetta is on its way out, that means the
    double-click opens Apple's "install Rosetta" page and the interpreter is
    never reached — no log line, no window, nothing to go on. `codesign` says
    the same thing in its own words: "app bundle with generic".

    The proof is one command, and it is worth keeping:

        mdls -name kMDItemExecutableArchitectures "…/Some.app"

    An app that runs answers x86_64 and arm64. The script bundle answered
    with an empty list.

    So the launcher is a hundred lines of C, built for both architectures, and
    the shell script stays as the fallback for a machine with no compiler —
    there it can at least be started from a terminal.
    """
    source = launcher.parent / "launch.c"
    source.write_text(LAUNCHER_C, encoding="utf-8")
    common = [
        "/usr/bin/clang",
        "-O2",
        f'-DINTERPRETER="{interpreter()}"',
        '-DMODULE="biofermentation.gui.app"',
        f'-DLOGFILE="{LOG}"',
        "-o",
        str(launcher),
        str(source),
    ]
    # Both slices if the SDK still carries them; on a machine that dropped
    # the x86_64 one, a native-only launcher is still a Mach-O and still
    # declares an architecture, which is the whole point.
    for architectures in (["-arch", "arm64", "-arch", "x86_64"], []):
        built = subprocess.run(
            common[:1] + architectures + common[1:], capture_output=True, text=True, check=False
        )
        if built.returncode == 0:
            source.unlink(missing_ok=True)
            print(f"  built for {_architectures(launcher)}")
            return
    print(f"  could not compile the launcher: {(built.stderr or built.stdout).strip()}")
    print("  falling back to a shell script — the Finder may ask for Rosetta")
    source.unlink(missing_ok=True)
    _write_launch_script(launcher)


def _architectures(binary: Path) -> str:
    result = subprocess.run(
        ["/usr/bin/lipo", "-archs", str(binary)], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "an unknown architecture"


def _write_launch_script(launcher: Path) -> None:
    """The fallback. Startable from a terminal, not reliably from the Finder."""
    launcher.write_text(
        "#!/bin/sh\n"
        "# Written by tools/make_launcher.py — edit that, not this.\n"
        "#\n"
        "# The fallback for a machine without a compiler. A script is not a\n"
        "# Mach-O, so LaunchServices reads no architecture out of this bundle\n"
        "# and may take it for an Intel application; see _build_launcher.\n"
        "#\n"
        "# The hardware is asked, not the process: under Rosetta `uname -m`\n"
        "# answers x86_64, so deciding from it would pick exactly the wrong\n"
        "# slice. hw.optional.arm64 is a property of the machine.\n"
        f'exec >>"{LOG}" 2>&1\n'
        'echo "=== $(date) ==="\n'
        'if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then\n'
        f'    exec /usr/bin/arch -arm64 "{interpreter()}" -m biofermentation.gui.app "$@"\n'
        "fi\n"
        f'exec "{interpreter()}" -m biofermentation.gui.app "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _sign(bundle: Path) -> None:
    """Sign the bundle with an ad-hoc signature.

    Without any signature Gatekeeper rejects the bundle — `spctl` says "no
    usable signature" — and a double-click in the Finder does nothing at all,
    silently. `open` from a terminal still works, which is what makes this so
    confusing to diagnose: it runs for whoever built it and for nobody else.

    Ad-hoc means "signed by no one", which is enough for a locally built
    application. It is not a substitute for signing a release; see
    docs/installation.md.
    """
    _run(["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(bundle)], "sign")


def _register(bundle: Path) -> None:
    """Tell LaunchServices the bundle exists, so Spotlight and the Finder see
    it without waiting for whatever would otherwise notice."""
    lsregister = (
        "/System/Library/Frameworks/CoreServices.framework/Frameworks"
        "/LaunchServices.framework/Support/lsregister"
    )
    _run([lsregister, "-f", str(bundle)], "register")


def _run(command: list[str], what: str) -> None:
    if not Path(command[0]).is_file():
        print(f"  could not {what}: {command[0]} is not there")
        return
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        print(f"  could not {what}: {(result.stderr or result.stdout).strip()}")


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
    if sys.platform == "darwin":
        print(f"  log: {LOG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
