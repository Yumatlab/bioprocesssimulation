# Biofermentation Simulation — Python

Python-Neuimplementierung der MATLAB-App-Designer-Anwendung Version 2.x.
Plattformen: Windows und macOS, verteilt als einzelne ausführbare Datei.

## Sprache

- Antworten im Chat: **Deutsch**
- Alle Code-Kommentare und Docstrings: **Englisch**

## Referenzdokumente

| Dokument | Rolle |
|---|---|
| `~/Documents/Biofermentation Simulation Version 2.2/Anweisungen/CLAUDE.md` | **Fachliche Referenz.** Beschreibt die MATLAB-Architektur: Datenmodell (`app.p`/`app.v`/`app.a`), Preallokations-Prinzip, Phasenautomat, Reglerlogik, DB-Regeln, bekannte Schema-Probleme. Diese Datei ist der Ist-Zustand, aus dem portiert wird — nicht der Zielzustand. |
| `~/Documents/Biofermentation Simulation Version 2.2/Anweisungen/Projektplan_Python_Migration.md` | **Phasenplan.** Neun Phasen mit Abschnittsnummern; wird eingehalten. |
| `~/Documents/Biofermentation Simulation Version 2.2/` | MATLAB-Quellcode als Übersetzungsvorlage (`Escherichia_coli/`, `Pichia_pastoris/`, `*.mlapp`). |
| `docs/verifikation_escherichia_coli.md` | **Verifikationsbericht.** Wogegen geprüft wurde, mit welchem Ergebnis, in welchem Fenster und warum es keine globale Toleranz geben kann. |

Der MATLAB-Code wird **nicht** verändert. Er ist Lesequelle, sonst nichts.

### An den Quellcode der `.mlapp`-Dateien kommen

Die Organismusmodelle liegen als `.m` offen, die gesamte Oberflächenlogik
aber in `.mlapp`-Dateien — und die sind ZIP-Archive. Der Code steht in
`matlab/document.xml`, verteilt auf `<w:t>`-Elemente:

```python
import re, html, zipfile
with zipfile.ZipFile("ControlApp.mlapp") as z:
    xml = z.read("matlab/document.xml").decode("utf-8", "replace")
code = "".join(html.unescape(t) for t in re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))
```

`ControlApp.mlapp` ergibt so 3737 Zeilen mit `loadPhases`, `savePhases`,
`saveProject`, `conditionCheck`, `checkStartCondition`, `createPhasePanel`
und dem Timer-Callback `calculationFcn`. `FigureApp.mlapp` enthält
`calculateYLimits` und `plotFlags`, `ClosingScreen.mlapp` und
`SelectProject.mlapp` die Lösch- und Anlegepfade.

Ohne diesen Schritt ist die halbe Vorlage unlesbar.

---

## Zielarchitektur

Python 3.11+, PySide6 (Qt) für die GUI, pyqtgraph für Live-Plots, scipy für
die ODE-Integration, `sqlite3` aus der Standardbibliothek, PyInstaller für die
Verteilung.

Was aus MATLAB unverändert übernommen wird, weil es sich bewährt hat:

- **Zwei DB-Zugriffe pro Session.** Einmal laden beim Start, einmal schreiben
  am Ende. Während der Simulation kein Datenbankzugriff. Alle Editoren lesen
  aus dem Speicher.
- **Preallokation.** Zeitreihen wachsen blockweise, nicht elementweise.
- **Grid komplett neu aufbauen** statt einzelne Spaltenbreiten pflegen
  (`rebuildGridColumns` → `rebuild_grid`).
- **Guard-Flag gegen Race Conditions** zwischen Timer-Tick und UI-Callback.

Was neu ist:

- **Plugin-Registry** für Organismusmodelle (`@register` + `discover_organisms`).
  Ein neues Modell ist ein Ordner mit einer Klasse — kein Eingriff in
  bestehenden Code, keine manuellen Einträge in `organismTab`/`modelTab`.
- **YAML-Konfigurationsebene** für reine Parameterdefinitionen, damit
  Anwender ohne Python-Kenntnisse Parameter ergänzen können. Die ODE bleibt
  Code: Parameterverwaltung ist Konfiguration, Kinetik ist Programm.
- **Automatisches Backup** nach jedem Speichern (in MATLAB nie umgesetzt,
  die DB ist dort zweimal korrupt geworden).

---

## Verzeichnisstruktur

```
biofermentation_sim/
├── pyproject.toml
├── README.md
├── CLAUDE.md
├── .github/workflows/ci.yml      Lint + Tests auf Linux/Windows/macOS
├── docs/                         Handbuch (Phase 8)
├── src/biofermentation/
│   ├── db/                       Zugriffsschicht (Phase 1)
│   ├── core/                     Zustand, Preallokation, Runner (Phase 2/4)
│   ├── organisms/                Basisklasse, Registry, Modelle (Phase 2)
│   │   ├── escherichia_coli/
│   │   └── pichia_pastoris/
│   ├── control/                  Phasenautomat, Regler (Phase 3)
│   ├── gui/
│   │   ├── windows/   StartingScreen, SelectProject, CreateProject,
│   │   │              ControlApp, FigureApp, DataTable
│   │   ├── widgets/   Regler-Panels, Phasenraster, Plot, Variable Pool, Log
│   │   └── dialogs/   Phasen-, Parameter-, Plot- und Exporteditoren
│   └── resources/SimulationAppDB_template.db
├── tests/
│   ├── reference_data/           MATLAB-Referenzläufe + Exportanleitung
│   ├── test_db.py
│   ├── test_organisms.py
│   └── test_control.py
└── build/                        PyInstaller-Specs (Phase 7)
```

---

## Konventionen

### Datenbank

- **Immer** `with get_connection(path) as conn:` — nie `sqlite3.connect(` ohne
  Context-Manager, nie eine globale Verbindung. In der MATLAB-Version sind
  mehrfach Bugs durch nicht geschlossene Verbindungen und verschachtelte
  Transaktionen entstanden; das ist der Grund für diese Regel.
- Keine verschachtelten Transaktionen. Ein Block, eine Verbindung.
- `COUNT(*)` statt `MAX()` zur Existenzprüfung.
- NaN-Preallokationsslots vor jedem Schreibvorgang herausfiltern.
- `PRAGMA foreign_keys = ON` und `journal_mode = WAL` setzt
  `get_connection` selbst. `readonly=True` öffnet im SQLite-Readonly-Modus und
  lässt WAL in Ruhe.
- Ein Block, eine Verbindung, **eine** Transaktion: `get_connection` öffnet
  `BEGIN` und schließt mit `COMMIT` oder `ROLLBACK`. `save_project` schreibt
  Parameter, Zeitreihen, Phasen und Log gemeinsam darin.
- **NaN wird nie geschrieben.** Preallokationsslots werden vor dem Upload
  gefiltert, NaN-Messwerte erzeugen keine `dataTab`-Zeile und kommen als NaN
  zurück. MATLAB schrieb dort 0 — aus „nicht gemessen" wurde eine gemessene
  Null.
- Der Default-Datensatz unter `resources/defaults/` ist der Wiederaufbaupfad:
  23 CSVs, `load_defaults()` / `export_defaults()`. Projektdaten sind nicht
  enthalten. Details in `resources/defaults/README.md`.

### Namensgebung

Die Fachnotation aus dem MATLAB-Modell wird **wörtlich beibehalten**: `cXL`,
`cS1L`, `qXpX`, `NSt`, `FR1`, `kLa`, `thetaL`, `pO2`. Eine Umbenennung nach
snake_case würde jeden Vergleich mit dem MATLAB-Referenzlauf unlesbar machen.
Die entsprechenden `pep8-naming`-Regeln sind in `pyproject.toml` deshalb
bewusst abgeschaltet (`N803`, `N806`, `N815`, `N816`). Für alles andere gilt
normales PEP 8.

Die drei Zustandsbehälter behalten ihre Rollen aus MATLAB:
`p` = Parameter, `v` = Variablen-Zeitreihen, `a` = Hilfsgrößen und
Reglerzustände (nicht persistiert).

### Tests

- Nach jeder Änderung `pytest`, erst weitermachen wenn grün.
- Gegen eine Kopie der echten Datenbank testen, nicht gegen Mocks.
- Kein ODE-Code ohne vorliegenden Referenzlauf. `test_organisms.py`
  überspringt die Vergleichstests, solange die CSV fehlt — ein Test, der ohne
  Referenz grün ist, beweist nichts.

---

## Altlasten in der Datenbank — Stand nach Phase 1

`db/apply_migration()` behebt alle fünf. Angewendet auf das mitgelieferte
Template; **auf die produktive `SimulationAppDB.db` im MATLAB-Ordner noch
nicht**. Der Aufruf ist idempotent und legt vorher eine Kopie an.

`apply_migration()` ist der Einstiegspunkt, nicht das SQL-Skript allein:
Punkt 5 sind zwei `ALTER TABLE ADD COLUMN`, und SQLite kennt dafür kein
`IF NOT EXISTS`. In `migrate_schema.sql` müssten sie als Tabellenneuaufbau
stehen — der beim nächsten Lauf beide Spalten samt Inhalt wieder wegwirft.
Deshalb stehen sie als `LOG_COLUMNS` in `migrate.py`.

1. **`processTab.start_typeID`/`end_typeID` zeigten auf `process_typeTab`**,
   gespeichert sind aber Bedingungstypen aus `process_conditiontypeTab`
   (1, 2 für Start; 6, 7 für Ende). 12 Fremdschlüsselverletzungen. **Behoben.**
2. **`MATCH SIMPLE` an allen Foreign Keys. Entfernt.** Anders als bisher
   angenommen war das nie die Ursache für unzuverlässige Cascades: SQLite
   parst die Klausel und ignoriert sie, MATCH SIMPLE *ist* die einzige
   Semantik, die SQLite kennt. Der reale Grund ist `PRAGMA foreign_keys`, das
   pro Verbindung standardmäßig **aus** ist — `get_connection` setzt es jetzt.
3. **`UNIQUE (projectID, parameterID)` auf `project_parameterTab`.** War im
   Template bereits vorhanden; die Migration erzwingt es trotzdem, weil die
   produktive DB den Stand nicht zwingend hat. Ermöglicht das Upsert in
   `save_project`.
4. **BIOSTAT B trug die Werte des BIOSTAT ED** bei sechs Parametern, acht
   Zeilen fehlten ganz. **Behoben** aus `Parameter Overview.xlsx`. Die
   Bioreaktoren sind die einzige Stelle, an der die Excel gegenüber der
   Datenbank Vorrang hat — überall sonst gilt die Datenbank.
5. **`logTab` fehlten `event_type` und `process_time`.** Die Anwendung führt
   fünf Felder pro Eintrag, die Tabelle hatte Platz für drei: der
   Ereignistyp landete als `[…]`-Präfix im Text, die Prozesszeit fiel weg.
   Ein wieder geöffnetes Projekt konnte seinen Log nicht rekonstruieren.
   **Behoben**, additiv. Bestandszeilen bekommen `NULL` und behalten ihren
   Text — `load_project_log()` liest das Präfix für sie zur Laufzeit heraus.
   Eine Schemamigration schreibt keine gespeicherten Daten um.

   Dazu: `_save_log` hat über `COUNT(*)` bestimmt, ab welchem Eintrag
   geschrieben wird. Das trägt nur, solange eine Sitzung genau einmal
   speichert und nie einen Log geladen hat. Jetzt trägt jeder Eintrag seine
   `logID`, und geschrieben wird, was noch keine hat.

6. **`processTab.processID` gehört der ganzen Tabelle, nicht dem Projekt.**
   Der Schlüssel ist tabellenweit `UNIQUE`, nummeriert wurde aber je Projekt:
   jedes neue Projekt fing bei 1 an, und das zweite, das gespeichert wurde,
   lief in die Phasen des ersten — `UNIQUE constraint failed`, und weil
   Parameter, Zeitreihen, Phasen und Log **eine** Transaktion sind, nahm der
   Einfügefehler die ganze Sitzung mit. `load_phases` fragt jetzt die ganze
   Tabelle, und `_claim_free_process_ids` heilt beim Speichern, was vorher
   falsch nummeriert wurde: eine Phase auf einer fremden Nummer bekommt eine
   freie und trägt sie in ihr Objekt zurück, damit `process_parameterTab`,
   Phasenraster und Plotmarkierungen dieselbe kennen. Zwei Phasen derselben
   Liste auf derselben Nummer bleiben ein Fehler und scheitern weiter laut.

Die produktive DB hatte zusätzlich eine inkonsistente Freelist
(`integrity_check` meldete vier nie benutzte Seiten). Das Template ist über
`VACUUM INTO` erzeugt und dadurch bereinigt.

## Herkunft des Templates

`resources/SimulationAppDB_template.db` ist ein `VACUUM INTO`-Abzug der
produktiven `SimulationAppDB.db` vom 11. Mai. Inhalt identisch (73 Objekte,
3737 Zeilen, Schema unverändert), Größe 49,4 MB → 0,56 MB, weil 98,9 % der
Originaldatei aus freien Seiten bestanden. Das Original liegt unverändert im
MATLAB-Projektordner.

---

## Phasenfortschritt

| Phase | Inhalt | Stand |
|---|---|---|
| 0 | Fundament, Referenzdaten | **abgeschlossen**, bis auf die Referenzläufe und das GitHub-Repository |
| 1 | Datenschicht | **abgeschlossen** |
| 2 | Kern, Plugin-Architektur, ODE-Übersetzung | **abgeschlossen**, E. coli verifiziert, Pichia offen |
| 3 | Phasenautomat | **abgeschlossen** |
| 4 | GUI-Grundgerüst, Timer | **abgeschlossen** |
| 5 | ControlApp, Phasenmanager | **abgeschlossen** |
| 6 | Plot-Engine | **abgeschlossen** |
| 7 | Verteilung Windows/macOS | **abgeschlossen** |
| 8 | Dokumentation | offen |
| — | UX-Durchgang nach dem ersten Anwendertest | **abgeschlossen**, 18 Punkte |

### UX-Durchgang — was daraus als Regel bleibt

Aus dem ersten Anwendertest kamen 18 Punkte, alle umgesetzt. Drei Erkenntnisse
gelten über den Anlass hinaus:

1. **`categoryTab.reading_rate` entscheidet, was während eines Laufs
   editierbar ist** — `cyclic` (97 Parameter: Sollwerte, Modi, Flags,
   Reglerverstärkungen, Feed Control), `once` (219: Anfangswerte wie `cS1L0`,
   Kesselgeometrie, Wachstumskinetik) und `invisible` (4, gar nicht
   angezeigt). Vor dem ersten Schritt ist alles Sichtbare editierbar, danach
   nur noch `cyclic`. **Dafür braucht die Datenbank keine neue Spalte.**
2. **Eine gestylte `QComboBox` verliert unter macOS das native Rendering**,
   und damit auch die Markierung der ausgewählten Zeile im Popup. Wer
   `QComboBox` in der QSS anfasst, muss `QComboBox QAbstractItemView` und
   dessen `selection-background-color` mitliefern.
3. **Ein `clicked`/`triggered`-Signal liefert ein `bool` als erstes Argument.**
   `plot_button.clicked.connect(self.open_plot)` ruft `open_plot(False)` auf,
   und `False` landete als `template_id` in der Datenbankabfrage. Slots mit
   optionalen Argumenten immer über ein `lambda` anbinden.
4. **Ein einfaches `QWidget` malt keinen Stylesheet-Hintergrund**, solange
   nicht `WA_StyledBackground` gesetzt ist. Betrifft alle Tabseiten; die
   Erlaubnis steht im Code, die Farbe in der QSS.
5. **Der Zustand des Phasenautomaten steht in `processTab`.** Beim Laden
   eines Projekts muss die laufende Phase übernommen werden
   (`adopt_active_phase`), sonst startet der Automat sie neu.
6. **Eine gestylte QSS-Regel nimmt dem Stil das Zeichnen ab.** Betrifft
   inzwischen drei Stellen: das Combobox-Popup, den `:checked`-Zustand einer
   QPushButton und den Kasten einer QCheckBox — die Häkchen wurden weiter
   gezeichnet, aber ein nicht angehaktes Feld war unsichtbar, und eine Liste
   davon sah leer aus. Wer ein Widget anfasst, muss auch seine Unterelemente
   mitliefern. Umgekehrt gilt: Finger weg von `QComboBox::drop-down`, sonst
   ist der Ausklapppfeil weg und aus Rahmen lässt sich keiner bauen.
7. **`isVisible()` ist keine Zustandsabfrage.** Ein Widget in einem nicht
   angezeigten Dialog meldet `False`, egal wie es gesetzt wurde. Für "ist
   dieses Feld gerade gemeint?" gilt `isVisibleTo(parent)` — oder besser die
   Bedingung selbst, so wie `PhaseEditor.accept()` den Phasentyp liest statt
   den Reservoir-Dropdown zu fragen.

### Ein Projekt zur Zeit

Jeder Weg aus einem Projekt heraus geht durch `ControlWindow.confirm_leave()`:
das Schließkreuz, Exit, und die beiden Menüeinträge, die ein anderes Projekt
öffnen. Gefragt wird mit `ClosingDialog` nach `ClosingScreen.mlapp` — Name,
Autor und Beschreibung, dann speichern, verwerfen, löschen, exportieren oder
abbrechen.

- **Vorher blieb das Control-Fenster stehen**, wenn man "Start new project"
  wählte, und ein zweites ging daneben auf. Wer das zweite und danach den
  Startbildschirm schloss, nahm das erste ungefragt und ungespeichert mit.
  `SimulationApp.release_current_project()` steht jetzt vor
  `show_create_project`, `show_select_project` und `open_project`.
- **Der Export schließt den Dialog nicht.** Exportieren ist keine Entscheidung
  über das Projekt, und eine ist noch fällig.
- **Die drei Textfelder werden mit dem Speichern geschrieben**, nicht beim
  Tippen. Im Original feuert jedes Feld sein eigenes `UPDATE` — auch auf dem
  Weg zum Löschen.
- **Löschen fragt ein zweites Mal.** Es ist nicht zurückzunehmen.
- **In Tests beantwortet `conftest.py` den Dialog** mit "verwerfen", ohne ihn
  zu zeigen. `confirm_leave()` läuft dabei wirklich; ein modaler Dialog in
  einer Fixture ist ein hängender Testlauf, und das ist zweimal passiert.

### Die Bedienelemente der Control Options

Nach dem zweiten Anwendertest sind die Schalter und die Modusauswahl neu.
Beide sind selbst gezeichnet, aber **der Zustand liegt immer in einem
Qt-Element**, nie in der Zeichnung — Fokus, Tastatur und der
Accessibility-Baum kommen von Qt, von uns kommt nur die Optik.

- **`SlideSwitch`** trägt die Flags (`f_acid`, `f_alkali`, `f_cooling`,
  `f_heating`, `f_harvest`, `f_feed`). Ein `QAbstractButton` mit einer
  animierten `Property`; `set_state_now()` ist der Ladeweg — ohne Animation
  und ohne Signal, denn ein Schalter, der beim Öffnen eines Projekts von
  allein hinüberfährt, sieht aus, als hätte ihn jemand umgelegt. `ToggleSwitch`
  ist die Zeile darum: Beschriftung links, Schalter rechts, **keine Lampe**.
  Der Schalter ist grau, wenn er aus ist, und grün, wenn er an ist; eine Lampe
  daneben sagt dasselbe ein zweites Mal. Die Lampe am Modus bleibt — sie sagt
  etwas anderes, nämlich ob der Regelkreis automatisch fährt.
- **`SegmentedControl`** ersetzt das Modus-Dropdown. Es beantwortet
  `addItem`/`findData`/`setCurrentIndex`/`currentData` und heißt sein Signal
  `currentIndexChanged` — damit tragen `select_data()` und `ControlPanel`
  beide Varianten, ohne zu wissen, welche sie halten. Passen die Tasten nicht
  nebeneinander, kommen sie in eine zweite Reihe statt zu verschwinden; die
  Höhe setzt `resizeEvent` selbst, weil `heightForWidth` in einem
  `QHBoxLayout` nicht beachtet wird und eine Tastenreihe außerhalb des Widgets
  eine ist, die niemand drücken kann.
- **Die pO2-Modi heißen ohne Präfix.** „pO2-agitation" in einem Panel namens
  pO2-Control wiederholt nur den Titel und kostete 170 px auf einer Zeile, die
  alle fünf gleichzeitig zeigen muss. Die gespeicherten Modusnummern sind
  unverändert.
- **Die Anordnung steht in `PANEL_PLACES`**, nicht im Aufbaucode: vier
  Spalten, jede über die ganze Höhe des Tabs. pH, Temperatur und pO2 nehmen je
  eine ganz, Liquid Weight und Feed teilen sich die vierte in zwei gleich
  großen Hälften. Alle vier Spalten haben dieselbe Mindestbreite.
- **Gleiche Hälften brauchen eine gemeinsame Mindesthöhe, nicht nur gleiche
  Streckung.** `setRowStretch` verteilt nur, was übrig bleibt; die beiden
  Panels brauchen von sich aus unterschiedlich viel, und das höhere behielte
  seinen Vorsprung bei jeder Fenstergröße.
- **Die Panels füllen ihre Zelle**, ohne Ausrichtung. Der Zwischenraum vor dem
  Knopf sammelt die Luft ein, also steht der Knopf am Fuß jedes Panels und
  alle vier stehen auf einer Linie.
- **Die Modusbeschriftung steht über den Tasten, nicht daneben**, mit der
  Lampe rechts in derselben Zeile. Neben ihr hätten die Tasten rund 60 px
  weniger, und pO2 fiel von zwei Tastenreihen auf vier.
- **Felder und Schalter teilen sich ein Raster aus zwei gleich breiten
  Plätzen.** Ein Sollwert mit Messwert daneben nimmt beide, alles andere
  einen, und eine Zeile wird gefüllt, bevor die nächste beginnt. Ein Schalter
  ist ein Platz breit, nicht ein Panel.
- **`content_width()` fragt das Minimum, nicht den Wunsch.** Eine
  `QDoubleSpinBox` wünscht sich die breiteste Zahl ihres Wertebereichs und die
  Modustasten wünschen sich eine Reihe. Beides muss nicht gewährt werden: die
  Felder haben eine lesbare Untergrenze, und die Tasten brechen um.
- **Eine `ValueRow` hat immer zwei Spalten**, auch ohne Messwert daneben.
  Sonst nahm ein alleinstehender Sollwert die ganze Panelbreite und die Felder
  einer Spalte kamen in zwei verschiedenen Breiten heraus.
- **Das Feed-Panel arbeitet auf einem Reservoir.** `R_feed` sagt auf welchem,
  und eine Phase kann es unter dem Panel wechseln. Deshalb tragen seine
  `FieldSpec`s ein `{n}` im Parameternamen und im Label (`cS{n}Lw`, `FR{n}w`,
  `FR{n}max`), und `ControlPanel.rows` ist nach der **Vorlage** verschlüsselt,
  nicht nach dem aufgelösten Namen — sonst wandern die Schlüssel beim Wechsel.
  Bei einem Reservoir gibt es keinen Wähler; eine Auswahl aus einem ist keine.
- **`cS{n}Lw` ist der Sinn des Closed-Loop-Modus** und fehlte im Panel. Der
  Regler lief gegen einen Sollwert, der nur über die Datenbank erreichbar war.
  `FR{n}max` steht daneben, nur lesbar — es gehört dem Reservoir, nicht dem
  Augenblick, genau wie im Original.

**Abweichung vom Original, bewusst:** Der Variable Pool zeigt `FT1` als
Säurepumpe und `FT2` als Laugenpumpe (so steht es in
`variableTab.description`). Die MATLAB-Version vertauscht die beiden in
diesem Panel — das Feld mit der Beschriftung `F_T1` liest `v.FT2`.

### Offen aus Phase 2

- **E. coli ist verifiziert.** Gegen `MyProject_11.txt`, einen Export der
  Anwendung vom 27.04.2026 — fünf Tage jünger als `Escherichia_coli.m`, also
  derselbe Code. Über die Batch-Phase (Schritte 0–402) stimmen `cXL`, `cS1L`,
  `pHL` und `thetaL` auf ≤ 1,5e-06 überein, `VL` auf 5,5e-14, die Messgrößen
  auf 1e-11. In den ersten zwölf Schritten sind es 1e-09. Eine MATLAB-Lizenz
  war dafür nicht nötig.
- **Pichia wird nicht verifiziert — bewusst.** Die Strategie der Software
  wurde geändert und dabei nur das E.-coli-Modell nachgezogen; Pichia steht
  noch auf dem älteren Ansatz. Eine Vorlage aus der aktuellen Quelle existiert
  daher nicht und ist auch nicht zu erwarten. Der einzige Lauf
  (`Thesis_SimulationAppDB.db`, Projekt 520, 02.03.2025) ist 14 Monate älter
  als `Pichia_pastoris.m` und reproduziert dessen `kLa`-Formel nicht. Der Test
  ist `skip`, nicht `xfail` — nicht fehlgeschlagen, sondern nicht anwendbar.
  Die Pichia-Übersetzung folgt der vorhandenen Quelle zeilengenau und ist über
  Struktur- und Plausibilitätstests abgesichert; das ist keine Verifikation
  und wird auch nicht als solche ausgegeben.
- **Der Vergleich reicht bis Schritt 903.** Die Fed-Batch-Phase des
  gelöschten Projekts ließ sich aus dem Lauf rekonstruieren: `FRj` aus dem
  Zustand bei Schritt 402 trifft den Wert bei 403 auf acht Nachkommastellen,
  und der Feed wächst mit exakt `qXpX1w`. Damit deckt die Verifikation seit
  Phase 3 auch den Exponentialfeed und einen Phasenübergang ab.
- **Pichia-Defaults waren verfälscht — behoben.** `default_modelTab` hatte für
  Pichia je zwei Zeilen für `yXpOgr`, `yCpO` und `qOpXm` (parameterID
  206/207/208). Die jeweils zweite trug Wert *und* Beschreibung der
  Methanol-Toxizitätsparameter `kS2tox`/`kappatox`/`qXpXtox` (309/310/311),
  die daneben korrekt existieren. Die falschen Werte waren in
  `project_parameterTab` gelandet: die Projekte 519 und 520 rechneten mit
  `yXpOgr` = 40 statt 1,773, `yCpO` = 15 statt 1,375 und `qOpXm` = 0,5 statt
  0,0117 — etwa die dreifache Sauerstoffaufnahmerate. `model_parameterTab`
  war durchgehend korrekt; nur `create_project` las von dort, `loadPhases` aus
  `default_modelTab`.

  Bereinigt mit `db/repair.py` (Werkzeug: `tools/repair_database.py`), auf
  Template und CSV-Satz angewendet. Die Erkennung rät nicht: eine Streuzeile
  trägt die Beschreibung eines anderen Parameters neben dessen eigenem Wert,
  und der Projektwert wird aus `model_parameterTab` wiederhergestellt.

  **Die neun halb angelegten Projekte bleiben stehen.** Sie sind nicht zu
  öffnen, aber sie sind auch der einzige verbliebene Beleg dafür, was der
  MATLAB-Anlegepfad getan hat — und die Grundlage der Forensik weiter unten.
  `repair()` löscht sie nur mit `remove_broken_projects=True`.
- **`variable_handlingTab` passt zu keinem der beiden Modelle.** Sieben
  E.-coli- und sechs Pichia-Zeitreihen werden gerechnet, aber keinem
  Organismus zugeordnet und daher nie gespeichert — darunter `xO2` und `xCO2`,
  die ODE-Zustände sind. Ein fortgesetzter Lauf startet sie still neu;
  `load_project_state` meldet sie jetzt in `a.restarted_variables`.
  Umgekehrt sind E. coli 19 Pichia-Variablen zugeordnet, für die es keine
  Bilanz gibt. `xfail(strict=True)` in `test_organisms.py`.
- **pO2 über 100 % ist kein Fehler.** Die Sonde wird gegen `pGcal` und
  `xOGcal` kalibriert (`cOL100 = pGcal·xOGcal/HO2`) und liest im Gleichgewicht
  `pG·xOGin/(pGcal·xOGcal)·100`. Projekt 519 begast mit 15 l/min Luft **plus
  1 l/min reinem Sauerstoff** (`f_O2` = 1, `FnO2w` = 1) — `xOGin` = 0,2588
  statt 0,2094, Gleichgewicht 124,7 %, gemessen 123,4 %. Die Bilanz rechnet
  richtig, das Projekt begast angereichert. Die früher notierten 1000 %
  stammten aus den verfälschten Pichia-Defaults und sind mit deren Bereinigung
  weg. In allen vier pO2-Modi bleibt pO2 jetzt unter der Grenze, die sein
  eigenes Gasgemisch zulässt.

### Offen aus Phase 7

- **Der Windows-Build ist ungetestet.** Cross-Compiling gibt es bei
  PyInstaller nicht; `build/windows.spec` ist geschrieben und geprüft, aber
  nur die CI kann ihn tatsächlich bauen. Das macOS-Bündel ist lokal gebaut
  und gestartet.
- **Nicht signiert**, bewusst — siehe `docs/installation.md`.

### Offen aus Phase 6

- **Zwei Templateeinstellungen wirken noch nicht.** `axisyoffset` (der Abstand
  der gestapelten Y-Achsen ergibt sich aus der Breite ihrer Beschriftungen)
  und `axisylabeloffsetabove`/`-below`. Alles andere im Settings-Dialog
  erreicht die Zeichnung.

### Offen aus Phase 5

- **`PhaseFeedEditor` fehlt noch.** `PhaseEditor` und `PhaseParameterEditor`
  sind übersetzt; der Feed-Editor des Originals nicht.

### Reglereinstellung

Die Verstärkungen der drei pO2-Regler sind experimentell neu bestimmt worden;
`tools/tune_po2.py` ist der Messstand dazu und hält die Zahlen reproduzierbar.
Gemessen an Projekt 716, bewertet über die Wachstumsphase (nach dem
Substratende steigt pO2 zwangsläufig zurück auf ~100 %, das ist keine
Reglerfrage): RMS-Abweichung Rührer 8,3 → 2,0 %, Gasmischung 16,8 → 0,9 %,
Begasung 0,9 → 0,8 %; die Stellwegsummen fallen um zwei Größenordnungen.

Zwei Dinge, die dabei zu wissen sind:

- **Die Regelabweichung wird je Regler anders normiert** — Rührer und
  Begasung durch 99, Gasmischung durch `1 - xOAIR` ≈ 0,79. Zwei
  Größenordnungen Unterschied; `KP_gasmix` stand trotzdem auf 0,4 wie ein
  Faktor für die andere Skala.
- **Der Integrator hat kein Anti-Windup.** Er integriert weiter, während der
  Ausgang am Anschlag klemmt. Das ist die MATLAB-Struktur und bleibt so; die
  Verstärkungen sind so gewählt, dass der Aufzug beim Sprung von 100 % auf
  den Sollwert klein genug bleibt, dass der Regler sich wieder erholt.

**Pichia bleibt außen vor.** Dort steht pO2 über die ganze Laufzeit über
100 % — die oben genannte Überschwingung der Sauerstoffbilanz, nicht die
Reglereinstellung. Auch mit den dokumentierten Werten für
`yXpOgr`/`yCpO`/`qOpXm` bleibt es bei RMS 93, mit alten wie mit neuen
Verstärkungen. Solange die Bilanz pO2 > 100 % zulässt, ist dort nichts zu
tunen.

### Offen aus Phase 3

- **`Mode_pH` 0, `Mode_temp` 0 und `Mode_pO2` 2/3/4 sind ungeprüft.** Der
  Referenzlauf benutzt sie nicht.
- **Der Pulsfeed ist nur strukturell getestet**, nicht gegen einen Lauf.

### Offen aus Phase 1

- **Migration auf die produktive `SimulationAppDB.db` anwenden.** Bisher nur
  auf dem Template.
- **`processTab.start_operatorID` zeigt auf `process_conditiontypeTab`**,
  sein Gegenstück `end_operatorID` auf `process_operatorTab`. Gespeichert sind
  Vergleichsoperatoren. Derselbe Fehler wie bei `end_typeID`, nur unsichtbar,
  weil die Werte 1 und 3 zufällig in beide Wertebereiche fallen. Bewusst
  nicht mitgeändert, im Skript kommentiert.
- **`xCGin` fehlt in `variableTab`.** Das Gegenstück `xOGin` ist vorhanden.

### Offen aus Phase 0

- **GitHub-Repository** anlegen und `main` pushen, damit die CI-Matrix läuft
  (Plan §0.2). Der Workflow liegt bereit und baut auf jeden `v*`-Tag beide
  Installationsdateien.
- **Lizenz** ist noch nicht festgelegt; `pyproject.toml` hat deshalb kein
  `license`-Feld.

---

## Projekte, Organismen und Bioreaktoren übertragen

Drei Pakete, alle über **Namen** verschlüsselt, nie über IDs — die
unterscheiden sich zwischen Installationen, und ein Paket mit IDs ließe sich
nur dort wieder einlesen, wo es herkommt.

| Paket | Modul | Enthält |
|---|---|---|
| Organismus | `db/definitions.py` | `organismTab`, `categoryTab`, `parameterTab`, `variableTab`, `variable_handlingTab`, `default_modelTab`, `process_variableTab` **und `modelTab`/`model_parameterTab`** |
| Bioreaktor | `db/bioreactors.py` | `bioreactorTab` und `default_bioreactorTab` |
| Projekt | `db/transfer.py` | Manifest `project.yaml` neben den lesbaren Tabellen des Exports |

Drei Dinge, die dabei gelernt wurden:

1. **Ein Organismus ohne Modell ist ein halber Organismus.** `create_project`
   liest den Parametersatz aus `model_parameterTab`; ein Import ohne
   `modelTab` sieht erfolgreich aus und scheitert beim ersten Projekt.
2. **`modelTab.name` ist tabellenweit `UNIQUE`, nicht je Organismus.** Ein
   neben seiner Vorlage importierter Organismus kollidiert auf dem Modell;
   `_free_model_name` hängt den Organismus in Klammern an.
3. **Ein Modell setzt Parameter, die der Organismus nicht definiert.** Der
   Kessel steuert seine eigenen bei, der Parametersatz eines Projekts ist die
   Vereinigung beider. Modellparameter werden deshalb gegen die ganze
   `parameterTab` aufgelöst, nicht nur gegen den Organismus.

**Der Export ist beides.** Die CSVs sind für Menschen — Phasentyp, Status,
Bedingung und Einheit ausgeschrieben statt als ID —, das Manifest ist die
Maschinenkopie davon und die einzige Datei, die der Importer liest. Prosa
zurückzuparsen wäre der falsche Weg.

**Pichia lässt sich zurzeit nicht als Organismus exportieren.** Die doppelten
Zeilen in `default_modelTab` (siehe Altlasten, Phase 2) machen es unmöglich zu
sagen, welcher Wert gilt; `export_definition` verweigert die Auskunft, statt
zu raten. Festgehalten als `xfail(strict=True)` in `test_transfer.py`.

## Projekt anlegen und löschen — in Phase 4 erledigt

Die beiden Pfade, über die die produktive Datenbank zerstört wurde, sind in
`db/project.py` neu gebaut, weil die Fenster aus Phase 4 sie brauchen.
`create_project` schreibt Projektzeile und Parametersatz in **einer**
Transaktion, `delete_project` löscht die Projektzeile und überlässt das
Kaskadieren SQLite. Kein `PRAGMA foreign_keys = OFF`, kein Nachbauen von Hand.
Die Anforderung unten bleibt als Begründung stehen.

## Anforderung an Phase 5: Projekt anlegen und löschen

Die produktive Datenbank ist über diese beiden Pfade zerstört worden. Die
Forensik ist eindeutig: von 733 je vergebenen Projekten sind 14 übrig, von
11,3 Millionen `dataTab`-Zeilen keine einzige, 98,9 % der Seiten sind frei.
Beide Pfade in der Python-Version **müssen** anders gebaut werden.

**Was in MATLAB passiert ist**

`ClosingScreen.deleteProject` schaltet die Fremdschlüssel ab
(`PRAGMA foreign_keys = OFF`, Kommentar „Manual cascade for speed"), löscht
dann von Hand aus `dataTab`, `timeTab` und `project_parameterTab`, schaltet
sie wieder ein und löscht zuletzt aus `projectTab`. Fünf einzeln
committende Anweisungen ohne Transaktion. Bricht etwas dazwischen ab, sind
alle Daten weg und die Projektzeile bleibt stehen. Das `catch` stellt das
Pragma wieder her, kann aber nichts zurückrollen — es gibt keine Transaktion.
Drei benutzte Projekte (707, 708, 712) stehen genau so in der Datenbank.

`CreateProject.CreateButtonPushed` fügt die Projektzeile ein und schreibt
danach 250 Parameterzeilen per `sqlwrite` — ebenfalls ohne Transaktion.
Projekt 732 hat 42 davon, lückenlos, endend exakt auf der höchsten je
vergebenen ID. Fünf weitere Projekte haben null.

Dazu vier verwaiste `.db-wal`-Dateien ohne zugehörige Datenbank: im
WAL-Modus committete Transaktionen stehen zunächst nur im WAL, und beim
Kopieren der `.db` ohne WAL sind sie verloren.

**Was Phase 5 daraus zu machen hat**

- `create_project` und `delete_project` sind **je eine** Transaktion über
  `get_connection`. Kein Zwischenzustand darf committet werden.
- **Das Kaskadieren macht SQLite.** Kein Nachbauen von Hand, und unter keinen
  Umständen `PRAGMA foreign_keys = OFF`. Ist das Löschen zu langsam, ist der
  Index das Mittel, nicht das Abschalten der Integritätsprüfung.
- Vor dem Löschen ein Backup über `save_project_with_backup` — die
  sqlite3-Backup-API, nie `shutil.copy`, damit das WAL mitkommt.
- Ein Test muss belegen, dass ein Abbruch mitten im Löschen **nichts**
  hinterlässt: entweder das Projekt ist vollständig weg oder vollständig da.

---

## Konventionen des Simulationskerns

- **Preallokation bleibt, die Blockgröße nicht.** `np.append` je Schritt ist
  O(n²) und kostet 7,3 s über 20 000 Schritte; MATLABs fester 20er-Block ist
  ebenfalls noch O(n²) (1,7 s bei 50 000 Schritten). `ensure_capacity`
  verdoppelt stattdessen und liegt bei 0,25 µs pro Schritt.
- **NaN heißt „nicht gerechnet".** `carry_forward` schreibt am Ende jedes
  Schritts Reihen fort, die das Modell nicht neu berechnet, statt eine Lücke
  zu hinterlassen.
- **`LSODA`, nicht `BDF`.** Über ein Fenster von 0,005 h ist das System nicht
  steif. LSODA bei rtol 1e-8 ist 6,7-mal schneller als BDF bei 1e-10 und weicht
  um 1e-6 ab. Begründung und Messreihe stehen in `core/integrate.py`.
  numba ist damit nicht nötig — 24 h Prozesszeit rechnen in 2,3 s.
- **MATLAB-Eigenheiten werden wörtlich übersetzt, nicht repariert.** Wo das
  Original einen Wert bei `idx` schreibt und im nächsten Ausdruck den bei
  `idx-1` liest, steht im Python-Code `# MATLAB lag`. Eine Korrektur vor dem
  Referenzlauf würde jede Abweichung unzuordenbar machen.

  **Vier Ausnahmen, alle in der Begasung und alle außerhalb des verifizierten
  Fensters.** Verifiziert ist der *Lauf*, nicht die Datei: Projekt 716 fährt
  `Mode_pO2` = 1 mit `f_O2` = 1, und keiner dieser Zweige wird dort betreten.
  Der Vergleich bei Schritt 403 ist nach jeder der vier Änderungen bitgleich
  geblieben — nachgemessen, nicht angenommen:

  1. `FnO2 = FnGw - FnAIR(previdx)` mischt einen aktuellen Sollwert mit einem
     vorherigen Fluss. Bei 100 % Sauerstoffanforderung geht `FnAIR` richtig
     auf null und `FnO2` wird dann `FnGw - FnGw` = 0 — **das Gas geht im
     Moment des höchsten Bedarfs aus**, gemessen 27 von 2000 Schritten. Auf
     dem Weg dorthin wird der Fluss negativ (−9 l/min bei Pichia) und `xOGin`
     verlässt [0, 1] (bis −0,48). In der Quelle steht an genau dieser Zeile
     `% HIER NOCHMAL CHECKEN`. Jetzt `FnAIR(idx)`.
  2. Die Pichia-Quelle summiert `FnG` an **allen drei** Stellen aus den
     Flüssen des vorigen Schritts, die E.-coli-Quelle an allen drei aus denen
     des aktuellen. `xOGin` teilt durch diese Summe und benutzt dabei die
     aktuellen Komponenten — gemessen fiel `xOGin` auf 0,079, wo nur Luft und
     Sauerstoff flossen und 0,209 die Untergrenze ist. Pichia rechnet jetzt
     wie E. coli.
  3. Die E.-coli-Quelle prüft `FnG(previdx) > 0` und teilt dann durch
     `FnG(idx)`. Ein Schritt ohne Gas ergibt `0/0`; das NaN wird anschließend
     von `carry_forward` durch das vorige Gemisch ersetzt und fällt nirgends
     auf. Geprüft wird jetzt der Index, durch den geteilt wird — so wie die
     Pichia-Quelle es schon tut.

  4. Die E.-coli-Quelle hat für die beiden Gase zwei Blöcke derselben Form
     untereinander, und der zweite trägt die Variable des ersten:

     ```matlab
     if app.p.f_O2 == 1
         app.v.FnO2(idx) = app.p.FnO2w;
     else
         app.v.FnAIR(idx) = 0;      % müsste FnO2 sein
     end
     ```

     Reinen Sauerstoff abzuschalten schaltete damit die **Luft** ab — und
     ließ `FnO2` ungeschrieben. Das Präallokations-NaN vergiftet die Summe
     eine Zeile weiter, `carry_forward` reicht daraufhin `FnO2` *und* die
     Gesamtmenge aus dem Vorschritt nach, und die friert auf ihrem Startwert
     ein: gemessen `FnAIR` = 0 und `FnO2` = 0 neben `FnG` = 7,5 l/min, ein
     Gasstrom, den keine Komponente speist. `xOGin` geht auf 0, `kLa` rechnet
     mit den 7,5 l/min weiter, `OTR` wird negativ, und pO2 fällt auf 0 —
     während die Oberfläche den Reaktor als begast anzeigt. `f_O2` ist ein
     `cyclic`-Flag und im Parameterdialog während des Laufs erreichbar. Die
     Pichia-Quelle hat die Zeile richtig.

  Festgehalten in `test_organisms.py`: das Einlassgemisch bleibt in
  [`xOAIR`, 1], kein Fluss wird negativ, `FnG` nie null, **`FnG` ist immer die
  Summe seiner Komponenten**, jedes Flag schreibt seinen eigenen Fluss, und
  pO2 bleibt unter dem Gleichgewicht seines eigenen Gasstroms. Die
  Summenprüfung ist die schärfste davon — sie hätte beide Defekte gefunden.
- **Qt bleibt aus `core/` heraus, bis auf eine Datei.** `core/runner.py`
  läuft ohne Oberfläche und ohne PySide6; nur `core/simulation_runner.py`
  importiert Qt, und `core/__init__.py` zieht sie nicht mit herein. Ein
  Referenzlauf oder ein Test darf nie eine GUI-Abhängigkeit brauchen.
- **Fenster öffnen keine Fenster.** Jedes gibt über ein Signal bekannt, was
  der Anwender wollte; `gui/app.py` entscheidet, was aufgeht. Nur so ist ein
  Fenster einzeln testbar.
- **Das Plot-Layout wird von Hand gebaut, nicht von `PlotItem` genommen.**
  `PlotItem` hält seine linke Achse in Spalte 0 und die ViewBox in Spalte 1,
  und `QGraphicsGridLayout` kann keine Spalte davor einfügen. Zusatzachsen in
  einer eigenen Layoutzeile umfassen auch Titel und x-Achse und sitzen dann
  ein paar Pixel versetzt. Deshalb: Zeile 1 trägt alle y-Achsen *und* die
  ViewBox, Zeile 2 nur die x-Achse. Damit sind alle Achsen exakt so hoch wie
  die Plotfläche.
- **Alle y-Achsen bekommen dieselbe Anzahl Teilungen** (`axisytick` aus dem
  Template), damit ihre Striche auf gleicher Höhe liegen und die Skalen
  quer lesbar sind. Die Zeitachse nicht — sie wächst mit dem Lauf, und
  erzwungene Teilungen ergäben dort krumme Zahlen.
- **Kein Gitter im Plot** und kein `(×0.001)` über den Achsen
  (`enableAutoSIPrefix(False)`).
- **Kurvenendlabels mit `ignoreBounds=True`**, sonst zieht das Label hinter
  dem letzten Datenpunkt die Achse bei jedem Schritt weiter.
- **Jeder Qt-Stift muss kosmetisch sein.** Ein `QPen` von Hand ist es nicht,
  seine Breite gilt dann in Datenkoordinaten und wird von der
  ViewBox-Transformation skaliert — aus einer 1,5-pt-Linie wird ein 50 px
  breites Band, und jede Kurve sieht aus wie eine Fläche. `pg.mkPen` setzt
  das Flag, ein selbst gebautes `QPen` nicht.
- **Kein `findData` mit einem `IntEnum`.** Qt vergleicht über eine QVariant,
  und die enthält einen `int` — `findData(EndCondition.TIMER)` liefert `-1`,
  wo `findData(7)` die 0 liefert. Jede ID in dieser Anwendung kommt aus einer
  Lookup-Tabelle und hat ein `IntEnum` daneben, die Falle liegt also überall
  eine Zeile entfernt. Dafür gibt es `widgets.select_data()`.
- **Jeder Schreibzugriff der Oberfläche läuft durch `runner.editing()`.**
  Ein Sollwert, der geändert wird, während ein Timer-Tick mitten im Schritt
  steht, ist genau der Fall, für den das Guard-Flag existiert.
- **Die Optik ist eine Textdatei.** `resources/styles/default.qss`; eine
  `style.qss` neben der Datenbank ersetzt sie. Farben, Abstände und Schriften
  ohne Python und ohne Neuübersetzung.
- **Die Anwendung hat ein eigenes Zeichen.** Das Logo des Originals ist ein
  Bildmittel der Hochschule und bleibt draußen; `resources/icons/` trägt
  stattdessen ein eigenes. Quelle ist `logo.png` (1024², transparent),
  daneben die Kantenlängen 32–512, `icon.ico` und `icon.icns`. Zu erreichen
  über `resources.app_icon_path(size)` und `platform_icon_path()`; gesetzt
  wird es einmal auf der `QApplication`, alle Fenster erben es. Beide
  PyInstaller-Spezifikationen stempeln es über `specs.icon_file()`.
- **Plugins brauchen einen Eintrag in `build/specs.py`.** Die Registry
  findet sie über `pkgutil.iter_modules`, also importiert sie niemand beim
  Namen und PyInstallers Analyse sieht sie nicht. Fehlt einer, startet die
  gebaute Anwendung **ohne Fehlermeldung** mit leerer Organismusliste.
  `tests/test_packaging.py` vergleicht die Liste gegen `discover_organisms()`.
- **Ressourcen über `resources.resource_root()`**, nie über
  `Path(__file__).parent` — im gepackten Zustand liegen sie unter
  `sys._MEIPASS`.
- **Die mitgelieferte Vorlage wird nie beschrieben.** `default_database()`
  legt beim ersten Start eine Kopie im Benutzerverzeichnis an — über die
  sqlite3-Backup-API, damit ein etwaiges WAL mitkommt. Im PyInstaller-Bundle
  ist die Vorlage schreibgeschützt.
- **Die beiden Organismen sind nicht vereinheitlicht.** Pichias MATLAB-Datei
  ist eine spätere Revision mit anderen Reglerabgriffen, D-Anteil auf der
  Messgröße und Anti-Windup. Jede Datei ist die Referenz für ihren Organismus.
- **Referenzvergleiche brauchen ein Fenster, keine globale Toleranz.** Der
  pH-Regler hat ein hartes Totband (`|pHw - pHL| < 0.1`), und der Prozess
  sitzt praktisch darauf: in 19 % aller Schritte liegt MATLAB näher als 1e-3
  an der Schaltschwelle. Bei Schritt 785 entscheidet eine pH-Differenz von
  1,0e-04 über die Laugenpumpe, und 1016 von 2983 Schritten fallen danach
  unterschiedlich aus. Bit-genaue Langzeitübereinstimmung ist hier **prinzipiell**
  unmöglich — kein Toleranzwert kann gleichzeitig aussagekräftig und
  erfüllbar sein. Deshalb: scharfes Fenster vor dem ersten Umschalten, danach
  nichts. Die Toleranzen in `test_organisms.py` sind gemessen, nicht geraten.

### Arbeitsweise

Eine Konversation pro Phase. Zu Beginn: Phase nennen, `CLAUDE.md` ist der
Einstieg. Am Ende jeder Phase: diese Datei aktualisieren (Stand, neue
Konventionen), committen, kurze Zusammenfassung.
