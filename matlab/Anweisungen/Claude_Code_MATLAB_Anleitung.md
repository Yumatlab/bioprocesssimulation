# Claude Code für die Biofermentation Simulation App

Anleitung für die Weiterentwicklung einer MATLAB-App-Designer-Anwendung mit Claude Code.

---

## 1. Das Kernproblem: `.mlapp` ist keine Textdatei

Eine `.mlapp`-Datei ist ein ZIP-Archiv. Der eigentliche Code liegt darin unter `matlab/document.xml`, eingebettet in Word-XML-Markup. Das hat drei Konsequenzen:

- Claude Code kann `.mlapp` **nicht direkt mit dem Edit-Tool bearbeiten**
- Git zeigt bei jeder Änderung nur „binary file changed" — Diffs sind nutzlos
- Die UI-Definition (`createComponents`) und die Logik liegen in derselben Datei

Das haben wir in dieser Session per Extract-Patch-Repack umgangen. Das funktioniert, ist aber fehleranfällig: mehrzeilige `sprintf`-Blöcke mit `...` haben beim Wiedereinsetzen zweimal Syntaxfehler verursacht.

**Empfehlung:** Logik schrittweise aus den `.mlapp`-Dateien in externe `.m`-Dateien verlagern. Was in einer `.m`-Datei liegt, kann Claude Code direkt lesen, ändern und versionieren.

---

## 2. Empfohlene Projektstruktur

```
Biofermentation_Simulation/
├── CLAUDE.md                    ← Projektkontext für Claude Code
├── SimulationAppDB.db
├── apps/                        ← alle .mlapp-Dateien
│   ├── ControlApp.mlapp
│   ├── FigureApp.mlapp
│   └── ...
├── src/                         ← ausgelagerte Logik (Claude Code arbeitet hier)
│   ├── db/
│   │   ├── loadPhases.m
│   │   ├── savePhases.m
│   │   ├── saveProject.m
│   │   └── dbConnect.m
│   ├── control/
│   │   ├── checkStartCondition.m
│   │   ├── checkEndCondition.m
│   │   └── evaluateCondition.m
│   └── util/
│       ├── safeNum.m
│       └── round2sig.m
├── organisms/
│   ├── Escherichia_coli.m
│   ├── Escherichia_coli_Initialization.m
│   ├── Pichia_pastoris.m
│   └── Pichia_pastoris_Initialization.m
├── Additional_functions/
│   ├── BatchEndDetection_pO2Slope.m
│   ├── centerWindow.m
│   └── meas_transfer_function.m
├── tools/                       ← Hilfsskripte für .mlapp-Handling
│   ├── mlapp_extract.py
│   └── mlapp_inject.py
└── extracted/                   ← generiert, nur zum Lesen (gitignored)
    ├── ControlApp.m
    └── FigureApp.m
```

Der Punkt bei `src/`: Methoden in App-Designer-Klassen können externe Funktionen aufrufen. Statt

```matlab
% in ControlApp.mlapp
function loadPhases(app)
    % 150 Zeilen Code
end
```

schreibst du

```matlab
% in ControlApp.mlapp — nur noch ein Einzeiler
function loadPhases(app)
    app = loadPhasesImpl(app);
end
```

und die 150 Zeilen liegen in `src/db/loadPhasesImpl.m`. Claude Code kann diese Datei direkt bearbeiten, du siehst saubere Git-Diffs, und beim Kompilieren wird sie automatisch mit eingebunden.

---

## 3. Hilfsskripte

### `tools/mlapp_extract.py`

Extrahiert den Code aus allen `.mlapp`-Dateien nach `extracted/`, damit Claude Code sie lesen kann.

```python
#!/usr/bin/env python3
"""Extrahiert MATLAB-Code aus .mlapp-Dateien zum Lesen und für Git-Diffs."""
import zipfile, re, sys
from pathlib import Path

APPS = Path("apps")
OUT  = Path("extracted")

def extract(mlapp_path):
    with zipfile.ZipFile(mlapp_path) as z:
        xml = z.read("matlab/document.xml").decode("utf-8")
    # Word-XML-Tags entfernen, CDATA-Inhalt behalten
    code = re.sub(r"<[^>]+>", "", xml)
    code = code.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    code = code.replace("&quot;", '"').replace("&apos;", "'")
    return code

def main():
    OUT.mkdir(exist_ok=True)
    for f in sorted(APPS.glob("*.mlapp")):
        target = OUT / (f.stem + ".m")
        target.write_text(extract(f), encoding="utf-8")
        print(f"{f.name} -> {target}")

if __name__ == "__main__":
    main()
```

### `tools/mlapp_inject.py`

Ersetzt eine einzelne Funktion in einer `.mlapp`-Datei. Sicherer als ein kompletter Rewrite.

```python
#!/usr/bin/env python3
"""Ersetzt eine Funktion in einer .mlapp-Datei.

Aufruf:
    python3 tools/mlapp_inject.py apps/ControlApp.mlapp saveProject patch.m

patch.m enthält die komplette neue Funktion inklusive 'function' und 'end'.
Es wird automatisch ein Backup .mlapp.bak angelegt.
"""
import zipfile, shutil, sys, re
from pathlib import Path

def find_function(code, name):
    """Findet Start- und Endindex einer Funktion über Einrückungstiefe."""
    pattern = re.compile(rf"^(\s*)function\s+[^\n]*\b{re.escape(name)}\s*\(", re.M)
    m = pattern.search(code)
    if not m:
        raise SystemExit(f"Funktion '{name}' nicht gefunden.")
    indent = len(m.group(1))
    start  = m.start()
    # Passendes 'end' auf gleicher Einrückungstiefe suchen
    end_pat = re.compile(rf"^\s{{{indent}}}end\s*$", re.M)
    m2 = end_pat.search(code, m.end())
    if not m2:
        raise SystemExit(f"Kein passendes 'end' für '{name}' gefunden.")
    return start, m2.end()

def main():
    mlapp, func_name, patch_file = sys.argv[1], sys.argv[2], sys.argv[3]
    mlapp = Path(mlapp)
    new_code = Path(patch_file).read_text(encoding="utf-8").rstrip()

    shutil.copy(mlapp, str(mlapp) + ".bak")

    with zipfile.ZipFile(mlapp) as z:
        names   = z.namelist()
        content = {n: z.read(n) for n in names}

    xml = content["matlab/document.xml"].decode("utf-8")
    start, end = find_function(xml, func_name)
    xml = xml[:start] + new_code + xml[end:]
    content["matlab/document.xml"] = xml.encode("utf-8")

    with zipfile.ZipFile(mlapp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.writestr(n, content[n])

    print(f"'{func_name}' in {mlapp.name} ersetzt. Backup: {mlapp.name}.bak")

if __name__ == "__main__":
    main()
```

---

## 4. Git einrichten

`.gitattributes`:

```
*.mlapp diff=mlapp binary
*.db    binary
```

`.gitignore`:

```
extracted/
*.mlapp.bak
*.asv
SimulationAppDB_backup*.db
```

Nach jedem Arbeitsschritt `python3 tools/mlapp_extract.py` laufen lassen und die `extracted/*.m` mit committen — dann hast du zusätzlich zum Binary auch einen lesbaren Verlauf.

---

## 5. Arbeitsteilung: Was macht wer

| Aufgabe | Wer |
|---|---|
| Logik in `src/`, `organisms/`, `Additional_functions/` ändern | Claude Code |
| SQL-Queries schreiben und prüfen | Claude Code |
| DB-Schema analysieren, Migrationsskripte | Claude Code |
| Bugs in extrahiertem Code finden | Claude Code |
| Funktionen per `mlapp_inject.py` einsetzen | Claude Code |
| **UI-Elemente hinzufügen/verschieben** | **Du, im App Designer** |
| **Callbacks anlegen** | **Du, im App Designer** |
| **Code kompilieren und testen** | **Du, in MATLAB** |

Claude Code kann MATLAB nicht ausführen. Es gibt also keinen Test-Loop — jede Änderung musst du selbst starten. Deshalb: **kleine Schritte, oft testen.** In dieser Session sind mehrfach drei, vier Bugs gleichzeitig eingebaut worden, weil zu viel auf einmal geändert wurde.

---

## 6. Praktische Regeln

**SQL-Queries immer einzeilig.** Mehrzeilige `sprintf`-Blöcke mit `...` haben beim XML-Wiedereinsetzen zweimal Syntaxfehler erzeugt. In `.m`-Dateien ist mehrzeilig unproblematisch, in `.mlapp` nicht.

**Vor jedem Eingriff in `.mlapp` ein Backup.** `mlapp_inject.py` macht das automatisch.

**DB vor Schema-Änderungen sichern.** Die Datenbank ist in dieser Session zweimal korrupt geworden.

**Ein Thema pro Session.** Claude Code arbeitet besser mit einem klaren Auftrag („Migriere `saveProject` nach `src/db/`") als mit „mach die App fertig".

**`/clear` zwischen Themen.** Verhindert, dass alter Kontext neue Aufgaben verwässert.

---

## 7. Erste Schritte

```bash
cd "Biofermentation Simulation Version 2.1"
git init && git add -A && git commit -m "Ausgangsstand vor Claude-Code-Migration"

mkdir -p tools src/db src/control src/util extracted
# CLAUDE.md und die beiden Python-Skripte anlegen

python3 tools/mlapp_extract.py
claude
```

Dann als erste Aufgabe etwas Kleines und Abgeschlossenes, um den Workflow zu testen — zum Beispiel die Migration von `saveProject` nach `src/db/`.
