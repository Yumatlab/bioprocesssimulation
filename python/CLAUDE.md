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
| `docs/verification_escherichia_coli.md` | **Verifikationsbericht.** Wogegen geprüft wurde, mit welchem Ergebnis, in welchem Fenster und warum es keine globale Toleranz geben kann. |

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

7. **`tmax` war ein Parameter, den nichts liest.** Kategorie „Settings",
   `reading_rate` = `invisible`, also in keinem Dialog sichtbar — und in
   keiner Formel: weder die Python-Modelle noch die MATLAB-Quellen greifen
   ihn ab. Die beiden Fundstellen in `FigureApp.mlapp` sind eine lokale
   Variable für den x-Bereich des Plots und ein Tooltip dazu, gleicher Name,
   andere Sache. Er stand in `parameterTab`, in beiden Organismus-Defaults, in
   drei Modellen und in fünf Projekten und entschied nirgends etwas.
   Entfernt mit `repair.remove_dead_parameters()` — getrennt von `repair()`,
   weil das Falsches richtigstellt und dies Überflüssiges wegnimmt.
   **Die Referenz-CSVs behalten ihn**: sie halten fest, was der MATLAB-Lauf
   hatte, nicht was diese Datenbank haben soll.

8. **Kein einziger Index auf einem Fremdschlüssel.** SQLite legt für einen
   Fremdschlüssel keinen an, und in dieser Datenbank stand auch keiner von
   Hand: alles, was es gab, kam von UNIQUE- und Primärschlüsseln. Beim
   Löschen eines Projekts muss SQLite deshalb für **jede** gelöschte
   `timeTab`-Zeile die ganze `dataTab` durchsuchen.

   Gemessen an zwei Stunden Prozesszeit — 3 601 Zeitzeilen gegen 201 656
   Datenzeilen:

   | | Löschen |
   |---|---|
   | ohne Index | **22,84 s** |
   | mit Index | **0,28 s** |

   Die Schreibkosten sind nicht messbar (0,54 gegen 0,53 s fürs Speichern);
   bezahlt wird mit Dateigröße, 8,1 auf 11,0 MB. Sechs Indizes stehen jetzt
   in `migrate_schema.sql`, `CREATE INDEX IF NOT EXISTS`, also idempotent wie
   der Rest. **Behoben** — und es ist genau die Antwort, die in der
   Anforderung an Phase 5 schon vorgesehen war: „Ist das Löschen zu langsam,
   ist der Index das Mittel, nicht das Abschalten der Integritätsprüfung."

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
| 8 | Dokumentation | **abgeschlossen** |
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

### Was eine Installation zeigt

`settings.yaml` neben der Datenbank, die dritte Datei dort nach `style.qss`
und `control_options.yaml`. Geschrieben vom Dialog hinter **Settings…** auf
dem Startbildschirm — wo vorher der Model Configurator saß, der nie portiert
war und abgeschaltet herumstand.

- **Tabs abschalten**: Controllers, Variable Pool, Process Manager und Log.
  Control Options und Information stehen nicht zur Wahl — ein Fenster ohne
  sie ist kein Kontrollfenster.
- **Studierendenansicht**: Δt bleibt sichtbar, aber nicht änderbar, und der
  Speedfactor wird gar nicht erst gezeigt. Ein Lauf, den alle mit derselben
  Schrittweite gestartet haben, ist vergleichbar; einer, bei dem jede Maschine
  ihren eigenen Faktor hatte, nicht. Der Speedfactor ändert am Ergebnis
  nichts und an der Wartezeit alles — deshalb weg statt gesperrt.
- **Ein abgeschalteter Tab wird trotzdem gebaut** und nur nicht eingehängt.
  Das Fenster frischt seine Seiten beim Namen auf; eine Seite, die es nicht
  gibt, müsste überall abgefragt werden statt einmal hier. Die Seiten hängen
  dafür an `self.pages` — ein Widget ohne Elternteil und ohne Python-Referenz
  wird eingesammelt und nimmt Log-Ansicht und Phasenraster mit.
- **Eine kaputte Datei zeigt alles.** `load_settings` fängt jeden Fehler und
  liefert die Vorgabe plus den Grund, den das Fenster in den Log schreibt:
  Einstellungen, die etwas verstecken, dürfen nicht in Richtung Verstecken
  scheitern.
- **Gelesen wird beim Öffnen eines Projekts**, nicht laufend. Ein offenes
  Fenster behält, womit es gebaut wurde, und der Dialog sagt das, statt so zu
  tun als ob.
- **Die Studierendenansicht steht im Fenstertitel.** Sie ist die einzige
  Einstellung, die ändert, was das Fenster kann; ein gesperrtes Δt ohne
  Erklärung daneben liest sich als Defekt.

### Ein Modus ist ein Name, eine Zahl ist eine Zahl

`gui/values.py` ist die eine Stelle, durch die Phasenraster, Parameterdialoge
und Log ihre Werte hindurchschreiben. Zwei Fragen, beide übers Lesen, nicht
übers Rechnen.

- **`Mode_pO2 = 3` sagt niemandem etwas**, und die Datenbank sagt seit jeher
  „pO2-Gasmix" — in `parameter_controlmodesTab`. Die Regelpanels zeigen die
  Namen von Anfang an; Parameterdialog, Phasendialog und Log druckten die
  rohe Zahl, und ein Log, aus dem niemand herauslesen kann, was eingestellt
  wurde, protokolliert nichts. `mode_table(setup.p_modes)` wird einmal im
  Fenster gebaut und weitergereicht.
- **`ModeBox` ist ein `QComboBox`, der `value`/`setValue`/`decimals`/
  `valueChanged` beantwortet** — dieselbe Abmachung wie `SegmentedControl`
  und `RotarySelector` bei den Panels: die Editoren tragen ihn, ohne zu
  wissen, welche der beiden Sorten sie halten. `decimals()` ist 0, damit
  `_differs` bei einem halben Schritt vergleicht; zwei Modi liegen eine ganze
  Zahl auseinander.
- **Eine Modusnummer, die die Datenbank nicht benennt, bleibt eine Zahl.** Sie
  bekommt einen eigenen Eintrag „7 (unknown)", statt still zum ersten Modus
  der Liste zu werden. Ein Rateversuch läse sich wie eine Tatsache.
- **Die grüne Markierung eines geänderten Feldes trägt einen Typselektor.**
  Ein Stylesheet ohne Selektor vererbt sich an die Kinder, und die
  Auswahlliste einer Combobox *ist* ein Kind: grün eingefärbt nimmt sie die
  Auswahlmarkierung mit — dieselbe Falle, der `default.qss` schon einen
  Absatz widmet.
- **Mindestens drei Nachkommastellen, und mehr, wo die Zahl mehr hat.**
  `format_number` misst das, statt es zu raten: die erste Stelle, ab der
  Runden den Wert nicht mehr ändert, ist die, die er hat. Zwei Stellen machten
  aus einem 0,005-h-Timer „0.00 h" — eine Bedingung, die nie auslöst und
  sofort auslöst.
- **Eine gemessene Zeit wird gerundet, eine eingestellte nicht.** Die
  Endzeit einer gelaufenen Phase kommt aus der Aufsummierung und trägt deren
  Arithmetik hinter sich her: 8.502222222223 h sind 8,502 h mit Rauschen.
  Der Timer daneben ist eine Zahl, die jemand eingetippt hat, und behält jede
  Stelle. Deshalb `cap=3` für `condition.time` und die Vorgabe für alles
  andere.

### Eine gelaufene Phase ist ein Protokoll, kein Plan

Abgeschlossene und laufende Phasen sind nicht mehr zu bearbeiten, nicht nur
nicht zu löschen. Der Automat hat ihre Bedingungen bereits gelesen und ihre
Parameter bereits angewandt; eine Änderung danach schriebe einen Plan, der
den gelaufenen Prozess nicht beschreibt. Die beiden Gründe, aus denen eine
Schaltfläche tot ist, sagen weiter Verschiedenes — „Pause the process to edit
a phase" gegen „A running or completed phase cannot be edited".

### Δt speichert, der Refresh zeigt

`sync_interval_to_dt()` hängt den Timer an `deltatsec` — ein Tick je Schritt,
damit ein Speedfactor von 1 Echtzeit bleibt. Das ist die Vorgabe und war
bisher die einzige Möglichkeit, und sie macht ein großes Δt unbenutzbar: Δt
bestimmt, wie viele Messwerte entstehen (bei 2 s sind es 1800 je Stunde und
Variable, gemessen 1 443 624 Werte für 14,3 h), gekoppelt bestimmt es aber
auch, wie oft der Bildschirm sich rührt.

- **`Settings.interval_ms(dt)` ist die eine Stelle, die die Frage
  beantwortet.** Fenster und Einstellungsdialog können sich damit nicht
  darüber uneinig werden, was die Einstellung bedeutet.
- **Entkoppeln ändert das Tempo, nicht nur die Glätte.** Δt geteilt durch
  Refresh *ist* der Faktor gegenüber der Wirklichkeit — bei Δt = 10 s und 2 s
  Refresh läuft es fünffach. Das steht so im Dialog und im Handbuch, weil
  jemand sonst eine ruhigere Anzeige erwartet und einen schnelleren Prozess
  bekommt.
- **`_set_dt` darf den Takt nicht mehr blind nachziehen.** Entkoppelt hat der
  Anwender ihn gesetzt, und eine Änderung an Δt überschriebe ihn.
- **Ein Refresh von 0 wird abgewiesen, nicht benutzt.** Ein QTimer mit
  Intervall 0 feuert, so schnell die Ereignisschleife kann; das Fenster wäre
  nicht mehr zu bedienen. `load_settings` prüft 0,05 bis 600 s und fällt
  sonst auf die Vorgabe zurück, mit Begründung für den Log.

### Δt rechnet, das Speicherintervall schreibt

Δt war bis hierhin für zwei Dinge zuständig, die nichts miteinander zu tun
haben: wie fein gerechnet wird, und wie viele Zeilen in der Datei landen. Wer
die Datei kleiner haben wollte, musste Δt vergrößern — **und bezahlte mit der
Regelung**: pO2-RMS 9,1 bei Δt = 2 s, 25,3 bei 10 s, 37,0 bei 20 s, 120,9 bei
60 s (pH und Temperatur bleiben flach). Die pO2-Verstärkungen sind bei 2 s
bestimmt worden; ein anderes Δt ist ein anderer Prozess.

`Settings.storage_interval` trennt die beiden Fragen. Jeder n-te *berechnete*
Schritt wird geschrieben, gerechnet wird weiter jeder.

- **Der letzte Schritt wird immer geschrieben**, unabhängig vom Intervall.
  Ein fortgesetzter Lauf beginnt beim jüngsten gespeicherten Punkt; wäre der
  nicht der letzte gerechnete, verschwände jedes Mal ein Stück Prozess.
- **Ausgedünnt wird nach Index, nicht nach Zeit.** `i % step == 0` über die
  ganze Reihe hält das Raster über mehrere Speichervorgänge hinweg stabil —
  sonst bekäme jeder Speichervorgang seinen eigenen Versatz und die Reihe
  wäre nach dem dritten Mal nicht mehr äquidistant.
- **`_save_series` fragt `MAX(process_time)`, nicht `COUNT(*)`.** Die alte
  Fassung nahm die Zeilenzahl in `timeTab` als Index in die Speicherarrays —
  das trägt nur, solange jeder Schritt gespeichert wird. Mit Ausdünnung wären
  bei jedem weiteren Speichern genau die falschen Schritte geschrieben worden.
  Das ist **keine** Existenzprüfung; die Konvention „`COUNT(*)` statt `MAX()`"
  weiter oben gilt für die Frage „gibt es das?", hier geht es um „wie weit
  sind wir gekommen?".
- **Gefragt wird zweimal**: in den Einstellungen als Vorgabe, und im
  Schließen-Dialog für den Lauf in der Hand. Der Moment des Speicherns ist
  der einzige, in dem jemand weiß, wie lang der Lauf geworden ist — und der
  letzte, in dem die Entscheidung noch möglich ist.
- **Ein ausgedünnter Speichervorgang sagt es.** „Saved 5040 time points (one
  step in 5)" — fehlende Zeilen sehen sonst aus wie verlorene Zeilen, und
  diese Datenbank hat schon einmal welche verloren. Formuliert wird mit „one
  step in n", nicht mit „every nth step": die Zahl kommt aus einem Spinfeld,
  englische Ordinalzahlen kommen dort nicht heraus.
- **Der Einstellungsdialog kennt kein Δt.** Er wird vom Startbildschirm
  geöffnet, wo kein Projekt offen ist; `EXAMPLE_DT` steht deshalb als
  *Beispiel* in der Erklärung, statt als Tatsache. Der Schließen-Dialog kennt
  es und rechnet in Sekunden.

### Was im Log steht, und was man davon sieht

Drei Sorten Einträge und zwei Schalter darüber. **Parameter Value Change** ist
der laute Normalfall, **Operation** der neue: Plot geöffnet, Datentabelle
geöffnet, Prozess pausiert, Δt geändert — was mit der *Anwendung* gemacht
wurde, nicht mit dem Prozess. Alles andere (Phasenereignisse, Phaseninfos,
Prozess, Projekt, Fehler) steht immer da.

- **Geschrieben wird immer, gezeigt nicht.** Der Filter arbeitet auf den
  Datensätzen, nicht auf dem Text: ein nachträglich gesetzter Haken zeigt die
  ganze Sitzung, nicht nur das, was danach kommt. Und der Export bekommt
  ohnehin alles — ein Log, der nur zeigt, was gerade angehakt war, wäre als
  Protokoll wertlos.
- **Operationen starten ausgeblendet.** Sie sind die häufigsten Einträge und
  die uninteressantesten für die Frage, die jemand an einen Log stellt.

### Wer in `p` schreibt, muss die Panels anfassen

`refresh()` füllt nur Messwerte nach — und zwar mit Absicht: es läuft nach
jedem Block, und ein Sollwertfeld neu zu setzen, während jemand hineintippt,
nähme ihm die halb getippte Zahl weg. Sollwerte, Modi und Schalter liest
`ControlPanel.load()`, und das lief bisher nur beim Öffnen des Fensters und
nach einem Dialog.

**Eine Phase schreibt aber auch in `p`.** Eine „Update Parameter Set"-Phase
setzte `Mode_feed` auf Closed loop, und der Tab zeigte weiter „Manual" — die
eine Stelle, an der jemand nachsieht, was der Prozess gerade tut, zeigte das
Gegenteil. `load_panels()` hängt jetzt an `_phase_changed`; die Parameter sind
zu diesem Zeitpunkt schon angewandt, weil `check_start` sie schreibt und der
Runner erst danach sendet.

### Ein fortgesetzter Lauf verliert seine Regler — gemessen

`a` wird nicht persistiert, und `initialize()` läuft beim Fortsetzen erneut
(„rebuild a, keep v"). `init_controller_states` setzt dabei **jeden I- und
D-Anteil auf null**. Das ist die MATLAB-Struktur und war nie gemessen.

Nachgemessen an Projekt 716, eine Stunde rechnen, speichern, neu laden, eine
Stunde weiter — gegen denselben Lauf ohne Unterbrechung:

| | durchgehend | nach Neuladen |
|---|---|---|
| I-Anteil Rührerregler | 0,2194 | **0,0000** |
| Rührerdrehzahl `NSt` | 469 rpm | **1276 rpm** |
| pO2-RMS der zweiten Stunde | 7,06 | **9,85** |
| `cXL` am Ende | 5,802 | 5,652 |

Der Regler fängt also bei null an und fährt den Rührer auf fast das Dreifache,
während der Prozess an derselben Stelle steht. Es ist **nicht** dasselbe wie
die fehlenden Messwerte aus `variable_handlingTab`: dort fehlen Zeitreihen,
hier fehlt der Zustand des Reglers, und der steht in keiner Tabelle.

**Zu entscheiden, nicht zu reparieren.** Die Reglerzustände zu speichern wäre
eine bewusste Abweichung vom Original — dieselbe Sorte wie die vier
Begasungskorrekturen, und sie gehört genauso gemessen und begründet, bevor sie
bleibt.

### Ein wieder geöffnetes Projekt ist schon beimpft

`a` wird nicht gespeichert, und `initialize` setzt `inoc_occ` nur für einen
frischen Zustand — `init_variables` läuft nicht mehr, sobald Schritte
gespeichert sind. Ein fortgesetzter Lauf kam deshalb mit `inoc_occ` = 0
zurück, während `f_Inoc` noch 1 war: genau das Paar, das das Modell als „jetzt
beimpfen" liest. Der nächste Schritt ersetzte die gewachsene `cXL` durch
`cXL0` und setzte `ToI`, von dem der Antischaumtimer zählt, auf den Moment des
Öffnens. Beides still — sichtbar war nur die Lampe, die erst mit dem ersten
Schritt anging, und genau die hat es gemeldet.

**Die Zeitreihe sagt, was war.** Biomasse im Kessel heißt beimpft, und der
Schritt, der den ersten positiven Wert geschrieben hat, hat `t` des
Vorschritts als Beimpfungszeit vermerkt. `_adopt_inoculation` liest beides
daraus zurück; bei `f_InocStart` bleibt `ToI` auf 0, wie bei einem frischen
Lauf.

**Das Original hatte die Regel, die Portierung hat sie verloren.**
`Escherichia_coli_Initialization.m` schließt mit genau dieser Prüfung:

```matlab
if app.v.cXL(end) > 0
    app.a.inoc_occ = 1; % Flag that activates once inoculation has happened
else
    app.a.inoc_occ = 0;
end
```

Sie steht dort *nach* dem `f_InocStart`-Zweig und außerhalb davon, läuft also
auch für einen geladenen Lauf. Die Portierung hat den Zweig übersetzt und die
Prüfung danach nicht — `initialize()` ruft `init_variables` nur bei
`idx == 0`, und damit fiel beides zusammen weg. Ein Übersetzungsfehler, kein
geerbter: **beim Rückportieren nach MATLAB gehört dieser Punkt nicht auf die
Liste.** Die Lehre daraus ist allgemeiner — was in der Quelle *neben* einem
`if` steht, wird beim Übersetzen leicht Teil davon.

### Der Reglertab

Die Anwendung rechnet jeden Anteil jedes Reglers in jedem Schritt — und zeigte
davon nichts. Wer pO2 schwingen sah, sah nicht den I-Anteil auflaufen, und das
ist das Einzige, was es erklärt. Der Tab „Controllers" zeigt je Regelkreis
Sollwert, Messwert, Abweichung, die drei Anteile als vorzeichenbehaftete Balken
auf gemeinsamer Skala, die zugehörige Verstärkung und die Stellgrößen.

- **Der Organismus sagt, welche Kreise er fährt**, nicht die Oberfläche:
  `OrganismModel.control_loops`, eine Liste von `ControlLoop`. Darin stehen nur
  Namen — Schlüssel in `p`, `v` und `a` —, aufgelöst gegen den laufenden
  Zustand. Ein Modell, das seine Kreise nicht beschreibt, bekommt einen leeren
  Tab statt eines falschen. Beide mitgelieferten Organismen teilen sich
  `shared.CONTROL_LOOPS`; sie greifen dieselben Signale ab.
- **Zwei Anteile lagen nur in lokalen Variablen** — der P-Anteil des
  pH-Masters und P und D der Füllstandsregelung. Sie stehen jetzt zusätzlich in
  `a`. Das ändert keine Zahl: `a` wird vom Modell nicht zurückgelesen und nicht
  gespeichert. Nachgemessen ist es trotzdem — der E.-coli-Referenzlauf ist nach
  der Änderung unverändert.
- **Eine `numpy.float64` ist ein nulldimensionales Array** und antwortet auf
  `size` mit 1. Wer Skalare und Zeitreihen daran unterscheidet, hält jeden
  skalaren Anteil für eine Reihe mit einem Element und liest ab dem zweiten
  Schritt nichts mehr. `ndim` ist das richtige Merkmal.
- **Nur der sichtbare Tab wird neu gezeichnet**, wie bei Variable Pool auch.

### Was eine Phase an Parametern anbietet

`PHASE_PARAMETERS` in `control/phases.py` sagt, womit eine Phase arbeitet —
`{n}` steht für ihr Reservoir. Die Tabelle steht neben den Handlern, die sie
lesen, damit beides nicht auseinanderläuft.

- **Update Parameter Set** bekommt alles Zyklische; dafür ist der Typ da.
- **Exponentialfeed** bekommt die fünf, aus denen er `FRj` rechnet, für sein
  Reservoir und kein anderes. **Pulsfeed** die zwei, die er multipliziert.
  `reading_rate` spielt hier keine Rolle: diese Werte liest der Phasenhandler
  beim Start der Phase, nicht der erste Schritt des Laufs.
- **Manual und Stop** bekommen nichts, und ihre Schaltfläche ist abgeschaltet.
  Eine Liste von Feldern, die nichts bewirken, ist schlechter als keine.
- **Nicht dabei: `t{n}j`, `cXL{n}j`, `FR{n}j`.** Das sind Ergebnisse — die
  Phase schreibt sie beim Start, und sie zum Bearbeiten anzubieten hieße
  anzubieten, ihre eigene Aufzeichnung zu überschreiben.

**Die Abschnitte stehen in Lesereihenfolge**, nicht in Datenbankreihenfolge:
Parameters, Organism, Bioreactor, General (`SECTION_ORDER`). `categoryTab`
sortiert nach ID und schob damit General — Kalibrierkonstanten und Schalter —
über die Sollwerte, wegen derer der Dialog geöffnet wurde. Ein Abschnitt, den
die Liste nicht kennt, folgt hinten, statt sich dazwischenzudrängen.

**Ein Feld, das seinen Wert nicht darstellen kann, meldet eine Änderung, die
niemand gemacht hat.** `KD_gasmix` ist 1e-05, die `QDoubleSpinBox` hatte vier
Nachkommastellen, hielt also 0.0000 und gab das zurück: in jedem Phasendialog
stand „KD_gasmix: 1e-05 → 0", ungefragt. `_decimals_for()` gibt jedem Feld so
viele Stellen, wie sein Wert braucht, und `_differs()` misst in dem, was das
Feld zeigen kann (eine halbe letzte Stelle) statt in 1e-15.

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
  daneben sagt dasselbe ein zweites Mal. Das gilt für den Schalter — der
  Modus-Wähler hat seine Lampe, siehe unten.
- **Zwei Modus-Wähler, dieselben vier Aufrufe.** `SegmentedControl` (Tasten)
  und `RotarySelector` (Drehschalter) beantworten beide
  `addItem`/`findData`/`setCurrentIndex`/`currentData` und heißen ihr Signal
  `currentIndexChanged` — damit tragen `select_data()` und `ControlPanel`
  jede Variante, ohne zu wissen, welche sie halten. **Welcher wo steht, sagt
  die Layoutdatei, je Panel** (`mode_selector:` als Name für alle oder als
  Zuordnung mit `default`); es ist Geschmack, keine Verdrahtung. Fünf Modi
  sind ein anderes Problem als zwei: pO2 trägt den Drehschalter, der Breite
  gegen Höhe tauscht (132 px Quadrat, keine Breite), der Rest die Tasten.
- **Die beiden Signallampen haben Luft nach oben.** Sie sitzen als
  Eckwidget in der Menüleiste, und ohne Rand oben und unten liegt die Lampe
  auf y = 0 — sie liest sich dann als Teil der Titelleiste statt als Teil der
  Anwendung. `LAMP_MARGIN` macht die Leiste um 2 × 7 px höher; eine Menüleiste
  richtet sich nach ihrem Eckwidget.
- **Die Lampe hat nur der Tastenwähler.** Eine Taste sagt, *welcher* Modus
  gewählt ist — blau, nicht grün, denn ob dieser Modus etwas regelt, ist eine
  zweite Frage, und die beantwortet die Lampe daneben. Der Drehschalter
  beantwortet beide selbst: sein Punkt ist grün für einen Regelmodus und rot
  für Handbetrieb, also steht neben ihm keine Lampe. Welcher Wert Handbetrieb
  ist, weiß das Panel: `MANUAL_MODE = 0`, so nummeriert
  `parameter_controlmodesTab` jeden Regler dieser Anwendung.
- **Die Tasten stehen auf einer Reihe, weil die Spalte dafür breit genug
  gemacht wird.** Der Rand je Taste ist beweglich (`PADDING` 12 bis
  `MIN_PADDING` 5), und `one_row_width()` — die Breite bei engstem Rand —
  steht als `setMinimumWidth` auf dem Wähler selbst. Damit kommt sie über
  `minimumSizeHint` mit den echten Rändern zurück, statt über einen
  geschätzten Zuschlag. Fünf Modi brauchen 215 px Text; in einer Viertelbreite
  bleiben 5,6 px Rand, und genau dafür ist die Untergrenze da. Darunter wird
  weiter umgebrochen statt abgeschnitten — die Höhe setzt `resizeEvent`
  selbst, weil `heightForWidth` in einem `QHBoxLayout` nicht beachtet wird.
- **Die pO2-Modi heißen ohne Präfix.** „pO2-agitation" in einem Panel namens
  pO2-Control wiederholt nur den Titel und kostete 170 px auf einer Zeile, die
  alle fünf gleichzeitig zeigen muss. Die gespeicherten Modusnummern sind
  unverändert.
- **Die Anordnung ist eine Textdatei, kein Python.** Sie ging an einem
  Nachmittag durch fünf Runden, und jede Runde war eine Codeänderung — das
  gehört nicht in den Code: es ist Geschmack, es beeinflusst nichts, was die
  Anwendung rechnet, und wer den Geschmack hat, soll dafür kein Python
  anfassen müssen. Mitgeliefert ist
  `resources/layouts/control_options.yaml`, eine `control_options.yaml` neben
  der Datenbank ersetzt sie; **Settings → Panel layout…** legt sie an und
  öffnet sie. Dieselbe Abmachung wie beim Stylesheet.
- **Die Datei *ist* die Anordnung**, und sie sagt auch, wie die Modi
  gezeichnet werden. Ein Raster aus Namen, eine Zeile je Tabzeile; ein
  wiederholter Name deckt die Nachbarzellen ab. Namen werden
  nachsichtig verglichen (`normalise`): `pH`, `pH-Control` und `PH control`
  sind dasselbe Panel. Geprüft wird, dass jedes Panel vorkommt, dass seine
  Zellen ein Rechteck bilden und dass alle Zeilen gleich lang sind.
- **Eine kaputte Datei wirft nie das Tab weg.** `load_layout` fängt alles und
  liefert die Ersatzanordnung (`fallback`: jedes Panel eine Spalte, ohne jede
  Datei) plus den Grund, den das Fenster in den Log schreibt. Ein halbes Tab
  wegen eines Tippfehlers wäre kein Tausch, den jemand eingeht.
- **Gleiche Zellen brauchen eine gemeinsame Mindestgröße, nicht nur gleiche
  Streckung.** `setRowStretch`/`setColumnStretch` verteilen nur, was übrig
  bleibt; zwei Panels brauchen von sich aus unterschiedlich viel, und das
  größere behielte seinen Vorsprung bei jeder Fenstergröße. `_size_panel_grid`
  rechnet beides aus den Platzierungen aus — ein Panel über zwei Zellen
  braucht aus jeder die Hälfte.
- **Wie breit die Panels sein wollen, entscheidet nicht dieses Projekt.** Eine
  `QDoubleSpinBox` bemisst sich an der breitesten Zahl ihres Wertebereichs, und
  der ist ±1e12 — gezeichnet in der Schrift des jeweiligen Systems. Gemessen
  mit derselben Layoutdatei: **1174 px unter macOS, 1538 auf einem
  Windows-Runner**, bei 1440 als schmalstem Zielbildschirm. Eine Mindestbreite,
  die niemand einhalten kann, ist schlimmer als ein Rollbalken, den niemand
  braucht: **Control Options liegt deshalb in einer `QScrollArea`**, wie der
  Process Manager. Das Fenster verspricht nicht, breit genug für seinen Inhalt
  zu sein, sondern auf den Bildschirm zu passen.
  Die Öffnungsgröße wird dabei am Bildschirm begrenzt
  (`_open_at_a_sensible_size`) — 1420 × 680 war eine einmal hingeschriebene
  Zahl und lag unter dem, was der Tab braucht (936 × 672), das Fenster ging
  also von sich aus gerollt auf.
- **Pixelgenaue Layoutzusagen halten nur auf einem System.** Die Feldbreiten
  liegen hier innerhalb von 2 px beieinander, unter Windows bei 140/144/148 —
  ein Raster verteilt seine Restpixel, und wie viele übrig bleiben, hängt an
  der Schrift. Der Test misst deshalb ein Verhältnis (kein Feld unter 90 % des
  breitesten) statt einer Pixeldifferenz. Der Fehler, den er bewacht, war 72
  gegen 133.
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
- **Eine `ValueRow` hat immer zwei Spalten** — Sollwert links, Messwert
  rechts. Ohne Messwert **spannt der Sollwert über beide**: sonst bekommt ein
  alleinstehendes Feld die halbe Breite eines Feldes mit Messwert daneben,
  gemessen 72 gegen 133 px in derselben Spalte.
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

  **Gemeldet wurde es lange nur an ein Feld, das niemand las.**
  `load_project_state` rechnet `a.restarted_variables` aus, und der einzige
  Leser war ein Test. `ControlWindow._report_resumed_state()` schreibt es
  jetzt beim Öffnen in den Log — ein Lauf, der still einen ODE-Zustand
  zurücksetzt, ist ein Lauf, dessen Zahlen hinterher niemand mehr erklären
  kann, und die einzige Stelle, die es weiß, muss es sagen.
- **pO2 über 100 % ist kein Fehler.** Die Sonde wird gegen `pGcal` und
  `xOGcal` kalibriert (`cOL100 = pGcal·xOGcal/HO2`) und liest im Gleichgewicht
  `pG·xOGin/(pGcal·xOGcal)·100`. Projekt 519 begast mit 15 l/min Luft **plus
  1 l/min reinem Sauerstoff** (`f_O2` = 1, `FnO2w` = 1) — `xOGin` = 0,2588
  statt 0,2094, Gleichgewicht 124,7 %, gemessen 123,4 %. Die Bilanz rechnet
  richtig, das Projekt begast angereichert. Die früher notierten 1000 %
  stammten aus den verfälschten Pichia-Defaults und sind mit deren Bereinigung
  weg. In allen vier pO2-Modi bleibt pO2 jetzt unter der Grenze, die sein
  eigenes Gasgemisch zulässt.

### Die Verknüpfung auf den Quellbaum

`tools/make_launcher.py` baut ein `.app`-Bündel in `~/Applications`, das den
Interpreter *dieser Arbeitskopie* startet — nicht der Verteilungsbau, sondern
das, was man zum Entwickeln und zum Unterrichten aus einem Checkout heraus
will. Drei Dinge daran sind teuer erkauft:

- **Die ausführbare Datei eines Bündels muss ein Mach-O sein.** Ein
  Shell-Skript startet von Hand tadellos und im Finder gar nicht:
  LaunchServices liest die Architekturen aus dem Hauptprogramm, ein Skript hat
  keine, und eine Anwendung ohne jede Architekturangabe gilt als Intel-App.
  Unter macOS 26, wo Rosetta ausläuft, öffnet der Doppelklick daraufhin Apples
  „Rosetta installieren"-Seite; der Interpreter wird nie erreicht, es gibt
  keine Logzeile und nichts, woran man es sieht. Nachweisen lässt es sich in
  einer Zeile — `mdls -name kMDItemExecutableArchitectures "…/Some.app"` gibt
  bei einer laufenden App `x86_64, arm64` und beim Skriptbündel **nichts**;
  `codesign -dvv` nennt das Format dann „app bundle with generic" statt „app
  bundle with Mach-O universal". Der Starter ist deshalb ein kurzes C-Programm
  für beide Architekturen. Das Skript bleibt als Notnagel für eine Maschine
  ohne Compiler.
- **Die Architektur wird vererbt.** Der Interpreter eines venv ist universal,
  und ein über LaunchServices gestartetes Bündel erbt die Architekturvorliebe
  dessen, der es angefordert hat. numpys Erweiterungsmodule gibt es nur für
  eine; passt sie nicht, scheitert der Import und das Fenster kommt nie.
  `LSRequiresNativeExecution` im Plist und `sysctl.proc_translated` im Starter
  sind Gürtel und Hosenträger. **Nicht** `uname -m`: unter Rosetta antwortet
  das x86_64 und wählt damit genau die falsche Hälfte.
- **Das Bündel wird beschrieben, nicht ersetzt.** Ein neu angelegtes Bündel
  bekommt eine neue Inode, und alles, was auf die alte zeigt — ein
  Dock-Eintrag zuerst —, zeigt danach ins Leere. Dazu eine Ad-hoc-Signatur
  (ohne jede Signatur weist Gatekeeper das Bündel ab) und `lsregister -f`,
  damit Finder und Spotlight es sofort kennen.

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
- **Der Integrator hat Anti-Windup, aber abgeschaltet.** Er integriert
  weiter, während der Ausgang am Anschlag klemmt — das ist die
  MATLAB-Struktur und die Vorgabe; die Verstärkungen sind so gewählt, dass der
  Aufzug beim Sprung von 100 % auf den Sollwert klein genug bleibt, dass der
  Regler sich wieder erholt. Einschalten lässt es sich je Regelkreis, siehe
  unten.

### Ein Schalter je Regelkreis, im Dialog der Verstärkungen

`shared.integrate()` kann den Integrator anhalten, `anti_windup(p, a, flag)`
beantwortet, ob er darf. Bedienbar war das nicht: die vier Flags standen nur
als Zahlenfeld im großen Parameterdialog, und in der Datenbank eines Anwenders
standen sie gar nicht.

- **`PanelSpec.anti_windup` nennt den Flag je Panel**, und
  `ControllerParametersDialog` baut daraus eine Gruppe „Anti-windup" unter den
  Verstärkungen. Dorthin gehört er: er ändert, wie der Integrator sich
  verhält, nicht was der Bediener vom Prozess verlangt.
- **`SwitchBox` ist dieselbe Abmachung wie `ModeBox`** — `value`, `setValue`,
  `decimals`, `valueChanged` —, also sammelt `_EditorBase` ihn ein, ohne zu
  wissen, was er hält. Ein Flag als Zahlenfeld liest sich wie eine Messung;
  0 und 1 sind keine Menge, sondern eine Stellung.
- **Welches Bedienelement ein Parameter bekommt, sagt die Datenbank.**
  `parameterTab.type`: 22 `switch`, 5 `dropdown`, 287 `editfield`, 9
  `uneditable` — und die Editoren haben jahrelang alles als Zahlenfeld
  gezeichnet. `_field(value, name, modes, kind)` liest die Spalte jetzt, und
  beide Dialoge (Parameterdialog und Phasendialog „Update Parameter Set")
  reichen sie durch. **Geraten wird nichts**: ein Flag, das gerade auf 0 steht,
  ist von einem Sollwert, der auf 0 steht, nicht zu unterscheiden — die
  Spalte weiß es, der Wert nicht.
- **Die Änderungsliste des Phasendialogs liest einen Schalter als Stellung**,
  nicht als Zahl: „f_acid: Off → On". Ein Protokoll, in dem „0 → 1" steht,
  zwingt den Leser, die Bedeutung selbst nachzuschlagen.
- **Mehr als vier Gruppen stehen zu zweit nebeneinander** (`COLUMN_LIMIT`).
  Das betrifft nur pO2: seine fünf Gruppen sind die vier Stellgrößen plus der
  Sensor, und untereinander ergaben sie einen Dialog von 837 px Höhe — mit
  Raster 557 bei gleicher Breite. Eine ungerade letzte Gruppe nimmt die ganze
  Zeile, ebenso das Anti-Windup-Feld darunter: eine halbe Zeile mit nichts
  daneben liest sich als Lücke. pH und Temperatur haben drei Gruppen und
  bleiben einspaltig — die Regel greift nur, wo sie gebraucht wird.
- **Der Einstellungsdialog ist 680 px breit, und seine Höhe kommt vom
  großzügigen Hinweis.** Er besteht überwiegend aus Erklärungen; bei 440 px
  brach jede Notiz auf vier bis fünf Zeilen um. Ein umbrechendes `QLabel`
  meldet seine Höhe, ohne seine künftige Breite zu kennen: `sizeHint()` sagt
  795 px, wo das Layout mit 615 auskäme. Über `heightForWidth` zu gehen klingt
  richtig und schneidet die letzte Notiz um zwei Zeilen ab — die Gruppenkästen
  melden sie zu knapp. Deshalb der großzügige Wert plus ein `addStretch()`,
  das den Überschuss nach unten schiebt: ein Dialog mit Luft ist besser als
  einer, der das Ende eines Satzes verbirgt.
- **Drei Kreise haben einen Schalter, zwei nicht, und die zwei aus
  verschiedenen Gründen.** pH hat keinen Integrator (P-Regler mit Totband).
  Der Temperatur-Master hat einen, **erreicht seine Anschläge aber nie**:
  gemessen über zwei Stunden Batch gegen einen 12 K entfernten Sollwert liegt
  sein Ausgang zwischen −2,3 und +3,2, die Anschläge der Split Range bei
  −100/`KP_temp2c` = −10 und +100/`KP_temp2h` = +10000. Auch mit
  tausendfachem `KI_temp1` ändert sich daran nichts — die innere Schleife
  nimmt die Auslenkung auf. `f_awtemp` hat deshalb keinen Leser und das Panel
  keinen Schalter; ein Bedienelement, das nachweislich nichts tut, ist
  schlechter als keines. `test_the_temperature_master_stays_away_from_its_stops`
  hält die Messung fest: wer die Kaskade neu abstimmt, bis der Master doch
  anschlägt, bekommt einen roten Test statt einer stillen Lücke.
- **Der Test liest die Flags aus der Modellquelle**, statt sie ein zweites Mal
  aufzuzählen: `anti_windup(p, a, "…")` per Regex gegen `PanelSpec`. Ein
  umbenannter Flag ergäbe sonst einen Schalter, der einen Parameter schreibt,
  den niemand liest — und das fällt nie auf, der Lauf rechnet einfach weiter
  wie vorher.
- **Gemessen, was der Schalter bewirkt** (Projekt 716, zwei Stunden, Δt = 2 s):
  mit `f_awpO2` = 1 steigt pO2 von 29,8 auf 32,1 %, `cXL` von 5,805 auf 5,898
  und der I-Anteil des Rührerreglers von 0,118 auf 0,145. Das ist keine
  Verbesserung, die versprochen wird — es ist ein anderer Lauf.
- **`_ensure_switch_parameters` beim Start**, wie `ensure_columns` und
  `ensure_indexes`. Die Datenbank eines Anwenders ist eine Kopie der Vorlage
  von seinem ersten Start; die vier Flags fehlten darin, und ohne sie hat der
  Schalter nichts zu schreiben. Eingetragen wird überall 0 — genau das, was
  ein fehlender Parameter schon bedeutete —, gemessen 28 Zeilen in 0,00 s auf
  der produktiven Datei, und beim zweiten Start keine.
- **Ein Projekt ohne den Parameter sagt es.** Die Gruppe erscheint trotzdem,
  mit einem Satz statt eines Schalters: ein fehlendes Bedienelement ist von
  einem nicht gefundenen nicht zu unterscheiden.
- **Ein Parameter ohne Beschreibung ist ein Name.** Die vier Flags kamen ohne
  eine in die Datenbank — `add_flags` schrieb nur Name, TeX und Wert —, und
  damit stand im Tooltip nur „f_awpO2". Die Beschreibung steht jetzt an den
  Parametern und wird beim Start nachgetragen, wo sie fehlt (40 Zeilen im
  Template, in drei Tabellen: jedes Projekt trägt seine eigene Kopie).

**Pichia bleibt außen vor — und jetzt ist auch klar, warum.**
`tools/tune_pichia.py` ist der Messstand dazu, aufgebaut wie `tune_po2.py`,
und er kommt zu einem anderen Ergebnis: **es gibt dort nichts zu tunen, weil
kein Regelkreis einen Arbeitspunkt hat.** Drei Befunde, alle gemessen, alle
als Test festgehalten.

1. **Das Anti-Windup des Rührerreglers steht in der falschen Einheit.**
   `clamp(cI_agi, 0, NStmax)` begrenzt einen normierten Term mit einer Grenze
   in min⁻¹: die Obergrenze 1500 kann nie greifen, die Untergrenze 0 immer —
   der I-Anteil kann nicht mehr negativ werden, und ein einmal hochgefahrener
   Rührer kommt nicht mehr herunter. Gemessen an Projekt 519, `Mode_pO2` = 1:
   pO2 endet bei **108,7 %** mit abgeschaltetem Schalter und bei **78,3 %**
   mit eingeschaltetem (RMS gegen 20 %: 96 → 72). Der Schalter **ersetzt** die
   Klammer, er tritt nicht neben sie: aus ist bitgleich die Quelle, an ist
   konditionale Integration an den echten Grenzen [0,3, 1,0]. Nachgemessen über
   alle vier pO2-Modi: mit allen Schaltern aus ist der Lauf bitgleich zu vorher.
2. **Die Verstärkungen des Methanol-Feeds haben das falsche Vorzeichen.**
   `KP_feedR2`/`KI_feedR2`/`KD_feedR2` = −2/−15/−0,009 sind **exakt** die Werte
   von `KP_feedpO2`/`KI_feedpO2`/`KD_feedpO2` — dort ist ein negatives
   Vorzeichen richtig (viel pO2 heißt: es darf mehr gefüttert werden), auf
   einem Substratkreis mit `cS2Lw − cS2L` kehrt es den Regler um: zu wenig
   Methanol ergibt einen positiven Fehler, eine negative Stellgröße und eine
   Pumpe, die zubleibt. Gemessen: Pumpe 100 % der Zeit am Anschlag, `cS2L`
   bleibt bei 0,001 g/l gegen einen Sollwert von 1,5.
3. **Und selbst mit richtigem Vorzeichen regelt der Kreis nichts**, weil er
   auf ein eingefrorenes Signal regelt. `meas_transfer_function` rechnet
   `T = dt / 3600` auf ein dt, das bereits in Stunden vorliegt; ein Schritt
   schließt damit 2,6e-09 des Abstands. **Das ist MATLABs eigene Arithmetik**
   und verifiziert — der E.-coli-Referenzlauf stimmt bei `pHLm`, `thetaLm`,
   `pO2m` und `cS1Lm` auf 1e-12 überein. E. coli fällt es nicht auf, weil sein
   Feed-Regler die *echte* Konzentration liest; Pichias liest die gemessene.
   Mit einmal statt zweimal umgerechneter Schrittweite folgt `cS2Lm` dem
   wahren Wert (1,086 gegen 1,092) und der Kreis schließt sich.

**Punkt 3 ist entschieden — `sensor_lag`, nur für Pichia**, siehe die fünfte
Abweichung oben. Damit ist Punkt 2 prüfbar geworden, und die Verstärkungen
sind gemessen und eingetragen:

| | `KP_feedR2` | `KI_feedR2` | `KD_feedR2` |
|---|---|---|---|
| vorher (= pO2-Feed-Regler) | −2 | −15 | −0,009 |
| **jetzt** | **1** | **5** | **0,005** |

Über acht Stunden Late-Stage-Modell: `cS2L` endet bei 1,38 g/l gegen einen
Sollwert von 1,5, Tail-RMS 0,237, die Pumpe **nie** am Anschlag, Stellweg
0,076 l/h summiert, Biomasse 21,0 g/l. Geprüft gegen Sollwerte von 1,0 bis
3,0 g/l, Schrittweiten 2/5/10 s und die halbe Reservoirkonzentration — Tail-RMS
bleibt bei 0,20 bis 0,55, ohne Anschlag. Die Alternativen: 3/30/0,01 ist beim
RMS besser (0,144), sitzt aber zu 28 % am Anschlag und fährt den dreifachen
Stellweg; 15/500/0,02 (E. coli, Reservoir 1) treibt die Konzentration auf
82 g/l und die Kultur über die Methanoltoxizität auf 10,7 g/l zurück.

Eingetragen über `repair.correct_pichia_feed_gains()` in `default_modelTab`
und `model_parameterTab`, angewendet auf Template und CSV-Satz. **Bestehende
Projekte behalten ihre Werte** — dieselbe Regel wie bei jeder anderen
Default-Änderung, und der Grund, warum ein gespeicherter Lauf reproduzierbar
bleibt. Ersetzt wird nur, was noch auf der Ausgangszahl steht; wer selbst
abgestimmt hat, bleibt unbehelligt.

**Was der Feed für den Rest bewirkt** (acht Stunden, Late-Stage-Modell): die
Kultur wächst von 20 auf 21,0 g/l statt auf 17,4 zurückzufallen, und die
Sauerstoffaufnahme verdreifacht sich fast (OUR 0,585 gegen 0,204). Mit
eingeschaltetem Anti-Windup fällt der pO2-RMS von 61,6 auf **29,6**.

**Der pO2-Kreis bleibt versorgungsbegrenzt, auch mit laufendem Feed.** Der
Rührer sitzt in **100 %** der Schritte an einem Anschlag, und acht
Verstärkungssätze über drei Größenordnungen (KP 0,5 bis 20, KI 30 bis 2000)
liefern **denselben** RMS von 29,6 und dasselbe Endergebnis von 46,2 %.
Gemessen, nicht geschätzt: **an diesem Kreis ist nichts zu tunen**, weil er
keinen Arbeitspunkt hat. Bei 8 l/min Luft plus 1 l/min Sauerstoff in acht
Litern liegt das Gleichgewicht selbst bei der Mindestdrehzahl von 450 min⁻¹
weit über dem Sollwert von 20 %.

Was es ändern würde, ist die Prozessführung, nicht der Regler: 4 l/min Luft
ohne reinen Sauerstoff bringen pO2 auf 24,8 % (RMS 10,6), 1 l/min auf 23,7 %
(RMS 6,1). Ein Sollwert von 60 % ist mit der mitgelieferten Begasung
erreichbar und lässt den Rührer bei 853 min⁻¹ stehen — dort regelt der Kreis
wirklich. Deshalb bleiben `KP_agi`/`KI_agi`/`KD_agi` unverändert: eine
Verstärkung, die an jedem gemessenen Punkt dasselbe Ergebnis liefert, ist
nicht abgestimmt, sondern folgenlos.

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

### Eine Versionsnummer, drei Stellen, die sie zeigen

`biofermentation.__version__` ist die Quelle. `pyproject.toml` hat keine
eigene Nummer mehr — hatch liest sie über `[tool.hatch.version]` von dort —,
der Startbildschirm und der Info-Tab zeigen sie, und
`tools/make_launcher.py` stempelt sie in `CFBundleShortVersionString`.

Vorher hielt jede Stelle eine Kopie, und so gehen sie auseinander: das Fenster
sagte 3.0, das Paket 0.1.0, und das gebaute `.app`-Bündel nahm seinen Stempel
vom Paket. `test_packaging.py` hält die drei zusammen.

### Zwei Stände, ein Repository

`github.com/Yumatlab/bioprocesssimulation` enthält bereits die
MATLAB-Anwendung. Dieses Repository hat damit **keine gemeinsame Historie** —
es ist eine eigene Wurzel. Zusammengebracht wird beides bewusst und sichtbar,
nicht durch einen Push:

- **Die Portierung geht auf einen eigenen Branch**, `python-port`, und von
  dort über einen Pull Request. `remote.origin.push` ist fest darauf
  eingestellt und `push.default` steht auf `nothing`, damit ein nacktes
  `git push` überhaupt kein Ziel hat.
- **`tools/pre-push-guard.sh` erzwingt es**, statt es zu versprechen. Der
  Hook weist drei Dinge ab: einen Push auf `main`/`master` der Gegenseite,
  das Löschen eines Remote-Branches, und jeden Push, der Commits der
  Gegenseite nicht als Vorfahren enthält — also genau das, was `--force` und
  `--force-with-lease` sonst durchlassen. Installiert wird er mit
  `tools/install-hooks.sh`; `.git/hooks` ist nicht Teil des Repositorys, ein
  Hook, der zählt, muss also getrackt und von dort kopiert werden.
- **Fünf Fälle durchgespielt** (Push auf main, neuer Branch, Überschreiben
  mit fremden Commits, Löschen, normales Fortschreiben) — die drei
  verbotenen scheitern, die zwei erlaubten laufen.

### Offen aus Phase 0

- **`main` der Gegenseite holen und ansehen**, bevor irgendetwas
  zusammengeführt wird. Erst dann ist zu entscheiden, ob die Portierung in
  ein Unterverzeichnis zieht — `.github/workflows/ci.yml` muss in jedem Fall
  im Wurzelverzeichnis liegen, sonst läuft die Matrix nicht.
- **CI-Matrix** läuft erst nach dem ersten Push (Plan §0.2). Der Workflow
  liegt bereit und baut auf jeden `v*`-Tag beide Installationsdateien.
  **Bis dahin ist der Windows-Build nicht nur ungetestet, sondern nie gebaut
  worden** — Cross-Compiling gibt es bei PyInstaller nicht, die CI ist der
  einzige Weg dorthin.
- ~~**Lizenz**~~ **festgelegt: MIT.** `LICENSE`, `license`-Feld in
  `pyproject.toml`, ein Abschnitt im README und der Info-Tab sagen es jetzt
  alle vier.

  Drei Dinge, die dabei auseinanderzuhalten waren. **Der CC-BY-4.0-Absatz im
  Info-Tab war die Lizenz der MATLAB-Anwendung**, wörtlich von dort
  übernommen — über den Python-Port sagte er nichts, und damit stand der
  rechtlich unter „alle Rechte vorbehalten". CC BY ist kein Copyleft, der
  Port durfte also frei gewählt werden; geschuldet ist nur die Namensnennung,
  und die steht jetzt in `LICENSE` und im Info-Tab: **Lena Sophia Kaletsch**
  als Vorentwicklerin der Anwendung (Version 1.3, 01.03.2024) und das
  BIOSIM-Programm von Prof. Dr.-Ing. R. Luttmann. **CC BY taugt nicht für
  Code** — Creative Commons rät selbst davon ab (keine Patentklausel, keine
  Quell-/Objektcode-Unterscheidung). Und **das gepackte Bündel enthält Qt**:
  PySide6 steht unter LGPLv3, eine Weitergabe der gebauten Datei schuldet
  den Lizenztext und die Möglichkeit, die Qt-Bibliotheken auszutauschen. Für
  die Weitergabe des Quellcodes gilt das nicht. `docs/installation.md` hat
  dafür einen eigenen Abschnitt.

---

## Kessel und Organismen anlegen — ohne Python

Zwei Dialoge derselben Bauart, **Library → Bioreactors…** und **Organisms…**
auf dem Startbildschirm. Liste links, das Objekt rechts, vier Handlungen:
auswählen, aus einem bestehenden einen neuen machen, bearbeiten, löschen.

- **Neu heißt kopieren.** Welche Parameter einen Kessel oder einen Organismus
  ausmachen, ist nichts, wonach ein Formular fragen sollte — das Objekt
  daneben weiß es. Ein leeres Formular hieße, den Anwender das Datenmodell
  auswendig können zu lassen.
- **Eine Änderung erreicht nur Neues.** `create_model` kopiert die Werte in
  `model_parameterTab`, `create_project` von dort in `project_parameterTab`:
  zwei Lagen Kopie, und beide sind der Grund, warum ein gespeicherter Lauf
  reproduzierbar ist. Beide Dialoge sagen es in der Kopfzeile, sonst würde es
  jemand anders herum erwarten.
- **Was benutzt wird, wird nicht gelöscht.** Die Kaskade die Modelle
  mitnehmen zu lassen ist der Weg, auf dem die MATLAB-Version Projekte
  verloren hat; beide `delete_*` fragen vorher `*_usage`.
- **Die Kinetik ist kein Datensatz.** `organismTab.function_file` zeigt auf das
  Modell-Plugin; der Dialog zeigt den Namen und lässt ihn nicht ändern. Eine
  Kopie behält die Kinetik, aus der sie kopiert wurde — neue Bilanzgleichungen
  sind ein Plugin, kein Formular. Genau an dieser Linie verläuft die Grenze
  zwischen „ohne Python" und „mit".
- **Ein Umbenennen ist ein `UPDATE`.** Modelle und Projekte zeigen auf
  `organismID`, nicht auf den Namen. Über `import_definition` zu gehen würde
  auf den Anzeigenamen schlüsseln und den alten Organismus neben dem neuen
  stehen lassen.
- **`save_organism_parameters` fasst nur die Werte an.** Kategorien,
  Variablen und Modelle beim Speichern von vier Zahlen mitzuschreiben wäre
  viel Risiko für wenig.
- **`default_modelTab.organismID` ist die einzige Referenz ohne
  `ON DELETE CASCADE`** — diese Zeilen löscht `delete_organism` deshalb
  selbst. Kein von Hand nachgebautes Kaskadieren, sondern die eine Stelle, für
  die das Schema keines erklärt.

**Ein neuer Kessel oder Organismus allein ist nicht auswählbar.** Ein Projekt entsteht aus
einem **Modell** — Organismus × Kessel —, und `create_project` liest nichts
außer `model_parameterTab`. Bis dahin konnte niemand ein Modell anlegen: der
Import schreibt `modelTab`-Zeilen ohne `bioreactorID`, und MATLABs
ModelCreator ist nicht portiert. `create_model()` macht die drei Schritte in
**einer** Transaktion, und beide Dialoge haben den Knopf „Make selectable…"
neben dem Objekt, das er betrifft — der eine fragt nach dem Organismus, der
andere nach dem Kessel.

**Der Kessel gewinnt, wenn beide Seiten denselben Parameter nennen.** Er darf
nur einmal vorkommen: `project_parameterTab` ist `UNIQUE (projectID,
parameterID)`, ein Modell mit einem doppelten Parameter ergäbe ein Projekt,
das sich nicht anlegen lässt. MATLAB hängt die beiden Tabellen aneinander und
merkt es nicht.

### Der dritte Dialog: die Modelle selbst

**Library → Models…**, gleiche Bauart wie die anderen beiden. Ein Modell
konnte bisher nur *nebenbei* entstehen — über „Make selectable…" neben einem
Organismus oder einem Kessel —, und danach gab es keine Stelle, an der man
eines ansehen, umbenennen, korrigieren oder entfernen konnte. Dabei ist
`model_parameterTab` die einzige Tabelle zwischen einer Definition und einem
Lauf: `create_project` liest nichts anderes.

- **Die Paarung ist nicht editierbar.** Organismus und Kessel stehen als
  Beschriftung da, nicht als Auswahlfeld. Sie zu tauschen hieße, Werte aus
  einem Kessel stehen zu lassen, den das Modell nicht mehr nennt — der
  Parametersatz wurde beim Anlegen aus beiden kopiert. Eine andere Paarung
  ist ein anderes Modell, und dafür gibt es `create_model`.
- **Parameter lassen sich weder hinzufügen noch entfernen**, nur ändern.
  Welche ein Modell trägt, entscheiden Organismus und Kessel;
  `save_model_parameters` meldet einen unbekannten Namen zurück, statt eine
  Zeile anzulegen.
- **`model_parameters` sagt, woher jeder Wert kommt** — Organismus, Kessel
  oder beide (dann hat der Kessel gewonnen). Das ist das Einzige, was ein
  Modell gegenüber den beiden Sätzen, aus denen es gebaut ist, hinzufügt, und
  es steht im Tooltip jedes Feldes.
- **Duplizieren kopiert den Ist-Zustand**, nicht die Vorgaben. Eine Variante
  entsteht aus dem Modell, nicht aus dem, woraus das Modell einmal entstand —
  sonst wäre „Duplicate" dasselbe wie ein zweites `create_model` auf
  derselben Paarung, und die bearbeiteten Werte fielen weg.
- **`projectTab.modelID` ist die einzige Referenz ohne `ON DELETE`-Klausel.**
  SQLite weist das Löschen also von sich aus ab; `model_usage` wird trotzdem
  vorher gefragt, damit ein Satz dasteht statt eines Constraint-Fehlers — und
  damit der Knopf grau sein kann, bevor jemand darauf drückt.
- **Ein Filterfeld über den Parametern**, als einziger der drei Dialoge. Ein
  Kessel hat 60 Parameter, ein Modell 253; das ist der Unterschied zwischen
  Blättern und Suchen. Gefiltert wird über Name, Symbol, Kategorie und
  Beschreibung.
- **`isVisibleTo(parent)`, nicht `isVisible()`** — der Test dazu wäre sonst
  immer grün und immer leer: in einem nie gezeigten Dialog meldet jedes
  Widget `False`. Dieselbe Falle wie in UX-Punkt 7.

### Platz zurückgeben: die eine Stelle ohne `get_connection`

Ein gelöschtes Projekt macht die Datei nicht kleiner — SQLite merkt die Seiten
als frei vor und behält sie. Gemessen auf einer Arbeitskopie: 119 MB ohne ein
einziges Projekt darin, und die produktive MATLAB-Datenbank bestand zu 98,9 %
aus freien Seiten. `db/maintenance.py` gibt sie zurück, **Load Project →
Compact Database…** ist der Knopf dazu.

- **`VACUUM` läuft nicht in einer Transaktion**, und `get_connection` öffnet
  genau eine. Deshalb ist das die einzige Stelle im Projekt mit einer eigenen
  `sqlite3.connect(..., isolation_level=None)` — die Regel wird gebrochen und
  im Modulkopf benannt, statt still umgangen zu werden.
- **Ohne Checkpoint schrumpft nichts.** Im WAL-Modus schreibt VACUUM die neu
  gebauten Seiten ins Log; die Hauptdatei behält ihre Größe, bis
  zurückgefaltet und abgeschnitten wird. Gemessen ohne die Zeile: 78,88 MB
  vorher, 78,88 MB nachher, Freiliste leer — die Arbeit war getan und
  unsichtbar. `PRAGMA wal_checkpoint(TRUNCATE)` gehört dazu, und der Test
  prüft die **Dateigröße auf der Platte**, nicht die Freiliste.
- **Vorher eine Kopie**, über die Backup-API wie überall sonst. VACUUM ist
  atomar und rollt zurück wie jede Anweisung, schreibt aber jede Seite der
  Datei neu; dieses Projekt schreibt keine Datenbank ohne Kopie daneben um.
- **Die Zeile über der Liste sagt, was zu holen ist** („78,88 MB, davon etwa
  78,31 MB ungenutzt"). „78,88 MB" allein gibt niemandem einen Grund, etwas zu
  drücken.
- Gemessen: 82,7 MB → 0,6 MB in 0,06 s, Projektliste, `dataTab`-Zeilen und
  `integrity_check` unverändert.

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

  **Die fünfte Abweichung: die Messwertverzögerung, und nur bei Pichia.**
  Sie ist von anderer Art als die vier oben — kein Logikfehler, sondern ein
  Einheitenfehler, und sie wird **nicht für beide Organismen** korrigiert.

  `meas_transfer_function` rechnet

  ```python
  T = dt / 3600          # dt liegt bereits in Stunden vor
  return previous + (T / tau) * (K * current - previous)
  ```

  Das Original übergibt `app.a.deltat` und teilt durch 3600, um von Sekunden
  auf Stunden zu kommen. In der Portierung ist `dt` schon in Stunden, also
  wird ein zweites Mal geteilt — und `tau` steht daneben in Sekunden. Ein
  Schritt schließt damit `dt/3600/tau` = **2,6e-09** des Abstands zwischen
  wahrem und gemessenem Wert: **jede Messgröße bleibt auf ihrem Anfangswert
  stehen.** Richtig wäre `dt/(tau/3600)` = 1/30 je Schritt bei tau = 60 s und
  Δt = 2 s. Die beiden liegen nicht einen, sondern **zwei** Umrechnungen
  auseinander, Faktor 3600² = 12 960 000 — die naheliegende Vermutung 3600 ist
  falsch, und `test_the_two_lags_differ_by_the_conversion_squared` schreibt es
  deshalb hin.

  **E. coli behält die Originalarithmetik.** Der Referenzlauf verifiziert sie:
  `pHLm`, `thetaLm`, `pO2m` und `cS1Lm` stimmen auf 1e-12 mit MATLAB überein.
  Das Original friert seine Messwerte also genauso ein, und eine Korrektur
  hier würde genau das kaputtmachen, wofür die Verifikation da ist. E. coli
  merkt nichts davon: sein Feed-Regler liest die *echte* Konzentration.

  **Pichia bekommt `sensor_lag`** — dieselbe Formel mit einer statt zwei
  Umrechnungen. Begründung, in dieser Reihenfolge:

  1. **Es gibt genau einen Leser einer Messgröße in dieser Anwendung**, und
     der steht im Pichia-Modell: `cSL = v[f"cS{n}Lm"][prev]` im Closed-Loop-
     Feed. Alle anderen Messreihen werden geschrieben und nie zurückgelesen —
     sie sind für Plot, Datentabelle und Export da. Die Abweichung berührt
     also genau einen Regelkreis und sonst keine Rechnung.
  2. **Ein Regler auf einer Konstanten regelt nichts.** Mit dem Original
     bleibt `cS2Lm` bei 0,000006 g/l, während `cS2L` auf 1,6 steigt; der
     Fehler bleibt bei seinem Sollwert stehen und der I-Anteil rampt die
     Pumpe weiter, bis die Kultur an der Methanoltoxizität stirbt.
  3. **Pichia ist nicht verifiziert** (kein Referenzlauf aus der aktuellen
     Quelle, siehe `docs/verification_escherichia_coli.md`). Hier ist also
     nichts zu verlieren, was es gibt — anders als bei E. coli.

  `test_the_two_organisms_measure_differently_and_on_purpose` bewacht beide
  Aufrufstellen; wer eine vertauscht, bekommt einen roten Test.
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
- **Die Anwendung hat ein eigenes Zeichen — und daneben zwei fremde.**
  `resources/icons/` trägt das eigene; es sagt, *was* das Programm ist.
  `resources/logos/` trägt die beiden Marken der HAW Hamburg und ihres Labors
  für Bioprozessautomatisierung; sie sagen, *woher* es kommt, und stehen
  deshalb im Info-Tab unter dem Satz, der die Hochschule nennt, und nicht
  neben dem eigenen Zeichen — nebeneinander läse sich das, als hätte die
  Hochschule das erste gezeichnet.

  **Die MIT-Lizenz überträgt keine Marke.** Das steht in `LICENSE` unter
  „Trademarks", und es steht dort, weil das Repository öffentlich werden
  kann: ein Fork nähme die Logos sonst einfach mit. Ein Fork, der nicht mehr
  die Software der HAW ist, löscht den Ordner — die Zeile im Info-Tab bleibt
  dann leer, und nichts geht kaputt.

  **Ein CMYK-JPEG bringt sein ICC-Profil mit.** Das BPA-Logo war 2,0 MB groß,
  davon 1,79 MB Farbprofil. Nach `convert("RGB")` steckt es weiter in
  `im.info` und landet wieder in der Ausgabedatei — ein 137 × 128 großes PNG
  wog damit 1354 KB. Verworfen sind es 18 KB. Qt zeichnet CMYK ohnehin nicht
  zuverlässig, die Umwandlung ist also nicht nur eine Größenfrage. Dieselbe
  Falle beim HAW-Logo: 557 KB Profil in einer 783-KB-Datei, das fertige PNG
  wiegt 15 KB. `test_no_logo_carries_a_colour_profile` prüft es jetzt für
  beide.

  **Ein Logo misst sich in Gerätepixeln, nicht in denen des Layouts.** Die
  Spalte im Info-Tab ist 128 *logische* Pixel breit, auf einem Retina-Schirm
  also 256 echte. Ein Pixmap, dem sein `devicePixelRatio` nicht gesagt wird,
  wird beim Zeichnen auf diese Breite gezogen — von Qt, stumm, unabhängig
  davon wie groß die Datei ist. **Das** war die Unschärfe des HAW-Logos, und
  die frühere Notiz hier („nie hochskalieren, die Quelle hat nur 274 × 77")
  benannte die falsche Hälfte: hochskaliert wurde nicht beim Laden, sondern
  beim Zeichnen. `scaled_mark(pixmap, column, ratio)` skaliert auf
  `column × ratio` und setzt das Verhältnis; die Obergrenze bleibt, was die
  Datei hergibt — eine zu kleine Quelle wird kleiner gezeichnet, nicht
  weicher. Die Quelle ist inzwischen die offizielle Marke in 1606 × 591,
  abgelegt mit 512 px Breite.

  **Die Funktion steht außerhalb des Fensters, weil `QLabel.pixmap()` lügt.**
  Es gibt eine geräteunabhängige Kopie zurück: für genau das Pixmap, das
  256 px breit mit Verhältnis 2 hineingegeben wurde, meldet es 128 und 1.
  Ein Test über das Label hätte die Regression nie gesehen — vor dem Label
  ist die einzige Stelle, an der sie sichtbar ist. Quelle ist `logo.png` (1024², transparent),
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

### Phase 8: fünf Dokumente, je eines pro Frage

`docs/` beantwortet fünf Fragen und keine zweimal. Ein Wegweiser
(`docs/README.md`) sagt, welche welche ist.

**Die Dokumentation ist englisch, diese Datei nicht.** Der Studiengang wird auf
Englisch gehalten; ein Handbuch, das die Hälfte der Leser nicht lesen kann, ist
keines. Übersetzt wurde an Ort und Stelle, mit englischen Dateinamen — zwei
Sprachfassungen nebeneinander laufen nach der dritten Änderung auseinander, und
dann weiß niemand, welche gilt. `CLAUDE.md` bleibt deutsch: sie ist die
Arbeitsdatei dieses Projekts und keine Abgabe. `docs/README.md` und
`docs/development.md` sagen beide, dass sie es ist.

| Datei | Frage |
|---|---|
| `manual.md` | Wie bediene ich das? |
| `installation.md` | Wie installiere und verteile ich das? |
| `architecture.md` | Wie ist das gebaut? |
| `development.md` | Wie entwickle ich es weiter? |
| `verification_escherichia_coli.md` | Stimmen die Zahlen? |

- **Diese Datei bleibt das Warum.** `architecture.md` ist die Landkarte und
  verweist hierher, statt die Begründungen zu wiederholen — zwei Texte über
  dieselbe Sache laufen nach der dritten Änderung auseinander, und dann weiß
  niemand mehr, welcher gilt.
- **Nichts wird behauptet, was nicht nachschlagbar ist.** Die
  Parameterbeschreibungen im Handbuch kommen aus `default_modelTab`, nicht aus
  dem Gedächtnis, und alle 34 dort genannten Parameternamen sind maschinell
  gegen `parameterTab` und `variableTab` geprüft worden. Ein Treffer kam
  zurück und hat einen Absatz korrigiert: `xO2` und `xCO2` haben in
  `variableTab` **gar keine Zeile** — die frühere Formulierung „die Datenbank
  ordnet sie keinem Organismus zu" war zu freundlich.
  Ebenso nachgemessen: die Schrittweite ist 2 s aus `deltatsec` und nicht die
  18 s aus `DEFAULT_DT` — `gui/app.py` überschreibt sie beim Öffnen.
- **`development.md` enthält den Startprompt für eine Version 4.** Er
  ist nicht Beiwerk, sondern der Kern des Dokuments: er nennt die sieben
  Regeln, deren Verletzung hier schon Schaden angerichtet hat, und verlangt
  Messungen statt Behauptungen. Die Zielgruppe ist eine Masterstudentin der
  Pharmazeutischen Biotechnologie, keine Informatikerin — Git und virtuelle
  Umgebungen werden so weit erklärt, wie man sie braucht, und nicht weiter.
- **Der Abschnitt „Wie Sie eine Änderung absichern" ist der wichtigste.** Er
  sagt, was die Anwendung selbst prüfen kann — ob sie dasselbe rechnet wie
  gestern — und was nicht: ob das Modell die Biologie richtig beschreibt.

### Arbeitsweise

Eine Konversation pro Phase. Zu Beginn: Phase nennen, `CLAUDE.md` ist der
Einstieg. Am Ende jeder Phase: diese Datei aktualisieren (Stand, neue
Konventionen), committen, kurze Zusammenfassung.
