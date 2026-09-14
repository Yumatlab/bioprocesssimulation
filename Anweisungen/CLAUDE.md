# Biofermentation Simulation App — Version 2

MATLAB-App-Designer-Anwendung zur Simulation von Bioreaktorprozessen. Master-Thesis-Projekt.

## Sprache

- Antworten im Chat: **Deutsch**
- Alle Code-Kommentare: **Englisch**

---

## Was die Software tut

Simuliert Fermentationsprozesse (Batch, Fed-Batch, Induktion) für verschiedene Mikroorganismen in verschiedenen Bioreaktoren. Pro Zeitschritt werden Regler (pO2, pH, Temperatur, Füllstand), Fütterung und Stoffbilanzen berechnet. Ein Phasen-Automat schaltet Prozessphasen anhand konfigurierbarer Start- und Endbedingungen weiter.

Zwei Organismen sind implementiert:
- **Escherichia coli** — 1 Reservoir, 18 ODE-Zustände, Substrate Glucose/Glycerol/Acetat
- **Pichia pastoris** — 2 Reservoirs (R1 Glycerol, R2 Methanol), 19 ODE-Zustände, AOX-Induktion nach Cornelissen

---

## Architektur

### Datenhaltung zur Laufzeit

Drei Structs am `app`-Objekt:

| Struct | Inhalt |
|---|---|
| `app.p` | Parameter (Sollwerte, Regler-Konstanten, Flags) — flach, `app.p.NStw` etc. |
| `app.v` | Variablen als Zeitreihen-Zeilenvektoren — `app.v.cXL(idx)` etc. |
| `app.a` | Hilfsgrößen (Regler-Zustände, abgeleitete Konstanten) — nicht persistiert |

`app.nxtidx` ist der aktuelle Index in allen `app.v`-Feldern.

### Preallokation

`preallocationFcn` hängt alle 20 Schritte einen NaN-Block an jedes `app.v`-Feld an. Grund: zyklisches Anhängen einzelner Werte ist zu langsam. Konsequenz: **`app.v`-Felder enthalten immer NaN-Slots am Ende**, die vor DB-Uploads gefiltert werden müssen.

Alle `app.v`-Felder müssen **Zeilenvektoren** sein. Die DB liefert Spaltenvektoren, deshalb wird in `loadProjectVariables` und `preallocationFcn` transponiert.

### Datenbankzugriff — genau zweimal pro Session

Das ist die zentrale Architekturentscheidung von Version 2. In Version 1 wurde zyklisch hoch- und heruntergeladen, was ohne Middleware Performance-Probleme verursachte.

| Zeitpunkt | Funktion | Was passiert |
|---|---|---|
| Session-Start | `loadPhases(app)` | Eine Verbindung: Lookup-Tabellen, Parameter + Metadaten, Phasen, Phasen-Parameter |
| Session-Ende | `saveProject(app)` | Parameter-Updates, Zeitreihen, Log; ruft `savePhases(app)` |

**Während der Simulation gibt es keine DB-Zugriffe.** Alle Editoren (`PhaseParameterEditor`, `PhaseFeedEditor`, `PhasePanelEditor`) lesen aus dem Memory.

`loadPhases` füllt:
- `app.p` — Parameterwerte
- `app.p_meta` — alle Parameter-Metadaten (tex, unit, type, category)
- `app.p_meta_cyclic` — nur `reading_rate = 'cyclic'`, für `PhaseParameterEditor`
- `app.p_modes` — `parameter_controlmodesTab`, für Dropdowns
- `app.Phases` — Struct-Array aller Phasen
- Lookup-Tabellen: `process_status`, `process_type`, `process_variable`, `process_operator`, `start_conditiontype`, `end_conditiontype`

### Aufrufreihenfolge in `ControlApp.startupFcn`

Kritisch — `loadPhases` muss vor `loadProject` laufen, weil `initialization_func` bereits `app.p` braucht:

```matlab
loadPhases(app);      % füllt app.p, app.p_meta, app.Phases
loadProject(app);     % → downloadProjectData → loadProjectVariables → initialization_func
% Timer erstellen und starten
% Phasen-Panels aus app.Phases aufbauen
```

### Phasensystem

`app.Phases` ist ein Struct-Array (ersetzt die frühere Tabelle `app.PhaseTable`):

```matlab
app.Phases(i).processID, .projectID, .statusID, .typeID, .name, .reservoirID
app.Phases(i).start.typeID, .variableID, .operatorID, .value, .time
app.Phases(i).end.typeID,   .variableID, .operatorID, .value, .time
app.Phases(i).parameters.(paramName) = value
```

`statusID`: 1 = Upcoming, 2 = Pending, 3 = Active, 4 = Ended
`typeID`: 1 = Blank, 2 = Stop, 3 = Parameter-Update, 4 = Puls-Feed, 5 = Exponentieller Feed

Start-Bedingungstypen: 1 = Variablenbedingung, 2 = vorherige Phase beendet, 3 = Batch-End-Erkennung
End-Bedingungstypen: 5 = nächste Phase startet, 6 = Variablenbedingung, 7 = Timer

`conditionCheck` / `evaluateCondition` ersetzen das frühere `conditionTypeCheck` mit `eval()`.

### Grid-Layout der Phasen-Panels

`rebuildGridColumns` ist die **einzige** Stelle, die `ProcessManagerGridLayout.ColumnWidth` anfasst, und baut sie immer komplett neu auf:

- Panel `i` → Spalte `2i-1` (210 px)
- Pfeil zwischen Phase `i` und `i+1` → Spalte `2i` (75 px)
- `AddPhaseButton` → letzte Spalte (100 px)

`app.arrowList{i}` ist der Pfeil zwischen Phase `i` und `i+1`. Es gibt also immer einen Pfeil weniger als Panels — Schleifen brauchen `i < numel(app.phaseList)` vor dem Arrow-Zugriff.

### Organismus-Module

Pro Organismus zwei Dateien, registriert in `organismTab.function_file` und `organismTab.initialization_file`, geladen per `str2func`:

- `<Name>_Initialization.m` — Reglerzustände, physikalische Konstanten, kinetische Konstanten, `app.v`-Startwerte unter `if app.nxtidx == 1`
- `<Name>.m` — Berechnung eines Zeitschritts

Struktur der Berechnungsfunktion: Index-Setup → Feeding → pO2-Regler → Füllstand → pH → Temperatur → Volumen-ODE → Respiration + pH-Iteration → (organismusspezifisch) → Konzentrationsbilanz-ODE → Messwerte → Zeitfortschritt.

---

## Datenbank

SQLite, `SimulationAppDB.db`, 31 Tabellen.

### Wichtigste Tabellen

| Tabelle | Zweck |
|---|---|
| `projectTab` | Projekte, verweist auf `organismTab`, `bioreactorTab`, `modelTab` |
| `project_parameterTab` | Parameterwerte pro Projekt |
| `timeTab` / `dataTab` | Zeitstempel und Variablenwerte (Langformat) |
| `processTab` / `process_parameterTab` | Phasen und phasenspezifische Parameter |
| `organismTab` | `function_file`, `initialization_file`, `reservoirs` |
| `variableTab` / `variable_handlingTab` | Variablendefinitionen, `visible`, `upload_rate` |
| `parameterTab` / `categoryTab` | Parameterdefinitionen, `reading_rate` |
| `model_parameterTab` | Standardwerte pro Modellvariante |
| `plot_templateTab` / `plot_variableTab` | Plot-Templates der FigureApp |
| `default_plot_variableTab` | Default-Werte für Plot-Variablen |
| `logTab` | Ereignis-Log |

### Bekannte Schema-Probleme

Beide sind in `migrate_schema.sql` behoben, das Skript ist aber **noch nicht auf die produktive DB angewendet**:

1. Alle Foreign Keys haben `MATCH SIMPLE`, wodurch `ON DELETE CASCADE` nicht zuverlässig greift.
2. `project_parameterTab` fehlt `UNIQUE (projectID, parameterID)`. Dadurch konnten Duplikate entstehen; ein solches Duplikat (parameterID 206/207/208 vs. 309/310/311 bei den Pichia-Modellen) hat das Anlegen neuer Pichia-Projekte blockiert.

### DB-Regeln

- `COUNT(*)` statt `MAX()` verwenden, um zu prüfen ob Daten existieren — `MAX()` gibt bei leerer Tabelle NULL zurück, was MATLAB-seitig crasht
- NaN-Preallokationsslots vor `sqlwrite` filtern (`validMask = ~isnan(procTimes)`)
- Jede Verbindung in `try`/`catch` mit `close(conn)` in beiden Zweigen
- Keine verschachtelten Transaktionen — jeder Block öffnet und schließt seine eigene Verbindung
- Timer (`app.Refresher`) vor jedem Schreibzugriff stoppen
- Die DB ist zweimal korrupt geworden. WAL-Modus (`PRAGMA journal_mode=WAL`) und ein rollierendes Backup nach jedem `saveProject` sind empfohlen, aber noch nicht implementiert.

---

## Dateien

```
apps/
  ControlApp.mlapp              Hauptfenster: Regler, Variablen, Phasen, Log
  FigureApp.mlapp               Plot-Fenster
  FigureAppSettings.mlapp       Plot-Einstellungen
  FigureAppTemplateManager.mlapp  Template-Verwaltung
  FigureAppVariableEditor.mlapp   Variablen-Editor
  PhasePanelEditor.mlapp        Phase bearbeiten
  PhaseFeedEditor.mlapp         Feed-Parameter pro Phase
  PhaseParameterEditor.mlapp    Parameter-Overrides pro Phase
  StartingScreen.mlapp          Einstieg
  SelectProject.mlapp           Projekt laden
  CreateProject.mlapp           Projekt anlegen
  ClosingScreen.mlapp           Speichern und beenden
  ModelCreator.mlapp            Modelle anlegen
  ModelConfigurator.mlapp       Modelle konfigurieren
  DialogBox1/2/3.mlapp          Parameter-Dialoge

organisms/
  Escherichia_coli.m / _Initialization.m
  Escherichia_ODE_Luttmann.m    18 Zustände
  Escherichia_ODE_Volume.m      4 Zustände
  Pichia_pastoris.m / _Initialization.m
  Pichia_ODE_Luttmann.m         19 Zustände
  Pichia_ODE_Volume.m           5 Zustände
  Pichia_Induction_Cornelissen.m   AOX-Induktion
  Pichia_Expression_Cornelissen.m  Produktexpression

Additional_functions/
  BatchEndDetection_pO2Slope.m
  centerWindow.m
  meas_transfer_function.m
```

---

## Standalone-Export

Ziel ist eine kompilierte Anwendung ohne MATLAB-Installation. Deshalb dürfen **keine Toolbox-Funktionen** verwendet werden außer denen der Base-Installation.

| Verwendet | Toolbox | Status |
|---|---|---|
| `ode15s`, `ode45`, `trapz`, `median`, `polyfit`, `str2func` | Base | in Ordnung |
| `sqlite`, `fetch`, `exec`, `sqlwrite` | Database Toolbox | **muss durch `mksqlite` ersetzt werden** |
| `spline`, `ppval`, `mkpp`, `unmkpp` in `updateTrendFcn` | Curve Fitting | **muss durch lineare Steigung ersetzt werden** |
| `medfilt1` | Signal Processing | bereits durch eigenes `slidingMedian` ersetzt |

Weitere Punkte: `addpath` funktioniert zur Laufzeit nicht, Pfade über `ctfroot()` auflösen; die DB-Datei muss mitgeliefert werden.

---

## Offene Aufgaben

1. **`mksqlite`-Migration** — alle `sqlite`/`fetch`/`exec`/`sqlwrite`-Aufrufe ersetzen. Blocker für den Standalone-Export.
2. **`updateTrendFcn`** — `spline`/`ppval`/`mkpp`/`unmkpp` durch lineare Steigung über die letzten 10 Punkte ersetzen.
3. **`migrate_schema.sql` anwenden** — entfernt `MATCH SIMPLE`, ergänzt den UNIQUE-Constraint.
4. **WAL-Modus und automatisches Backup** in `saveProject`.
5. **Initialization-Redesign** — `initControllerStates` und `initPhysicalConstants` als gemeinsame Funktionen ausgliedern. Reduziert eine Organismus-Initialisierung von ~200 auf ~50 Zeilen. Entwurf existiert, ist noch nicht eingebaut.
6. **Pichia-Modell testen** — neu geschriebene `Pichia_pastoris.m` ist noch nicht in einem vollständigen Lauf validiert.
7. **pO2-Regler abstimmen** — aktuell `Kp = 10`, `Ki = 1000`, `Kd = 0.0015`, was Dauerschwingung mit wachsender Amplitude erzeugt. Empfohlener Startpunkt: `Kp = 3…8`, `Ki = 15…20`, `Kd = 0`, plus Anti-Windup-Clamp auf `[0, NStmax]`.
8. **Benutzerhandbuch** — Gliederung steht (10 Kapitel plus Anhang), Inhalte fehlen.

---

## Konventionen

- Code-Kommentare auf Englisch
- `isfield`-Prüfung vor jedem `app.v.*`-Zugriff in UI-Update-Funktionen — beim Laden eines Projekts existieren nicht alle Felder
- `safeNum()` für NULL-sichere Umwandlung von SQLite-Werten
- SQL-Queries in `.mlapp`-Dateien einzeilig halten (mehrzeilige `sprintf` mit `...` brechen beim XML-Wiedereinsetzen)
- `getReport(ME)` statt `ME.message` beim Debuggen — liefert den vollständigen Stack
- Vor Änderungen an `.mlapp`: Backup. Vor Schema-Änderungen: DB-Backup.
- Claude Code kann MATLAB nicht ausführen — kleine Schritte, nach jedem Schritt selbst testen
