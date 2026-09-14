# Projektplan: Migration zu Python + SQLite

Biofermentation Simulation App — Umzug von MATLAB App Designer zu einer plattformübergreifenden Python-Anwendung mit Plugin-fähiger Organismus-Architektur.

**Randbedingungen:** SQLite bleibt die Datenhaltung. Windows und macOS als Zielplattformen. Neue Organismusmodelle sollen ohne Codeänderung am Kern hinzufügbar sein. Vollständige Dokumentation am Ende.

**Technologiewahl:** Python 3.11+, PySide6 (Qt), pyqtgraph, scipy, sqlite3 (Standardbibliothek).

---

## Phase 0 — Fundament (1 Woche)

Bevor Code entsteht: Struktur und Werkzeuge, die alle folgenden Phasen tragen.

### 0.1 Repository-Struktur

```
biofermentation_sim/
├── pyproject.toml
├── README.md
├── docs/                        ← Phase 8
├── src/
│   └── biofermentation/
│       ├── __init__.py
│       ├── db/                  ← Phase 1
│       ├── core/                ← Phase 2 (App-Zustand, Preallokation)
│       ├── organisms/           ← Phase 2, Plugin-Registry
│       │   ├── base.py
│       │   ├── escherichia_coli/
│       │   └── pichia_pastoris/
│       ├── control/              ← Phase 3 (Phasenautomat, Regler)
│       ├── gui/                  ← Phasen 4–6
│       │   ├── windows/
│       │   ├── widgets/
│       │   └── dialogs/
│       └── resources/
│           └── SimulationAppDB_template.db
├── tests/
│   ├── reference_data/           ← MATLAB-Referenzläufe als CSV
│   ├── test_db.py
│   ├── test_organisms.py
│   └── test_control.py
└── build/
    ├── windows.spec
    └── macos.spec
```

### 0.2 Werkzeuge einrichten

- `git init`, virtuelle Umgebung, `pyproject.toml` mit Abhängigkeiten
- `pytest` für Tests, `ruff` für Linting (schnell, ersetzt mehrere ältere Tools)
- GitHub-Repository, damit Windows- und Mac-Builds später über GitHub Actions laufen können

### 0.3 Referenzdaten sichern

Aus der laufenden MATLAB-Anwendung, solange sie noch verfügbar ist:

- Ein vollständiger E.-coli-Lauf, alle Variablen, exportiert als CSV
- Ein vollständiger Pichia-Lauf, gleiche Bedingungen
- Die aktuelle `SimulationAppDB.db` als Vorlage kopieren

Diese Referenzläufe sind die einzige Absicherung, dass die Python-Version dasselbe rechnet. Ohne sie ist jede spätere Abweichung nicht mehr nachweisbar.

**Ergebnis von Phase 0:** Leeres, aber lauffähiges Projektgerüst mit CI-Grundgerüst und gesicherten Referenzdaten.

---

## Phase 1 — Datenschicht (1–2 Wochen)

### 1.1 Schema-Bereinigung zuerst

Bevor die Python-Schicht entsteht, das bekannte Schema-Problem beheben — jetzt ist der richtige Zeitpunkt, da noch keine Python-Abhängigkeit davon besteht:

- `MATCH SIMPLE` aus allen Foreign-Key-Definitionen entfernen (das `migrate_schema.sql`-Skript aus der vorherigen Session existiert bereits dafür)
- `UNIQUE (projectID, parameterID)` auf `project_parameterTab` ergänzen
- Auf einer Kopie testen, dann erst auf die produktive DB anwenden

### 1.2 Zugriffsschicht

Eine Klasse pro logischer Zuständigkeit, keine globalen Verbindungen:

```python
# db/connection.py
import sqlite3
from contextlib import contextmanager

@contextmanager
def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

Darauf aufbauend die drei zentralen Operationen aus deinem bestehenden Konzept:

- `load_phases(db_path, project_id)` — ein Laden, alle Lookup-Tabellen, Parameter, Phasen
- `save_project(db_path, project_id, state)` — ein Schreiben am Session-Ende
- `load_project_variables(db_path, project_id)` — Zeitreihen beim Fortsetzen eines Projekts

Das Zwei-Zugriffe-Prinzip bleibt vollständig erhalten — es war architektonisch richtig und ist unabhängig von der Sprache.

### 1.3 Automatisches Backup

Was in MATLAB nie umgesetzt wurde, hier von Anfang an einbauen:

```python
def save_project_with_backup(db_path, project_id, state):
    save_project(db_path, project_id, state)
    backup_path = db_path.with_suffix(".backup.db")
    shutil.copy(db_path, backup_path)
```

### 1.4 Tests

`tests/test_db.py` — Laden, Speichern, Neuladen, Werte müssen übereinstimmen. Testet gegen eine Kopie der echten Datenbank, nicht gegen Mocks.

**Ergebnis von Phase 1:** Datenschicht, die unabhängig von jeder GUI funktioniert und per `pytest` verifiziert ist.

---

## Phase 2 — Numerischer Kern und Plugin-Architektur (3–4 Wochen)

Das ist der wichtigste Teil für deine Anforderung „erweiterbar, anwenderfreundlich, transparent".

### 2.1 Die Organismus-Schnittstelle

Eine abstrakte Basisklasse definiert, was jedes Organismusmodell liefern muss:

```python
# organisms/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class OrganismMetadata:
    name: str
    display_name: str
    n_reservoirs: int
    description: str
    author: str = ""
    version: str = "1.0"

class OrganismModel(ABC):
    metadata: OrganismMetadata

    @abstractmethod
    def init_controller_states(self, a: dict) -> dict:
        """Shared across all organisms — usually just calls the default."""

    @abstractmethod
    def init_physical_constants(self, p: dict, a: dict) -> dict:
        """Bioreactor physics — usually just calls the default."""

    @abstractmethod
    def init_kinetics(self, p: dict, a: dict) -> dict:
        """Organism-specific kinetic constants."""

    @abstractmethod
    def init_variables(self, p: dict, a: dict) -> dict:
        """Initial values for v.* at t=0."""

    @abstractmethod
    def calculate_step(self, p: dict, v: dict, a: dict, idx: int, dt: float) -> dict:
        """One simulation time step. Returns updated v."""
```

Die von uns entworfenen gemeinsamen Funktionen `init_controller_states` und `init_physical_constants` bekommen eine konkrete Default-Implementierung in `organisms/shared.py`, die jedes Modell per `super()` aufrufen kann — genau das Redesign-Konzept aus der MATLAB-Session, jetzt strukturell erzwungen statt nur empfohlen.

### 2.2 Die Plugin-Registry

```python
# organisms/registry.py
import importlib
import pkgutil

_REGISTRY: dict[str, type[OrganismModel]] = {}

def register(cls):
    _REGISTRY[cls.metadata.name] = cls
    return cls

def discover_organisms():
    """Scans organisms/ for subpackages and imports them.
    Each subpackage registers itself via @register on import."""
    package = importlib.import_module("biofermentation.organisms")
    for _, name, is_pkg in pkgutil.iter_modules(package.__path__):
        if is_pkg:
            importlib.import_module(f"biofermentation.organisms.{name}")
    return _REGISTRY

def get_organism(name: str) -> OrganismModel:
    return _REGISTRY[name]()
```

Ein neues Organismusmodell wird dadurch zu einer Frage von „Ordner anlegen, Klasse schreiben, `@register` davorsetzen" — keine Datenbank-Einträge in `organismTab`/`modelTab` mehr manuell erforderlich, denn:

### 2.3 Anwenderfreundlichkeit — Organismus-Definition per Konfigurationsdatei

Für Anwender, die kein Python schreiben wollen, zusätzlich eine deklarative Ebene. Parameter, Kategorien und Variablen eines Organismus als YAML statt als Python-Code:

```yaml
# organisms/pichia_pastoris/definition.yaml
name: pichia_pastoris
display_name: "Pichia pastoris"
n_reservoirs: 2
parameters:
  - name: qS1pXm
    category: kinetics
    unit: "1/h"
    default: 0.02
    description: "Maintenance glycerol uptake rate"
  - name: kS2tox
    category: kinetics
    unit: "g/l"
    default: 40.0
variables:
  - name: cXL
    unit: "g/l"
    visible: true
    reading_rate: cyclic
```

Ein Import-Skript liest diese Datei ein und befüllt `parameterTab`, `categoryTab`, `variableTab`, `model_parameterTab` automatisch. Nur die Berechnungsfunktion selbst — die eigentliche Kinetik — bleibt Python-Code, weil sie beliebige Mathematik enthalten kann, die sich nicht deklarativ fassen lässt. Das ist der richtige Schnitt zwischen Transparenz und Notwendigkeit: Parameterverwaltung ist Konfiguration, die ODE ist Programm.

### 2.4 ODE-Übersetzung

Beide Organismen Zeile für Zeile aus MATLAB übersetzen, in dieser Reihenfolge:

1. `escherichia_coli/ode_volume.py` und `ode_luttmann.py` — die einfacheren Bilanzen zuerst
2. `escherichia_coli/model.py` — Reglerlogik, Fütterung, Substrataufnahme
3. Verifikation gegen den E.-coli-Referenzlauf aus Phase 0, bevor Pichia begonnen wird
4. `pichia_pastoris/*` analog, inklusive AOX-Induktion und Produktexpression
5. Verifikation gegen den Pichia-Referenzlauf

```python
# tests/test_organisms.py
import numpy as np
import pandas as pd

def test_ecoli_matches_matlab_reference():
    reference = pd.read_csv("tests/reference_data/ecoli_reference.csv")
    result = run_simulation("escherichia_coli", params_from(reference), n_steps=len(reference))
    for column in ["cXL", "pO2", "pH", "thetaL"]:
        np.testing.assert_allclose(
            result[column], reference[column], rtol=1e-4, atol=1e-6,
            err_msg=f"Abweichung in {column}"
        )
```

### 2.5 Performance-Check

An diesem Punkt, nicht früher: eine realistische Simulation über mehrere tausend Schritte laufen lassen und die Zeit pro Schritt gegen MATLAB messen. Bei Bedarf `numba.njit` auf die ODE-Funktionen anwenden. Diese Entscheidung jetzt zu treffen, bevor die GUI entsteht, verhindert dass eine spätere Performance-Korrektur die GUI-Schicht mit berührt.

**Ergebnis von Phase 2:** Numerisch verifizierter Simulationskern, unabhängig von jeder Oberfläche, mit einer Plugin-Architektur, in die neue Organismen ohne Eingriff in bestehenden Code eingehängt werden.

---

## Phase 3 — Phasenautomat und Steuerungslogik (1–2 Wochen)

Übersetzung von `checkStartCondition`, `checkEndCondition`, `conditionCheck`, `evaluateCondition` und der Fütterungslogik.

```python
# control/phases.py
from enum import IntEnum
from dataclasses import dataclass

class PhaseStatus(IntEnum):
    UPCOMING = 1
    PENDING = 2
    ACTIVE = 3
    ENDED = 4

class PhaseType(IntEnum):
    BLANK = 1
    STOP = 2
    PARAMETER_UPDATE = 3
    PULSE_FEED = 4
    EXPONENTIAL_FEED = 5

@dataclass
class Phase:
    process_id: int
    status: PhaseStatus
    phase_type: PhaseType
    name: str
    reservoir_id: int
    start_condition: "Condition"
    end_condition: "Condition"
    parameters: dict
```

Kein `eval()`-Äquivalent nötig — Python erlaubt direkten Attributzugriff über `getattr`, was `evaluateCondition` unmittelbar abbildet, ganz ohne die Sicherheitsbedenken, die `eval` mit sich brächte.

Die Batch-End-Erkennung (`BatchEndDetection_pO2Slope`) wird 1:1 übernommen — reines NumPy, keine Abhängigkeiten.

**Ergebnis von Phase 3:** Vollständiger Phasenautomat, testbar ohne GUI (`tests/test_control.py` simuliert eine Phasenabfolge und prüft Übergänge).

---

## Phase 4 — GUI-Grundgerüst (2 Wochen)

### 4.1 Anwendungsstruktur

```python
# gui/app.py
class SimulationApp(QApplication):
    def __init__(self):
        super().__init__(sys.argv)
        discover_organisms()          # Plugins beim Start laden
        self.starting_screen = StartingScreen()
        self.starting_screen.show()
```

### 4.2 Einfache Fenster zuerst

In dieser Reihenfolge, jedes einzeln testbar:

1. `StartingScreen` — Projekt neu/laden/löschen
2. `SelectProject` — Tabelle über `QTableView`
3. `CreateProject` — Formular mit Organismus-Dropdown, gespeist aus der Plugin-Registry
4. Die drei `DialogBox`-Fenster für Regler-Parameter

### 4.3 Timer-Mechanismus

Das architektonische Herzstück, hier zuerst absichern, bevor größere Fenster entstehen:

```python
# core/simulation_runner.py
from PySide6.QtCore import QTimer, QObject, Signal

class SimulationRunner(QObject):
    step_completed = Signal()

    def __init__(self, organism, state, speedfactor=1, interval_ms=100):
        super().__init__()
        self.organism = organism
        self.state = state
        self.speedfactor = speedfactor
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_tick)
        self.timer.setInterval(interval_ms)

    def _on_tick(self):
        for _ in range(self.speedfactor):
            self.state.check_start_condition()
            self.state.v = self.organism.calculate_step(...)
            self.state.preallocate_if_needed()
        self.state.check_end_condition()
        self.step_completed.emit()

    def start(self):
        self.timer.start()

    def pause(self):
        self.timer.stop()
```

Das `isUpdating`-Guard-Muster gegen Race Conditions zwischen Timer und UI-Callbacks — aus unserer MATLAB-Session bekannt — bleibt unverändert nötig und wird identisch umgesetzt: ein Flag, das der Timer-Tick prüft, bevor er Zustand verändert, den eine UI-Interaktion gerade anfasst.

**Ergebnis von Phase 4:** Startbarer Prototyp — Projekt anlegen, Simulation im Hintergrund laufen lassen, ohne Plot und ohne Phasenmanager. Guter Meilenstein, um zu prüfen ob sich die Portierung insgesamt richtig anfühlt.

---

## Phase 5 — ControlApp und Phasenmanager (2–3 Wochen)

### 5.1 Haupt-Tabs

`QTabWidget` mit den fünf bekannten Tabs. Reglerfelder als `QDoubleSpinBox`, Modi als `QComboBox`, Schalter als `QCheckBox` oder ein Toggle-Widget.

### 5.2 Dynamisches Phasen-Grid

Das `rebuildGridColumns`-Konzept — immer das gesamte Grid neu aufbauen statt einzelne Spaltenbreiten zu pflegen — hat sich bewährt und wird direkt übernommen:

```python
def rebuild_grid(self):
    self._clear_layout(self.phase_grid)
    for i, phase in enumerate(self.phases):
        panel = PhasePanel(phase)
        self.phase_grid.addWidget(panel, 0, i * 2)
        if i < len(self.phases) - 1:
            arrow = ArrowButton()
            self.phase_grid.addWidget(arrow, 0, i * 2 + 1)
    # add_phase_button in die letzte Spalte
```

### 5.3 Editoren als modale Dialoge

`PhaseParameterEditor`, `PhaseFeedEditor`, `PhasePanelEditor` als `QDialog`, geöffnet mit `exec()` — das direkte Äquivalent zu `waitfor(dialog)`.

**Ergebnis von Phase 5:** Funktionsgleiche Steuerungsoberfläche, Phasenautomat vollständig über GUI bedienbar.

---

## Phase 6 — Plot-Engine (2–4 Wochen)

Der aufwendigste Einzelteil, deshalb eigene Phase mit eigenem Zeitpuffer.

### 6.1 Grundplot

`pyqtgraph.PlotWidget` mit einer `ViewBox` je Variable für die versetzten y-Achsen — das direkte Gegenstück zu deiner mehrachsigen Konstruktion in `FigureApp`.

### 6.2 Templates

`plot_templateTab` und `plot_variableTab` werden unverändert übernommen — reine Konfigurationsdaten, keine MATLAB-Spezifika enthalten. Der `TemplateManager` wird ein eigenes Dialogfenster, das Farbwahl, Linienstil und Achsengrenzen über Qt-native Widgets anbietet (`QColorDialog` für Farben statt einer eigenen Farbtabelle-Auswahl).

### 6.3 Flags und Annotationen

Die Flag-Beschriftungen an Kurven (`plotFlags`-Logik) über `pyqtgraph.TextItem` und `InfiniteLine`.

**Ergebnis von Phase 6:** Vollständige Plot-Oberfläche mit Live-Update, Templates und Export.

---

## Phase 7 — Verteilung für Windows und macOS (1–2 Wochen)

### 7.1 Build-Konfiguration

`PyInstaller` mit getrennten Spec-Dateien:

```
build/windows.spec
build/macos.spec
```

Beide bündeln die Python-Laufzeit, alle Abhängigkeiten und eine leere `SimulationAppDB_template.db` in eine einzelne ausführbare Datei beziehungsweise ein `.app`-Bundle.

### 7.2 Automatisierte Builds

GitHub Actions mit einer Matrix aus `windows-latest` und `macos-latest` — jeder Tag erzeugt automatisch beide Installationsdateien, ohne dass du selbst auf beiden Systemen bauen musst:

```yaml
strategy:
  matrix:
    os: [windows-latest, macos-latest]
runs-on: ${{ matrix.os }}
steps:
  - uses: actions/checkout@v4
  - run: pip install -e .[build]
  - run: pyinstaller build/${{ matrix.os == 'windows-latest' && 'windows' || 'macos' }}.spec
```

### 7.3 Code-Signing — realistisch einordnen

Ohne Signatur warnen beide Betriebssysteme beim ersten Start („unbekannter Herausgeber"). Für eine Hobby-Anwendung ist das ein akzeptabler Kompromiss — echtes Signing kostet auf macOS eine jährliche Apple-Developer-Mitgliedschaft, auf Windows ein Zertifikat. Ein Hinweistext in der Dokumentation, wie die Warnung sicher bestätigt wird, ist die pragmatische Alternative.

**Ergebnis von Phase 7:** Herunterladbare `.exe`- und `.app`-Dateien, ohne Installation von Python oder Administratorrechten nutzbar.

---

## Phase 8 — Dokumentation (2 Wochen, parallel zu späteren Phasen begonnen)

Das ursprüngliche Inhaltsverzeichnis bleibt die Grundlage, wird aber um zwei Kapitel für die neue Architektur ergänzt:

1. Einleitung
2. Erste Schritte
3. Benutzeroberfläche der Anwendung
4. Simulation starten und bedienen
5. Phasen-Automatisierung
6. Datenbankkonzept
7. **Neuen Organismus hinzufügen** — jetzt in zwei Varianten dokumentiert: über die YAML-Konfiguration für reine Parameteränderungen, über eine neue Python-Klasse für neue Kinetik
8. Neuen Bioreaktor hinzufügen
9. **Installation und Verteilung** — ersetzt den früheren MATLAB-Compiler-Abschnitt
10. Fehlerbehebung
11. **Für Entwickler** — neu: Projektstruktur, Testphilosophie, wie ein Pull Request aussehen sollte, falls das Projekt einmal Beiträge von anderen erhält

Zusätzlich, direkt aus dem Entwicklungsprozess ableitbar:

- Ein `CONTRIBUTING.md` mit der Plugin-Schnittstelle als Kurzreferenz
- Docstrings in `organisms/base.py`, aus denen sich mit `sphinx` oder `mkdocs` automatisch eine API-Referenz erzeugen lässt

**Ergebnis von Phase 8:** Vollständiges Handbuch, das sowohl Anwender als auch zukünftige Mitentwickler abdeckt.

---

## Zeitübersicht

| Phase | Inhalt | Dauer |
|---|---|---|
| 0 | Fundament, Referenzdaten | 1 Woche |
| 1 | Datenschicht | 1–2 Wochen |
| 2 | Kern, Plugin-Architektur, Verifikation | 3–4 Wochen |
| 3 | Phasenautomat | 1–2 Wochen |
| 4 | GUI-Grundgerüst, Timer | 2 Wochen |
| 5 | ControlApp, Phasenmanager | 2–3 Wochen |
| 6 | Plot-Engine | 2–4 Wochen |
| 7 | Verteilung Windows/macOS | 1–2 Wochen |
| 8 | Dokumentation | 2 Wochen, teils parallel |
| **Gesamt** | | **13–20 Wochen** |

Bei lockerer Hobby-Taktung realistisch **4 bis 6 Monate**, mit nutzbaren Zwischenständen bereits nach Phase 4.

---

## Arbeitsweise pro Phase

Für jede Phase derselbe Ablauf, um den Token- und Zeitaufwand niedrig zu halten:

1. Neue Konversation, `/clear` falls in Claude Code
2. Kontext: „Wir sind in Phase X. CLAUDE.md und der aktuelle Stand von `src/biofermentation/<Bereich>/` sind der Ausgangspunkt."
3. Kleine Schritte, nach jedem Schritt `pytest` laufen lassen
4. Am Ende der Phase: `CLAUDE.md` aktualisieren, Zwischenstand committen, kurze Zusammenfassung was funktioniert

Ich kann bei den Phasen 0–3 (Datenschicht, Kern, Phasenautomat) am meisten eigenständig testen, weil sich alles per `pytest` verifizieren lässt, ohne dass du etwas manuell anklicken musst. Bei den Phasen 4–6 (GUI) bist du der Flaschenhals, weil ich das Ergebnis nicht sehe — dort lohnt sich besonders, kleine, einzeln überprüfbare Schritte zu machen statt ganze Fenster auf einmal.
