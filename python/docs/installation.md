# Installation and distribution

Project plan §7 · replaces the earlier section on the MATLAB compiler

---

## For users

**No Python is needed** and **no administrator rights**. Both files are under
[Releases](https://github.com/Yumatlab/bioprocesssimulation/releases) on the
latest tag.

| System | File | Use |
|---|---|---|
| Windows | `BiofermentationSimulation.exe` | double-click, no installation |
| macOS | `BiofermentationSimulation-macos.zip` | unzip, drag the app into `/Applications` |

The macOS download is a zip because an `.app` is a folder, and a folder does
not survive the way GitHub hands files out: the executable bit and the internal
symlinks are lost, and what arrives is a few hundred loose files. The archive is
made on the build machine with macOS's own `ditto`, which keeps both.

### The warning on first start

Neither file is signed. That is a deliberate decision: real signing costs a
yearly Apple Developer membership on macOS and a certificate on Windows — out of
all proportion for an application of this size. The consequence is a warning on
first start, and it appears for **every** unsigned program alike.

**Windows** reports "Windows protected your PC".
→ *More info* → *Run anyway*.

**macOS** refuses the double-click with "cannot be opened because it is from an
unidentified developer".
→ right-click (or Ctrl-click) the app → *Open* → *Open* again in the dialog.
After that it starts normally.

Both only have to be done once.

### Checking that the file is the one that was built

Every release lists the SHA-256 of each file, in its text and as
`SHA256SUMS.txt`. A checksum that matches says the bytes on your disk are the
bytes the build produced; it is the statement that carries weight here, and it
costs one command.

**Windows**, in PowerShell, in the folder you downloaded into:

```powershell
Get-FileHash .\BiofermentationSimulation.exe -Algorithm SHA256
```

**macOS**, in Terminal:

```bash
shasum -a 256 ~/Downloads/BiofermentationSimulation-macos.zip
```

Compare what comes back with the line in the release. Upper and lower case do
not matter; every other character does. If they differ, do not open the file —
either the download broke or it is not the file that was built.

**One step further**, if this repository is public: every build is attested by
GitHub, which records that this exact file came out of this exact commit in
this workflow. With the [GitHub CLI](https://cli.github.com/) installed:

```bash
gh attestation verify BiofermentationSimulation-macos.zip --repo Yumatlab/bioprocesssimulation
```

That is a stronger statement than a code-signing certificate, and it costs
nothing. It is not available for a private repository on a free plan — the
release then carries the checksums alone, and the build step that would have
produced the attestation is allowed to fail without taking the release with
it.

> **A private repository has one more consequence:** only people invited to it
> can download a release at all. To hand the application to a course, either
> make the repository public or pass the two files on another way — and then
> the checksums from the release are what somebody compares against.

### Where the data lives

The shipped template is never written to; a copy of your own is created on first
start:

| System | Path |
|---|---|
| Windows | `%APPDATA%\Biofermentation Simulation\SimulationAppDB.db` |
| macOS | `~/Library/Application Support/Biofermentation Simulation/SimulationAppDB.db` |
| Linux | `~/.local/share/biofermentation/SimulationAppDB.db` |

A `style.qss` in the same directory replaces the shipped appearance (see
`gui/style.py`). The environment variable `BIOFERMENTATION_DB` points at another
database, for instance to run two installations side by side.

---

## Starting from source

```bash
pip install -e .
biofermentation
```

or without installing:

```bash
python -m biofermentation
```

---

## Building it yourself

```bash
pip install -e ".[build]"
pyinstaller --noconfirm build/windows.spec     # on Windows
pyinstaller --noconfirm build/macos.spec       # on macOS
```

Both specifications share `build/specs.py` — what is declared there holds for
both platforms. The result is in `dist/`.

PyInstaller has no cross-compiling: a Windows file is only produced on Windows.
That is exactly why the CI builds both.

### What is bundled

`build/specs.py` declares three things, and all three have a reason:

**Data files.** The template database, the CSV default data set, the stylesheet
and the organisms' `definition.yaml`. The target paths mirror the package
structure so that `resources.resource_root()` finds them at the same relative
place inside the bundle as in the source tree.

**Hidden imports.** The organism plugins are found at runtime through
`pkgutil.iter_modules` and are never imported by name. To PyInstaller's analysis
they are therefore invisible. If one is missing, the built application starts
without an error message — only with an empty organism list. A test in
`tests/test_packaging.py` compares the list against what `discover_organisms()`
actually finds.

**Exclusions.** `tkinter`, `matplotlib`, `pandas` and the unused Qt modules. Only
the reference comparison in the tests needs `pandas`, not the application.

---

## Automatic builds

A tag of the form `v*` triggers the build matrix:

```bash
git tag v3.0.0
git push origin v3.0.0
```

The CI first runs the tests on all three systems, then builds on Windows and
macOS and attaches both results to a release entry, together with their SHA-256
checksums in `SHA256SUMS.txt` and in the release text. No build without green
tests — `needs: test`.

**Build first, tag second.** The same matrix runs from the Actions tab through
*Run workflow* without producing a release, and that is the order to use: a tag
whose build fails is a release to withdraw. Cross-compiling does not exist in
PyInstaller, so this is also the only way to find out whether the Windows file
works at all.

---

## Distribution: what is in the package

The application's own code is under MIT (`LICENSE`). A **packaged** version is
more than that code, though: PyInstaller puts the interpreter and every
dependency in with it, and among those is Qt — through PySide6, under the **GNU
Lesser General Public License v3**.

Anyone distributing the built single file therefore owes:

- the text of the LGPLv3 next to the file,
- the notice that the application uses Qt and under which licence,
- and the ability to replace the Qt libraries with a version of one's own. For a
  single file that practically means: ship or link the source code of this
  application, so that the build can be repeated with a different Qt. A
  directory build instead of a single file (leaving out `runtime_tmpdir`) makes
  it more immediate, because the Qt libraries then sit beside it as their own
  files.

None of this applies to distributing the **source code** — there everyone
installs PySide6 themselves.

## Known limitations

- **Unsigned**, see above.
- **An application mark of its own.** The original's logo is a visual asset of
  the university and does not belong in this port; `resources/icons/` carries one
  of its own instead, and both specifications stamp it in through
  `specs.icon_file()`.
- **The macOS bundle is for the architecture of the machine that built it.** A
  `universal2` bundle that runs on Intel and Apple Silicon requires *every*
  dependency as a universal wheel — a single-architecture numpy makes the build
  abort with "is not a fat binary". Where the prerequisite is met:
  `BIOFERMENTATION_TARGET_ARCH=universal2 pyinstaller build/macos.spec`.
- **The first start takes a while.** A single file unpacks itself into a
  temporary directory on every start. That costs noticeable time on Windows;
  anyone who would rather avoid it builds into a directory instead of a file, by
  leaving out `runtime_tmpdir=None`.
