# Installation und Verteilung

Projektplan §7 · ersetzt den früheren Abschnitt zum MATLAB-Compiler

---

## Für Anwender

Es wird **kein Python benötigt** und **keine Administratorrechte**. Beide
Dateien liegen unter [Releases](../../releases) am jeweils neuesten Tag.

| System | Datei | Nutzung |
|---|---|---|
| Windows | `BiofermentationSimulation.exe` | Doppelklick, keine Installation |
| macOS | `Biofermentation Simulation.app` | nach `/Programme` ziehen |

### Die Warnung beim ersten Start

Keine der beiden Dateien ist signiert. Das ist eine bewusste Entscheidung:
echtes Signieren kostet auf macOS eine jährliche Apple-Developer-Mitgliedschaft
und auf Windows ein Zertifikat — für eine Anwendung dieses Zuschnitts steht
das in keinem Verhältnis. Die Folge ist eine Warnung beim ersten Start, und
zwar bei **jedem** unsignierten Programm gleichermaßen.

**Windows** meldet „Der Computer wurde durch Windows geschützt".
→ *Weitere Informationen* → *Trotzdem ausführen*.

**macOS** verweigert den Doppelklick mit „kann nicht geöffnet werden, da sie
von einem nicht verifizierten Entwickler stammt".
→ Rechtsklick (oder Ctrl-Klick) auf die App → *Öffnen* → im Dialog erneut
*Öffnen*. Danach startet sie normal.

Beides muss nur einmal gemacht werden.

Wer sichergehen will, prüft die Prüfsumme der heruntergeladenen Datei gegen
die des Release-Eintrags — das ist die belastbare Aussage, nicht die
Signatur.

### Wo die Daten liegen

Die mitgelieferte Vorlage wird nie beschrieben; beim ersten Start entsteht
eine eigene Kopie:

| System | Pfad |
|---|---|
| Windows | `%APPDATA%\Biofermentation Simulation\SimulationAppDB.db` |
| macOS | `~/Library/Application Support/Biofermentation Simulation/SimulationAppDB.db` |
| Linux | `~/.local/share/biofermentation/SimulationAppDB.db` |

Eine `style.qss` im selben Verzeichnis ersetzt das mitgelieferte Aussehen
(siehe `gui/style.py`). Die Umgebungsvariable `BIOFERMENTATION_DB` zeigt auf
eine andere Datenbank, etwa um zwei Installationen nebeneinander zu betreiben.

---

## Aus dem Quellcode starten

```bash
pip install -e .
biofermentation
```

oder ohne Installation:

```bash
python -m biofermentation
```

---

## Selbst bauen

```bash
pip install -e ".[build]"
pyinstaller --noconfirm build/windows.spec     # unter Windows
pyinstaller --noconfirm build/macos.spec       # unter macOS
```

Beide Spezifikationen teilen sich `build/specs.py` — was dort deklariert ist,
gilt für beide Plattformen. Das Ergebnis liegt in `dist/`.

Cross-Compiling gibt es bei PyInstaller nicht: eine Windows-Datei entsteht nur
unter Windows. Genau deshalb baut die CI beide.

### Was gebündelt wird

`build/specs.py` deklariert drei Dinge, und alle drei haben einen Grund:

**Datendateien.** Vorlagendatenbank, der CSV-Standarddatensatz, das
Stylesheet und die `definition.yaml` der Organismen. Die Zielpfade bilden die
Paketstruktur nach, damit `resources.resource_root()` sie im Bündel an
derselben relativen Stelle findet wie im Quellbaum.

**Versteckte Importe.** Die Organismus-Plugins werden zur Laufzeit über
`pkgutil.iter_modules` gefunden und nirgends beim Namen importiert. Für
PyInstallers Analyse sind sie damit unsichtbar. Fehlt einer, startet die
gebaute Anwendung ohne Fehlermeldung — nur mit leerer Organismusliste. Ein
Test in `tests/test_packaging.py` vergleicht die Liste gegen das, was
`discover_organisms()` tatsächlich findet.

**Ausschlüsse.** `tkinter`, `matplotlib`, `pandas` und die ungenutzten
Qt-Module. `pandas` braucht nur der Referenzvergleich in den Tests, nicht die
Anwendung.

---

## Automatische Builds

Ein Tag der Form `v*` löst die Build-Matrix aus:

```bash
git tag v3.0.0
git push origin v3.0.0
```

Die CI führt zuerst die Tests auf allen drei Systemen aus, baut dann auf
Windows und macOS und hängt beide Ergebnisse an einen Release-Eintrag. Ohne
grüne Tests kein Build — `needs: test`.

---

## Bekannte Einschränkungen

- **Unsigniert**, siehe oben.
- **Kein Anwendungssymbol.** Das Logo des Originals ist ein Bildmittel der
  Hochschule und gehört nicht in diese Portierung; `icon=None` in beiden
  Spezifikationen ist die Stelle, an der ein eigenes eingehängt würde.
- **Das macOS-Bündel gilt für die Architektur des Bau-Rechners.** Ein
  `universal2`-Bündel, das auf Intel und Apple Silicon läuft, verlangt
  *jede* Abhängigkeit als universelles Rad — ein einzelarchitektonisches
  numpy lässt den Build mit „is not a fat binary" abbrechen. Wo die
  Voraussetzung erfüllt ist:
  `BIOFERMENTATION_TARGET_ARCH=universal2 pyinstaller build/macos.spec`.
- **Erststart dauert.** Eine Einzeldatei entpackt sich bei jedem Start in ein
  temporäres Verzeichnis. Das kostet auf Windows spürbar Zeit; wer das nicht
  will, baut ohne `runtime_tmpdir=None` in ein Verzeichnis statt in eine
  Datei.
