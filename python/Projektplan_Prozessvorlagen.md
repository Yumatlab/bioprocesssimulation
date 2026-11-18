# Projektplan: Prozessvorlagen im Process Manager

Stand der Grundlage: Arbeitsverzeichnis vom 18.11.2026 (HEAD `1691ee7` plus die
nicht committeten Änderungen dieser Woche). Aussagen über den Code beziehen sich
auf diesen Stand und nennen Funktionen statt Zeilennummern.

**Ziel:** Ein aufwendig entworfener Prozess — die Phasenliste im Process
Manager — lässt sich als **Vorlage** unter Name und Beschreibung speichern und
später in einem Projekt **desselben Modells** wieder laden. Beim Laden wird
gefragt, ob die noch nicht begonnenen Phasen des Projekts **ersetzt** werden oder
die Vorlage **dahinter angehängt** wird. Laufende und abgeschlossene Phasen
bleiben in jedem Fall stehen. Ob Vorlagen angeboten werden, entscheidet eine
Einstellung, damit Studierende ihren Prozess selbst entwerfen müssen.

---

## 1. Ablauf aus Sicht des Anwenders

1. Im Process Manager ist ein Prozess entworfen, z. B. Batch → Fed-Batch →
   Update Parameter Set → Stop.
2. **Process → Save process as template…** (Menü und Schaltfläche im Process
   Manager). Ein Dialog fragt nach **Name** und **Beschreibung** und zeigt die
   Phasen, die gespeichert werden.
3. Die Vorlage wird sofort in der Datenbank abgelegt, gebunden an das Modell
   des Projekts (Organismus × Bioreaktor). Der Log vermerkt es.
4. Später, in einem anderen Projekt desselben Modells: **Process → Load process
   template…** öffnet eine Liste der Vorlagen dieses Modells mit Beschreibung
   und Phasenvorschau.
5. Nach der Auswahl fragt die Anwendung:
   - **Replace** — alle noch nicht begonnenen Phasen werden entfernt, die
     Vorlage folgt auf die letzte begonnene oder abgeschlossene Phase;
   - **Append** — die Vorlage wird hinter die vorhandenen Phasen gereiht;
   - **Cancel**.
   Gibt es keine löschbaren Phasen, entfällt die Frage, und es wird angehängt.
6. Die neuen Phasen erscheinen im Process Manager als `upcoming` und lassen sich
   wie jede andere Phase bearbeiten. Gespeichert werden sie mit dem Projekt.

---

## 2. Was im Code schon da ist — und was daraus folgt

### 2.1 Wo die Phasen leben

| Ort | Inhalt |
|---|---|
| `processTab` | eine Zeile je Phase eines **Projekts**: Typ, Name, Start- und Endbedingung, Reservoir, **Status und Zeitstempel** |
| `process_parameterTab` | Parameterwerte je Phase (Update Parameter Set, Feeds) |
| `db/models.py` | `Phase` mit `Condition start/end` und `parameters: dict[name → value]` |
| `db/project.py` | `load_phases()` liest beides einmal beim Öffnen; `_save_phases()` ersetzt beim Speichern alle Phasen des Projekts |
| `gui/windows/control_app.py` | `add_phase`, `edit_phase`, `delete_phase`: ändern `setup.phases` unter `runner.editing()` und geben die Liste an `runner.phases` weiter |
| `gui/widgets/phase_panel.py` | Sperre: `ACTIVE` und `COMPLETED` sind weder bearbeitbar noch löschbar; bei laufendem Prozess ist gar nichts bearbeitbar |

Folgerungen:

- **`processTab` taugt nicht als Vorlagenspeicher.** `processID` ist
  tabellenweit eindeutig (Altlast 6 in `CLAUDE.md`), jede Zeile gehört einem
  Projekt, und Status sowie `start_time`/`end_time` sind Laufzeitdaten, kein
  Entwurf. Eine Vorlage mit `projectID = NULL` dort abzulegen, hieße, dass
  `load_phases`, `_claim_free_process_ids` und das Löschen eines Projekts jede
  Zeile auf diesen Sonderfall prüfen müssten. → **Eigene Tabellen.**
- **Die Sperre gibt es schon.** „Begonnen" heißt im Code `ACTIVE` (3) und
  `COMPLETED` (4); `upcoming` (1) und `pending` (2) sind löschbar. Der
  Ersetzen-Weg nutzt genau diese Unterscheidung und keine neue.
- **Parameter werden über ihren Namen geführt**, Bedingungen über
  `variableID` aus `process_variableTab` des Organismus und über
  Reservoirnummern. Innerhalb desselben Modells passen alle drei. Deshalb wird
  eine Vorlage an das **Modell** gebunden, wie gewünscht.
- **Timer speichern Dauer und Zeitpunkt getrennt:** `end.value` ist die
  eingestellte Dauer, `end.time` der beim Start berechnete Zeitpunkt. In eine
  Vorlage gehört nur der Wert, nie die Zeit.
- **„End of previous phase" (Startbedingung 2) startet sofort**, wenn die
  vorige endet (`PhaseAutomaton.condition_check`). Eine angehängte Vorlage
  beginnt also nahtlos nach der letzten vorhandenen Phase. Das ist gewollt,
  muss aber im Ladedialog stehen.

### 2.2 Wie Schema und Einstellungen bisher erweitert werden

- Schema: `migrate_schema.sql` (`CREATE … IF NOT EXISTS`, idempotent) plus
  `ensure_columns`/`ensure_indexes` beim Start, weil die Datenbank eines
  Anwenders eine Kopie der Vorlage von seinem ersten Start ist.
- Wiederaufbaupfad: 23 CSVs unter `resources/defaults/`, `export_defaults()`.
  Zählende Tests in `test_db.py`.
- Einstellungen: `gui/settings.py` (`Settings`-Felder, `settings.yaml` neben der
  Datenbank), Dialog `gui/dialogs/settings.py`. Gelesen wird beim Öffnen eines
  Projekts, nicht laufend.

### 2.3 Eine Regel, die hier bewusst gebrochen wird

`CLAUDE.md`: **zwei Datenbankzugriffe je Sitzung** — laden beim Start, schreiben
am Ende. Eine Vorlage muss aber gespeichert sein, sobald der Anwender „Save"
drückt, unabhängig davon, ob er das Projekt danach speichert oder verwirft.
Deshalb:

- Speichern und Auflisten der Vorlagen sind **eigene, kurze Transaktionen** über
  `get_connection`, ausgelöst nur durch einen Dialog, nie durch den Timer.
- Sie fassen **keine Zeile des laufenden Projekts** an (nur die drei neuen
  Tabellen), sie können sich also nicht mit dem Speichern des Projekts in die
  Quere kommen.
- Die Ausnahme wird im Modulkopf benannt, wie in `db/maintenance.py`.

---

## 3. Entscheidungen

**Bestätigt am 18.11.2026**: alle Empfehlungen E1–E10, wie unten.

| # | Frage | Empfehlung |
|---|---|---|
| E1 | Bindung | **An das Modell** (`modelID`), wie gewünscht. Projekte eines anderen Modells desselben Organismus sehen die Vorlage nicht. |
| E2 | Was gespeichert wird | **Alle Phasen** des Entwurfs, auch begonnene und abgeschlossene — der Entwurf ist das Ganze. Ohne Status, ohne Zeitstempel; geladen werden alle als `upcoming`. |
| E3 | Gleicher Name im selben Modell | **Nachfragen und überschreiben** (eine Transaktion: alte Vorlage löschen, neue schreiben). Kein stilles Duplikat. |
| E4 | Was die Einstellung abschaltet | **Laden und Speichern** — beide Menüeinträge und die Schaltfläche verschwinden. Nur Laden abzuschalten ließe Studierende Vorlagen anlegen, die sie nicht nutzen können. Vorgabe: **an**. |
| E5 | Studierendenansicht | Unabhängig von der neuen Einstellung (zwei Schalter, zwei Fragen). Im Einstellungsdialog direkt darunter. |
| E6 | Laden bei laufendem Prozess | **Nicht möglich**, wie Bearbeiten heute: „Pause the process to load a template". |
| E7 | Modell wird gelöscht | Vorlagen gehen mit (`ON DELETE CASCADE`). `model_usage` zählt sie mit, und der Bestätigungstext von „Delete" nennt die Zahl. |
| E8 | Modell wird dupliziert | Vorlagen **werden mitkopiert** — die Kopie ist eine Variante desselben Prozesses. |
| E9 | Verwaltung | Umbenennen und Löschen im Ladedialog. Keine eigene Library-Seite in dieser Fassung. |
| E10 | Übertragung zwischen Installationen | **Nicht in dieser Fassung.** Später mit dem Organismus-/Modellpaket (`db/definitions.py`), über Namen verschlüsselt wie dort. |

Zu E4: Die Einstellung ist keine Sicherung. `settings.yaml` ist eine Textdatei,
die jeder ändern kann. Sie ist eine Vorgabe für den Kurs, genau wie die
Studierendenansicht.

---

## 4. Datenmodell

Drei Tabellen, nach dem Muster von `processTab`/`process_parameterTab`, aber
ohne Laufzeitspalten und mit den Fremdschlüsseln, die dort falsch sind
(Altlast 1 und „Offen aus Phase 1": `start_operatorID` zeigt in `processTab`
auf `process_conditiontypeTab`).

```sql
CREATE TABLE IF NOT EXISTS process_templateTab (
    templateID   INTEGER PRIMARY KEY AUTOINCREMENT,
    modelID      INTEGER NOT NULL REFERENCES modelTab (modelID) ON DELETE CASCADE,
    name         TEXT    NOT NULL,
    description  TEXT,
    author       TEXT,
    created_on   TEXT,
    UNIQUE (modelID, name)
);

CREATE TABLE IF NOT EXISTS process_template_phaseTab (
    template_phaseID INTEGER PRIMARY KEY AUTOINCREMENT,
    templateID       INTEGER NOT NULL REFERENCES process_templateTab (templateID) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    process_typeID   INTEGER NOT NULL REFERENCES process_typeTab (process_typeID),
    name             TEXT,
    reservoirID      INTEGER,
    start_typeID     INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
    start_variableID INTEGER REFERENCES variableTab (variableID),
    start_operatorID INTEGER REFERENCES process_operatorTab (process_operatorID),
    start_value      REAL,
    end_typeID       INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
    end_variableID   INTEGER REFERENCES variableTab (variableID),
    end_operatorID   INTEGER REFERENCES process_operatorTab (process_operatorID),
    end_value        REAL,
    UNIQUE (templateID, position)
);

CREATE TABLE IF NOT EXISTS process_template_parameterTab (
    template_parameterID INTEGER PRIMARY KEY AUTOINCREMENT,
    template_phaseID     INTEGER NOT NULL REFERENCES process_template_phaseTab (template_phaseID) ON DELETE CASCADE,
    parameterID          INTEGER NOT NULL REFERENCES parameterTab (parameterID) ON DELETE CASCADE,
    value                REAL NOT NULL,
    UNIQUE (template_phaseID, parameterID)
);

CREATE INDEX IF NOT EXISTS process_templateTab_modelID ON process_templateTab (modelID);
CREATE INDEX IF NOT EXISTS process_template_phaseTab_templateID
    ON process_template_phaseTab (templateID);
CREATE INDEX IF NOT EXISTS process_template_parameterTab_phaseID
    ON process_template_parameterTab (template_phaseID);
```

- **`position`** statt Reihenfolge über die ID: die Reihenfolge ist Inhalt der
  Vorlage, nicht ein Nebeneffekt des Einfügens.
- **Ein Index je Fremdschlüssel** (Altlast 8: ohne Index wird das Löschen
  quadratisch).
- **Kein NaN wird geschrieben** — fehlende Werte sind `NULL`, wie überall.
- **Keine Zeitspalten.** Siehe 2.1.

---

## 5. Architektur

| Schicht | Datei | Inhalt |
|---|---|---|
| Datenbank | `db/process_templates.py` (neu) | `list_process_templates(db, model_id)`, `load_process_template(db, template_id) → ProcessTemplate`, `save_process_template(db, model_id, name, description, phases, *, author, replace=False)`, `rename_process_template`, `delete_process_template`, `template_count(db, model_id)` |
| Datenmodell | `db/models.py` | `ProcessTemplate(templateID, modelID, name, description, author, created_on, phases: list[Phase])` — die Phasen sind gewöhnliche `Phase`-Objekte mit `processID = 0`, `statusID = None`, ohne Zeiten |
| Kernlogik, ohne Qt | `control/templates.py` (neu) | `phases_from_template(template, next_process_id, project_id)` und `apply_template(phases, template_phases, mode)` mit `mode` ∈ {`replace`, `append`}; `check_template(template, setup) → list[str]` |
| Oberfläche | `gui/dialogs/process_templates.py` (neu) | `SaveTemplateDialog`, `LoadTemplateDialog` (Liste, Beschreibung, Phasenvorschau, Umbenennen, Löschen) |
| Fenster | `gui/windows/control_app.py` | `save_process_template()`, `load_process_template()`; Menü **Process**, zwei Schaltflächen im Process Manager |
| Einstellungen | `gui/settings.py`, `gui/dialogs/settings.py` | `Settings.process_templates: bool = True`, Kontrollkästchen „Offer process templates" |
| Schema | `db/migrate_schema.sql`, Start in `gui/app.py` | die drei Tabellen; `ensure_template_tables` beim Start wie `ensure_indexes` |

Regeln, die durchgehen:

- **Die Kernlogik kennt keine Oberfläche und keine Datenbank.** `apply_template`
  bekommt Listen und gibt eine Liste zurück; die Sperre liest es aus dem Status
  der Phasen. So ist der wichtigste Teil — was entfernt wird und was stehen
  bleibt — ohne Fenster testbar.
- **Jede Änderung an `setup.phases` läuft durch `runner.editing()`** und wird
  danach an `runner.phases` übergeben, genau wie `add_phase`.
- **Neue `processID`s kommen aus `setup.next_process_id`.** Kollisionen mit
  anderen Projekten heilt `_claim_free_process_ids` beim Speichern ohnehin.
- **Eine Vorlage, die nicht passt, wird nicht still angepasst.** `check_template`
  meldet: Parameter, die das Modell nicht mehr hat; Variablen, die nicht in
  `process_variableTab` des Organismus stehen; Reservoirs über
  `n_reservoirs`. Der Ladedialog nennt die Gründe und lädt nicht.

### Ersetzen und Anhängen, genau

```
vorhanden:  [P1 completed] [P2 active] [P3 pending] [P4 upcoming]
Vorlage:    [T1] [T2] [T3]

append  →   [P1] [P2] [P3] [P4] [T1] [T2] [T3]
replace →   [P1] [P2] [T1] [T2] [T3]          (P3, P4 entfernt)
```

- „Löschbar" ist dieselbe Bedingung wie im `PhasePanel`: Status nicht `ACTIVE`
  und nicht `COMPLETED`. Eine Funktion dafür, von beiden genutzt.
- Ersetzen verlangt **eine zweite Bestätigung**, wenn es Phasen mit
  Parametern entfernt: „P3 and P4 will be removed. This cannot be undone."
- Steht der Automat auf einer entfernten Phase (`pending`), wird
  `runner.phases.current` zurückgesetzt — derselbe Schritt wie in
  `delete_phase`.
- Der Log schreibt eine Zeile: „Process template 'X' loaded: 3 phases,
  replacing 2" bzw. „appended".

---

## 6. Phasen

Eine Sitzung je Phase. Nach jeder Phase die ganze Suite, dann `CLAUDE.md`
nachziehen. Die Aufwandsangaben sind Schätzungen, keine Zusagen.

### Phase 0 — Festlegen (½ Sitzung) — erledigt 18.11.2026

Ergebnisse, am Code gelesen und am Lauf geprüft:

- **P0-1 · Fehler gefunden und behoben: Löschen neben einer aktiven Phase
  startete diese neu.** `ControlWindow.delete_phase` setzte nach jedem Löschen
  `runner.phases.current = None`. Ist dabei eine Phase aktiv, hält
  `check_start` sie beim nächsten Takt für die nächste und startet sie erneut.
  Gemessen an Projekt 519 (gespeichert mit aktivem „Fed Batch"): Löschen der
  letzten, noch nicht begonnenen Phase und ein Takt — Startzeit 3,502 h → 0,0,
  `FR1j` 0,0545 → 0 l/h, der Feed bricht weg. Behoben: nach dem Löschen sucht
  `adopt_active_phase()` die aktive Phase wieder, dieselbe Funktion wie beim
  Laden eines Projekts. Test
  `test_deleting_an_upcoming_phase_leaves_the_active_one_running`
  (`test_control_gui.py`), schlägt mit der alten Zeile fehl (Gegenprobe
  gelaufen). **Für Phase 2 heißt das:** `apply_template` im Ersetzen-Modus
  benutzt denselben Weg, nie `current = None`.
- **P0-2 · Eine Feed-Phase speichert ihre Ergebnisse als Parameter.**
  `_exponential_feed` schreibt `t{n}j`, `cXL{n}j`, `FR{n}j` in
  `phase.parameters`; in den mitgelieferten Projekten 519/520 sind das die
  *einzigen* Parameter ihrer Feed-Phasen. `PHASE_PARAMETERS` nennt sie
  ausdrücklich „Ergebnisse, nicht Einstellungen". **Eine Vorlage speichert sie
  nicht** (Test in Phase 1). Die Feed-Einstellungen (`qXpX{n}w` usw.) reisen
  nur mit, wenn sie in der Phase selbst eingetragen sind; sonst gelten beim
  Laden die Werte des Zielprojekts. Der Speicherdialog sagt das bei jeder
  Feed-Phase ohne eigene Einstellungen.
- **P0-3 · Anhängen hinter einen beendeten Prozess funktioniert.** An Projekt
  520 (alle sieben Phasen abgeschlossen) geprüft: `check_start` nimmt die Phase
  nach der letzten abgeschlossenen, die angehängte startet beim nächsten Takt,
  ihr Timer wird ab dem Start gestempelt.
- **P0-4 · Anhängen hinter eine aktive Phase:** `check_end` setzt beim Ende
  der aktiven Phase die nächste auf `PENDING` — das ist dann die erste der
  Vorlage. **Achtung:** endet die aktive Phase mit „Next phase condition"
  (Endbedingung 5), entscheidet die *Startbedingung der nächsten Phase*, wann
  sie endet (`condition_check` geht dorthin). Ersetzen kann also das Ende der
  laufenden Phase verschieben. Der Ladedialog warnt in genau diesem Fall.
- **P0-5 · `pending`** ist die nächste Phase, die auf ihre Startbedingung
  wartet; sie ist nie `current`. Sie zu entfernen ist mit P0-1 gefahrlos:
  `check_start` macht danach die nächste zur wartenden.
- **P0-6 · Timer:** `end.value` ist die Dauer, `end.time` stempelt
  `check_start` beim Start. Bestätigt, die Vorlage speichert nur den Wert.
- **P0-7 · Unbekannte Parameter werden still übergangen:**
  `_apply_parameters` kopiert nur Namen, die `p` kennt. Darum muss
  `check_template` sie vor dem Laden melden (Phase 2), sonst fehlt ein Wert,
  ohne dass es jemand sieht.
- **P0-8 · Parameter je Phasentyp:** Manual und Stop tragen keine; Pulse Feed
  `kR{n}`, `FR{n}max`; Exponential Feed die fünf aus `PHASE_PARAMETERS` plus
  die Ergebnisse (P0-2); Update Parameter Set beliebige zyklische Parameter.
  Alle über den Namen, also innerhalb eines Modells übertragbar.

Ursprünglicher Auftrag dieser Phase:

- Entscheidungen E1–E10 bestätigen oder ändern.
- Gegenlesen am Code: `PhaseAutomaton.check_start`/`condition_check` für
  angehängte Phasen nach einer aktiven; was `pending` genau bedeutet und ob
  eine `pending`-Phase gefahrlos entfernt werden kann; ob `Phase.parameters`
  für alle fünf Phasentypen vollständig ist (`PHASE_PARAMETERS`).
- **Fertig, wenn** die Entscheidungen hier eingetragen sind.

### Phase 1 — Datenbank (1 Sitzung) — erledigt 18.11.2026

Ergebnis: `db/process_templates.py`, `ProcessTemplate` in `db/models.py`,
Schema in `db/migrate.py` (`TEMPLATE_TABLES`, `ensure_template_tables`),
`tests/test_process_templates.py` (22 Tests), ganze Suite grün (891).

- **Abweichung vom Plan: Vorlagen gehören nicht in den CSV-Satz.** Der
  Default-Datensatz enthält ausdrücklich keine Anwenderdaten, und Vorlagen
  sind Anwenderdaten wie Projekte. Im CSV-Satz würde `load_defaults` sie beim
  Wiederaufbau leeren; außerhalb nähme das Leeren von `modelTab` sie per
  Kaskade mit. Deshalb: 23 CSVs wie bisher, und `load_defaults` verweigert
  den Dienst, solange Vorlagen existieren — derselbe Schutz wie für Projekte.
- **Das SQL steht nur in `migrate.py`**, nicht zusätzlich in
  `migrate_schema.sql`: `apply_migration` und der Programmstart rufen dieselbe
  Funktion. `migrate_schema.sql` verweist mit einem Kommentar darauf.
- **Ergebnisparameter** werden über `RESULT_PARAMETER`
  (`(t|cXL|FR)\d+j`) erkannt — trifft in `parameterTab` genau die neun
  Ergebnisse von Reservoir 1–3 und sonst nichts (geprüft).
- **Unbekannte Parameternamen** werden beim Speichern mit Namen abgewiesen,
  nicht still verworfen (P0-7).
- **Ältere Datenbanken:** `model_usage` und `duplicate_model` fragen, ob die
  Tabellen existieren; ohne sie verhalten sich beide wie vorher.
- Vorlage-Datenbank ergänzt (`VACUUM` danach, 0 freie Seiten, keine
  Fremdschlüsselverletzung). Auf einer **Kopie** der produktiven Datenbank:
  Tabellen angelegt, zweiter Lauf legt nichts an, `foreign_key_check` leer,
  `integrity_check` ok. Die produktive Datei selbst ist unverändert; das
  Programm ergänzt sie beim nächsten Start.
- Gegenproben gelaufen: ohne Ergebnisfilter schlagen zwei Tests fehl, ohne
  Kopieren beim Duplizieren einer.

Ursprünglicher Auftrag dieser Phase:

- Schema in `migrate_schema.sql`, `ensure_template_tables` beim Start, auf die
  mitgelieferte Vorlage anwenden (danach `VACUUM`), CSV-Satz mit
  `export_defaults` neu erzeugen (23 → 26 Dateien), zählende Tests anpassen.
- `db/process_templates.py` mit den Funktionen aus Abschnitt 5, je eine
  Transaktion.
- `model_usage` zählt Vorlagen, `duplicate_model` kopiert sie (E7, E8).

Tests (`tests/test_process_templates.py`):
- `test_saving_and_loading_gives_back_the_same_phases` (Typ, Name, Reservoir,
  Bedingungen, Parameter; ohne Status und Zeiten)
- `test_a_timer_keeps_its_duration_not_its_time`
- `test_the_order_is_kept`
- `test_a_name_is_unique_per_model_not_per_database`
- `test_overwriting_replaces_the_whole_template_in_one_transaction`
- `test_an_interrupted_save_leaves_nothing` (Abbruch mitten im Schreiben)
- `test_deleting_a_model_takes_its_templates`
- `test_duplicating_a_model_copies_its_templates`
- `test_the_migration_is_idempotent_and_leaves_no_foreign_key_violation`
- `test_the_results_of_a_feed_are_not_saved` (P0-2: `t{n}j`, `cXL{n}j`, `FR{n}j`)
- `test_a_database_from_before_still_opens` (Tabellen fehlen → werden angelegt)

**Fertig, wenn** die Suite grün ist und eine Kopie der produktiven Datenbank
die Migration ohne Fremdschlüsselverletzung übersteht.

### Phase 2 — Kernlogik (½ Sitzung) — erledigt 18.11.2026

Ergebnis: `control/templates.py`, `is_started` in `control/phases.py`,
`tests/test_control_templates.py` (19 Tests), ganze Suite grün (910).

- **Funktionen:** `phases_from_template` (Kopien, neue `processID`s ab
  `next_process_id`, Status `upcoming`, keine Zeiten), `place_template(phases,
  new, mode)` → `Placement(phases, added, removed)` — gibt eine neue Liste
  zurück und lässt die übergebene unverändert, `hand_over(automaton, phases)`
  (setzt die Liste und ruft `adopt_active_phase`, P0-1), `check_template` /
  `check_template_for` (anderes Modell, unbekannter Phasentyp, unbekannter
  Parameter, Bedingung auf einer Variablen, die der Organismus nicht anbietet,
  Reservoir außerhalb), `end_moves_with_replacement` (P0-4), `removable`.
- **Eine Regel für „begonnen":** `is_started(phase)` in `control/phases.py`;
  `PhasePanel` sperrt damit, `place_template` behält damit. Ein Test hält
  beide zusammen.
- **Abnahmetest gelaufen:** Projekt 716, vier Phasen (Batch, Update Parameter
  Set `thetaLw` 34 °C, Exponential Feed mit Variablen-Startbedingung auf
  `cXL`, Hold), 240 Blöcke. Einmal von Hand, einmal gespeichert → geladen →
  platziert: alle Reihen bitgleich, Phasenzeiten und `p` identisch, drei
  Phasen abgeschlossen, die vierte aktiv.
- **Ersetzen hinter einer aktiven Phase** an Projekt 519 mit echtem Block:
  „Fed Batch" bleibt aktiv, Startzeit und `FR1j` unverändert, die drei
  kommenden Phasen sind ersetzt.
- Gegenproben: Vorlagenphasen ohne Parameter → Abnahmetest rot; Ersetzen ohne
  Statusprüfung → zwei Tests rot; `hand_over` mit `current = None` → rot.

Ursprünglicher Auftrag dieser Phase:

- `control/templates.py`: `phases_from_template`, `apply_template`,
  `check_template`; die Löschbarkeitsfrage als eine Funktion, die auch
  `PhasePanel` benutzt.

Tests:
- `test_append_keeps_every_phase_and_adds_behind`
- `test_replace_keeps_active_and_completed_phases`
- `test_replace_removes_upcoming_and_pending_phases`
- `test_loaded_phases_are_upcoming_and_have_no_times`
- `test_loaded_phases_get_fresh_process_ids`
- `test_replacing_behind_an_active_phase_keeps_it_running` (P0-1, mit Takt)
- `test_a_next_phase_end_before_a_replacement_is_reported` (P0-4)
- `test_a_template_with_an_unknown_parameter_is_refused_with_its_name`
- `test_a_template_with_a_reservoir_the_model_lacks_is_refused`
- `test_loading_into_a_run_gives_the_same_run_as_entering_the_phases_by_hand`
  (E. coli 716: Vorlage laden gegen dieselben Phasen von Hand → bitgleich)

### Phase 3 — Speichern in der Oberfläche (1 Sitzung) — erledigt 18.11.2026

Ergebnis: `gui/dialogs/process_templates.py` (`SaveTemplateDialog`,
`describe_phase`, `feed_settings_missing`), Menü **Process** und
`save_process_template` in `ControlWindow`, Schaltfläche „Save as template…"
im `PhaseGrid`, `tests/test_process_template_gui.py` (15 Tests), ganze Suite
grün (925).

- ~~Die Schaltfläche sitzt unter dem „+"~~ — **am 18.11.2026 auf Wunsch des
  Anwenders geändert:** das „+" steht wieder allein in der Phasenreihe, wie
  vorher; „Save as template…" und „Load template…" stehen in einer eigenen
  Leiste (`PhaseGrid.template_bar`) **unten rechts unter der Scrollfläche**,
  also immer sichtbar, wie weit die Reihe auch gerollt ist. Die Tabseite ist
  dafür ein Rahmen aus Scrollfläche und Leiste; die Gestaltung der
  Scrollfläche steht jetzt in `_style_scroll_area` und wird für
  `process_area` eigens aufgerufen.
- **Speichern geht auch bei laufendem Prozess**, anders als Hinzufügen: es
  ändert nichts am Lauf. Die Phasen werden unter `runner.editing()` kopiert.
- **Die Rückfragen sind eigene Methoden** (`_ask_template_details`,
  `_confirm_overwrite`), damit die Tests sie ersetzen; die Schreiblogik steht
  in `_store_template`.
- **Feed-Phasen ohne eigene Einstellungen** (P0-2) tragen in der Liste den
  Hinweis „feed settings from the project it is loaded into". Die Zeilen
  brechen um — im ersten Bild lag der Hinweis hinter einem Rollbalken.
- Geprüft, dass Speichern **keine andere Tabelle** berührt (alle Zeilen aller
  übrigen Tabellen vorher/nachher gleich) und den Lauf nicht anhält.
- Bestehender Test angepasst: `test_the_control_window_has_its_menu_bar`
  kennt jetzt das Menü „Process" — das erste, das das Original nicht hatte.
- Gegenproben: Überschreiben ohne Rückfrage → rot; Schaltfläche bei laufendem
  Prozess gesperrt → rot.

Ursprünglicher Auftrag dieser Phase:

- Menü **Process** mit „Save process as template…", Schaltfläche im Process
  Manager.
- `SaveTemplateDialog`: Name (Pflicht), Beschreibung, Liste der Phasen;
  gleicher Name → Nachfrage (E3). Autor vorbelegt aus dem Projekt.
- Ausnahme von der Zwei-Zugriffe-Regel im Modulkopf benennen (Abschnitt 2.3).

Tests:
- `test_saving_a_template_writes_only_the_template_tables`
- `test_saving_does_not_save_the_project`
- `test_an_empty_name_cannot_be_saved`
- `test_saving_is_logged_as_an_operation`

### Phase 4 — Laden in der Oberfläche (1 Sitzung) — erledigt 18.11.2026

Ergebnis: `LoadTemplateDialog` in `gui/dialogs/process_templates.py`,
`ControlWindow.load_process_template`, Schaltfläche „Load template…" unter
„Save as template…", `Settings.process_templates` mit Kontrollkästchen
„Offer saving and loading process templates" direkt unter der
Studierendenansicht; 19 neue Tests in `tests/test_process_template_gui.py`
(34 insgesamt), ganze Suite grün (944).

- **Ablauf:** bei laufendem Prozess abgelehnt (E6; die Schaltfläche ist dann
  gesperrt wie „+") → keine Vorlage für das Modell: Hinweis, wie man eine
  anlegt → Auswahl im Dialog → `check_template_for`; passt sie nicht, nennt
  eine Meldung jeden Grund und es wird nichts geladen → gibt es Phasen, die
  noch nicht begonnen haben: Frage „Append / Replace / Cancel", die die
  wegfallenden Phasen nennt und bei P0-4 warnt → bei „Replace" eine zweite
  Bestätigung mit den Namen → Einsetzen unter `runner.editing()`, die Liste
  **an Ort und Stelle** ersetzt (`setup.phases[:] = …`), damit jeder, der sie
  hält, den neuen Plan sieht, danach `hand_over`.
- Ohne löschbare Phasen (leerer Prozess, alles abgeschlossen) wird ohne Frage
  angehängt.
- **Der Dialog schreibt nur beim Umbenennen und Löschen** in die Datenbank,
  beides mit Rückfrage bzw. Meldung bei vergebenem Namen.
- **Ausgeschaltet** fehlt das ganze Menü „Process" (es enthält nur die
  Vorlagen) und beide Schaltflächen sind verborgen; „+" bleibt.
- Logeintrag als Operation: „Process template 'X' loaded: n phases,
  appended" bzw. „replacing k phase(s): …".
- Geprüft: der geladene Prozess wird mit dem Projekt gespeichert (Status
  `upcoming`, Timerdauer erhalten).
- Gegenproben: Laden bei laufendem Prozess, Ersetzen ohne zweite Frage,
  Menü trotz ausgeschalteter Einstellung — jede macht einen Test rot.

Ursprünglicher Auftrag dieser Phase:

- `LoadTemplateDialog`: Vorlagen des Modells, Beschreibung, Phasenvorschau,
  Prüfbefund aus `check_template`; Umbenennen und Löschen (E9).
- Frage Ersetzen / Anhängen / Abbrechen; zweite Bestätigung beim Ersetzen;
  Einfügen unter `runner.editing()`; nur bei pausiertem Prozess (E6).
- `Settings.process_templates` und das Kontrollkästchen; ist es aus, gibt es
  weder Menü noch Schaltflächen (E4).

Tests:
- `test_the_dialog_lists_only_templates_of_this_model`
- `test_loading_appends_behind_a_running_process`
- `test_replacing_never_touches_a_started_phase`
- `test_loading_while_running_is_refused`
- `test_the_automaton_sees_the_new_phases`
- `test_switched_off_there_is_no_way_to_templates` (Menü, Schaltflächen)
- `test_a_loaded_process_is_saved_with_the_project`
- `test_a_loaded_template_is_logged`

### Phase 5 — Dokumentation und Abnahme (½ Sitzung) — erledigt 18.11.2026

- **Handbuch** (`docs/manual.md`): Abschnitt „Process templates" am Ende von
  „How a process runs: phases" (Speichern, was gespeichert wird, Laden,
  Anhängen/Ersetzen, laufende Phasen); „Process templates on or off" unter den
  Einstellungen; `settings.yaml` in der Dateitabelle.
- **`architecture.md`:** ein Absatz unter „The phase automaton".
- **Bild** `10_process_templates.png` in `gui/screenshots.py` (der Rendertest
  zählt jetzt 11). Gebaut auf einer Kopie in einem eigenen temporären Ordner,
  weil `render()` eine echte Datenbank übergeben bekommen kann.
- **Abnahme gelaufen**, durch das Fenster statt nur durch die Funktionen:
  `tests/test_process_template_acceptance.py` (siehe `CLAUDE.md`). Bitgleich;
  Gegenprobe rot.

Ursprünglicher Auftrag dieser Phase:

- Abschnitt im Handbuch (englisch) unter „How a process runs: phases", die
  Einstellung unter „Settings", ein Absatz in `architecture.md`.
- `CLAUDE.md`: Stand, die Ausnahme von der Zwei-Zugriffe-Regel, die neuen
  Tabellen unter „Altlasten in der Datenbank" als *nicht* betroffen.
- Bild für `gui/screenshots.py` (Ladedialog).
- **Abnahme:** ein Prozess aus Projekt 716 wird als Vorlage gespeichert, in
  einem neuen Projekt desselben Modells geladen und gerechnet; der Lauf ist
  bitgleich zum Lauf mit denselben, von Hand angelegten Phasen.

---

## 7. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Ersetzen entfernt eine Phase, die der Anwender noch braucht | Nur nicht begonnene Phasen; Namen in der zweiten Bestätigung; Logzeile |
| Eine Vorlage nennt einen Parameter, den es nicht mehr gibt (z. B. nach `remove_dead_parameters`) | `ON DELETE CASCADE` entfernt die Zeile; `check_template` vergleicht zusätzlich mit dem Modell und meldet, statt still zu laden |
| Vorlagen gehen mit dem Modell verloren | E7: die Zahl steht im Löschdialog |
| Studierende schalten die Einstellung selbst ein | Bekannt und akzeptiert (E4): eine Kursvorgabe, keine Sicherung |
| Schreiben während einer Sitzung stört das Speichern des Projekts | Eigene Tabellen, eigene kurze Transaktion, nur aus einem Dialog |
| Die Datenbank eines Anwenders kennt die Tabellen nicht | `ensure_template_tables` beim Start, idempotent, getestet an einer Datenbank von vorher |
| Der Plan behauptet etwas über den Automaten, das nicht stimmt | Phase 0 liest es nach; Phase 2 prüft am Lauf |

---

## 8. Startprompt für Claude Code

```
Wir bauen Prozessvorlagen nach python/Projektplan_Prozessvorlagen.md, heute
Phase <N>. Lies zuerst python/CLAUDE.md und den Plan. Halte dich an die Regeln
dort: jede Datenbankänderung in einer Transaktion über get_connection, kein
PRAGMA foreign_keys = OFF, jeder Schreibzugriff auf die Phasen durch
runner.editing(), Kommentare englisch. Arbeite nur an dieser Phase, lass pytest
laufen, bevor du weitermachst, und trage am Ende Stand und neue Regeln in
CLAUDE.md ein. Behaupte nichts über den Code, was du nicht nachgelesen oder
gemessen hast.
```
