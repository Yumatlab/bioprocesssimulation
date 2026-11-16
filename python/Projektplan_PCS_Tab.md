# Projektplan: PCS-Tab (Prozessleitansicht) für die Python-Anwendung

Stand der Grundlage: Repository `Yumatlab/bioprocesssimulation`, Branch `main`,
Commit `5347fe2` vom 17.09.2026 (am 14.11.2026 erneut abgerufen, unverändert).
Alle Aussagen über den Code beziehen sich auf diesen Stand. Lokale, nicht
gepushte Änderungen sind darin nicht enthalten.

Ziel: ein neuer Tab im Kontrollfenster, der die Anlage als R&I-Fließbild zeigt —
Kessel in der Mitte, Ventile, Pumpen und Vorlagen darum herum. Ventile sind
bedienbar und schreiben Parameter (0 ↔ 1), Leitungen zeigen, wo gerade etwas
fließt, Vorlagen und Kessel zeigen ihren Füllstand relativ zum Maximum. Ein
Alarmkonzept wird jetzt mitgedacht und später umgesetzt.

---

## 1. Was im Code schon da ist — und was daraus folgt

### 1.1 Einhängepunkte

| Was | Wo | Bedeutung für den PCS-Tab |
|---|---|---|
| Tabs werden in `self.pages` gebaut und über `settings.shows(title)` eingehängt | `gui/windows/control_app.py` | PCS wird eine weitere Seite; ein abgeschalteter Tab wird trotzdem gebaut |
| `HIDEABLE_TABS` | `gui/settings.py` | „PCS" ergänzen, dann erscheint er von selbst im Einstellungsdialog |
| `refresh()` zeichnet nur den sichtbaren Tab neu | `control_app.py` | ein weiterer `elif`-Zweig für `self.pcs_view` |
| `load_panels()` liest Sollwerte, Modi, Schalter aus `p` | `control_app.py` | muss auch `pcs_view.load(state)` rufen — und umgekehrt nach jedem Ventilklick laufen |
| `_set_parameter(name, value)` schreibt durch `runner.editing()` und protokolliert | `control_app.py` | der eine Schreibweg; der PCS-Tab bekommt keinen eigenen |
| Layout als Textdatei mit Benutzerkopie neben der Datenbank und Ersatzanordnung | `gui/panel_layout.py`, `resources/layouts/` | dieselbe Abmachung für die Anordnung des Fließbilds; `build/specs.py` liefert den Ordner `layouts` bereits mit |
| Selbst gezeichnete Bedienelemente, Zustand immer in einem Qt-Element | `gui/widgets/indicators.py` (`SlideSwitch`, `StatusLamp`) | Ventile werden `QAbstractButton`, keine reinen Zeichnungen |
| `matlab/RI.drawio` | enthält ein R&I-Schema als eingebettetes Bild | Vorlage für die Topologie (Kessel, Pumpen FR1/FT1/FT2/FAF/FH, Vorlagen, Begasungsstrecke AIR/O2/N2). Es ist ein Bild, keine Struktur — gezeichnet wird neu, mit eigenen Symbolen |

### 1.2 Welche Flags es gibt und wann das Modell sie liest

> **Nach Phase 0 gilt die Elementliste in `python/CLAUDE.md`, Abschnitt
> „Der PCS-Tab"** — mit Zeilennummern für beide Modelle. Korrigiert gegenüber
> dieser Tabelle: Ernte wirkt bei `Mode_harvest != 1`; Luft und O2 brauchen
> zusätzlich `f_aeration == 1`; `f_aeration` wirkt in `Mode_pO2` 2/3 nur auf
> N2/CO2; Feed hängt zusätzlich an `a.switch_exp`/`a.switch_pulse`.

Geprüft im E.-coli-Modell (`organisms/escherichia_coli/model.py`). Das ist der
wichtigste Befund für die Bedienung: **ein Flag wirkt nur in bestimmten Modi.**
Im Automatikbetrieb setzt der Regler den Fluss selbst und liest das Flag nicht.

| Element im Fließbild | schreibt | wirkt, wenn | Fluss / Rückmeldung |
|---|---|---|---|
| Säureventil | `f_acid` | `Mode_pH == 0` | `v.FT1` |
| Laugenventil | `f_alkali` | `Mode_pH == 0` | `v.FT2` |
| Feedventil Reservoir n | `f_feed`, `R_feed` wählt das Reservoir | in beiden Feed-Modi; nicht während Exponential-/Pulsfeed und nicht bei `Mode_pO2 == 4` | `v.FR{n}` |
| Ernteventil | `f_harvest` | `Mode_harvest == 0` | `v.FH` |
| Antischaum | `f_antifoam` | nach der Beimpfung (`a.ToI != 0`) | keine Flussreihe; `v.AAF` |
| Begasung gesamt | `f_aeration` | Hauptschalter; ohne ihn `FnG = 0` | `v.FnG` |
| Luft | `f_air` | `Mode_pO2` nicht 2 oder 3 | `v.FnAIR` |
| Sauerstoff | `f_O2` | `Mode_pO2` nicht 2 oder 3 | `v.FnO2` |
| Stickstoff | `f_N2` | `f_aeration == 1` | `v.FnN2` |
| Kohlendioxid | `f_CO2` | `f_aeration == 1` | `v.FnCO2` |
| Rührermotor | `f_motor` | `Mode_pO2 != 1` | `v.NSt` |
| Kühlwasser | `f_cooling` | `Mode_temp == 0` | `a.mdotC` |
| Heizung | `f_heating` | `Mode_temp == 0` | Automatik: `a.mdotH`; Handbetrieb: Heizleistung wird nicht gespeichert |
| Beimpfung | `f_Inoc` | — | `a.inoc_occ` (Lampe und Knopf existieren schon) |

Dazu drei Befunde, die den Plan beeinflussen:

- **`f_FR1`, `f_FR2`, `f_FR3` stehen in `parameterTab`, aber kein Modell liest
  sie** (Suche über `organisms/`, `core/`, `control/` ohne Treffer). Sie werden
  nicht als Ventil angeboten — ein Bedienelement, das nichts bewirkt, ist
  schlechter als keines.
- **Kühlung und Heizung liegen in `a`, nicht in `v`.** `a` wird nicht
  gespeichert; nach dem Wiederöffnen eines Projekts stehen beide bis zum ersten
  Schritt auf 0.
- **Für Antischaum- und Erntegefäß gibt es keine Volumenreihe.** `VH` ist ein
  Parameter in m³ und keine Zeitreihe; was er bedeutet, habe ich nicht geprüft.
  Diese beiden Gefäße bekommen zunächst keinen Füllstand.

Für Pichia gilt dieselbe Tabelle mit zwei Reservoirs (`v.FR2`, `v.VR2`) — in
Phase 0 gegengelesen.

### 1.3 Füllstände

| Gefäß | Ist | Bezug (100 %) | Bemerkung |
|---|---|---|---|
| Rührkessel | `v.VL` | `p.VLmax` | zusätzliche Marke bei `p.VLmin` |
| Reservoir n | `v.VR{n}` | `p.VR{n}0` | es gibt keinen Parameter für das Fassungsvermögen; das Anfangsvolumen ist der Bezug |
| Säurevorlage | `v.VT1` | `p.VT10` | |
| Laugenvorlage | `v.VT2` | `p.VT20` | |

Eine Begrenzung für ein leerlaufendes Reservoir habe ich im Modell nicht
gefunden: das Volumen wird linear integriert. Das ist ein Kandidat für einen
Alarm (Abschnitt 5), keine Aufgabe für die Anzeige.

### 1.4 Alarmähnliche Zustände, die es schon gibt

`a.VolumeFlag` (`VL >= VLmax`), `a.VLflag`, `a.temperature_exceeded`
(`thetaL > 100`), `a.feed_limit_hit` (Exponentialfeed erreicht `FR1max`),
`a.pH_negative`. In `gui/` liest sie derzeit niemand.

---

## 2. Architektur

### 2.1 Drei Lagen, wie bei den Control Options

```
gui/pcs_specs.py              what exists and what it is wired to   (Python, wiring, no Qt)
resources/layouts/pcs.yaml    where it sits on the canvas           (text file, taste)
gui/widgets/pcs_view.py       the widgets and the canvas            (drawing)
gui/pcs_layout.py             reads pcs.yaml, validates, falls back
```

- **Verdrahtung ist Code, Anordnung ist Text.** Welches Ventil welchen Parameter
  schreibt, entscheidet über das Ergebnis eines Laufs und gehört in eine
  geprüfte Spezifikation. Wo das Ventil sitzt, ist Geschmack und gehört in
  `pcs.yaml` — mit Benutzerkopie neben der Datenbank und Ersatzanordnung, wenn
  die Datei kaputt ist. Genau die Trennung von `panel_specs.py` und
  `control_options.yaml`.
- **Die Modusabhängigkeit hat eine Quelle.** Für `f_acid`, `f_alkali`,
  `f_cooling`, `f_heating`, `f_harvest`, `f_feed` steht sie schon in den
  `SwitchSpec`s der Panels. Die Ventilspezifikation liest sie von dort, statt
  sie ein zweites Mal aufzuschreiben. Nur die Flags ohne Panelschalter
  (`f_aeration`, `f_air`, `f_O2`, `f_N2`, `f_CO2`, `f_motor`, `f_antifoam`)
  bekommen ihre Bedingung in `pcs_specs.py`.

Skizze der Spezifikation:

```python
@dataclass(frozen=True)
class ValveSpec:
    """One operable element: a flag in p, and when the model reads it."""

    element: str                      # id used by pcs.yaml and by alarms
    parameter: str                    # e.g. "f_acid"; may carry {n}
    label: str
    mode_parameter: str | None = None  # e.g. "Mode_pH"
    live_modes: tuple[int, ...] = ()   # empty: always live
    flow: str | None = None            # series in v that proves the flow


@dataclass(frozen=True)
class TankSpec:
    element: str
    volume: str                       # series in v, e.g. "VR{n}"
    maximum: str                      # parameter in p, e.g. "VR{n}0"
    minimum: str | None = None        # optional mark, e.g. "VLmin"


@dataclass(frozen=True)
class PipeSpec:
    element: str
    source: str                       # element id
    target: str                       # element id
    flow: str                         # series in v, or "a:mdotC" for an auxiliary
    medium: str                       # feed, acid, base, gas, harvest, coolant
```

`{n}` wird wie bei `ControllerView` über die Zahl der Reservoirs des Organismus
aufgelöst. E. coli bekommt ein Reservoir, Pichia zwei.

### 2.2 Das Fließbild: eine Zeichenfläche mit echten Bedienelementen

Empfehlung: **ein `PcsCanvas(QWidget)`**, der Leitungen und Kessel in
`paintEvent` zeichnet, mit Kindwidgets für alles Bedienbare und Ablesbare:

- `ValveButton(QAbstractButton)` — checkbar, selbst gezeichnet (Ventilsymbol),
  Fokus und Tastatur kommen von Qt. `set_state_now()` als Ladeweg ohne Signal,
  wie beim `SlideSwitch`.
- `TankGauge(QWidget)` — Gefäß mit Füllhöhe, darunter „3,2 / 5,0 l · 64 %".
- `VesselWidget(QWidget)` — der Kessel: Füllstand, Marken für `VLmin`/`VLmax`,
  Rührersymbol.

Positionen kommen als normierte Koordinaten (0…1) aus `pcs.yaml` und werden in
`resizeEvent` in Pixel umgerechnet. Das Fließbild skaliert also mit dem Fenster
und erzwingt keine Mindestbreite — die Regel aus dem 1716-px-Fehler.

Warum nicht `QGraphicsScene`: sie wäre für ein frei zoombares Diagramm die
bessere Wahl, bricht aber mit der Projektregel „der Zustand liegt in einem
Qt-Element" und macht Ventile schwerer testbar (`button.click()` gegen
Szenenkoordinaten). Bei rund 30 Elementen bringt sie keinen Vorteil.

Grobe Anordnung (Vorgabe in `pcs.yaml`, änderbar):

```
   AIR ─▷◁─┐                               ┌── exhaust
   O2  ─▷◁─┤                    (M)        │
   N2  ─▷◁─┼─▷◁── aeration ──▶ ┌─────┐ ────┘
   CO2 ─▷◁─┘                   │     │
                               │ VL  │ ─▷◁──▶ harvest
  [AF] ─▷◁────────────────────▶│     │
  [T2] ─▷◁────────────────────▶│     │ ◀─▷◁── cooling water
  [T1] ─▷◁────────────────────▶│     │ ◀─▷◁── heating
  [R1] ─▷◁────────────────────▶└─────┘
  [R2] ─▷◁───────────────────────┘
```

### 2.3 Zwei Aktualisierungswege — Befehl und Rückmeldung

| | Quelle | Wann | Was |
|---|---|---|---|
| `PcsView.load(state)` | `p`, dazu `a.switch_exp`/`a.switch_pulse` | Öffnen, nach Dialog, nach Phasenwechsel, nach jedem Schreibzugriff | Ventilstellung (Befehl), Bedienbarkeit je Modus, gewähltes Reservoir |
| `PcsView.refresh(state)` | `v` und `a` am Index `state.idx` | nach jedem Block, nur wenn der Tab sichtbar ist | Durchfluss je Leitung, Füllstände, Rührer, Zahlenwerte |

Die Trennung ist dieselbe wie bei den Panels und hat denselben Grund: `refresh`
läuft ständig, `load` nur, wenn jemand in `p` geschrieben hat.

**Befehl und Rückmeldung sind zwei Dinge und werden getrennt gezeigt.** Das
Ventil zeigt, was befohlen ist (Flag aus `p`); die Leitung zeigt, ob etwas
fließt (Reihe aus `v`). Im Automatikbetrieb ist das Ventil nicht bedienbar,
sein Tooltip sagt warum („controlled by pH-Control (Auto)"), und sein Symbol
folgt dem Fluss statt dem Flag. Sonst stünde ein „geschlossenes" Ventil an
einer Leitung, durch die der Regler gerade Lauge pumpt.

### 2.4 Schreibweg

```
ValveButton.clicked → PcsView.parameter_changed(name, value)
                    → ControlWindow._set_parameter      (runner.editing(), log)
                    → ControlWindow.load_panels()       (Control Options follow)

ControlPanel.parameter_changed → ControlWindow._set_parameter
                               → PcsView.load(state)    (PCS follows)
```

Kein zweiter Weg nach `p`. Der Logeintrag entsteht damit von selbst als
Parameteränderung, über denselben `note()`-Aufruf wie bei den Panels.

`_set_parameter` ruft `load_panels()` heute nicht, weil bisher nur das Panel
selbst schrieb. Die beiden Richtungen werden deshalb getrennt behandelt: ein
Ventilklick lädt die Panels neu, eine Paneländerung lädt nur das Fließbild.
Ein Panel nach seiner eigenen Änderung neu zu laden, würde das Feld anfassen,
in das gerade jemand tippt — genau das, was `refresh()` mit Absicht vermeidet.

### 2.5 Durchflussanzeige

- Leitung aktiv, wenn der Fluss am aktuellen Index größer als eine kleine
  Schwelle ist (`FLOW_EPSILON`, nicht `> 0`: Reglerausgänge können Rauschen
  tragen).
- Aktiv: kräftige Farbe je Medium, dickere Linie, Pfeilspitze, Zahlenwert mit
  Einheit an der Leitung. Inaktiv: dünn und grau, kein Wert.
- **Nie Farbe allein.** Dicke, Pfeil und Zahl sagen dasselbe; damit bleibt das
  Bild auch bei Rot-Grün-Schwäche und im Schwarzweißdruck lesbar.
- Wandernde Strichelung als Bewegungseindruck ist ein Zusatz für Phase 5. Sie
  braucht einen eigenen Timer, der nur läuft, wenn der Tab sichtbar ist und
  der Prozess rechnet.
- Farben und Linienstärken stehen in `default.qss` bzw. als benannte Konstanten,
  nicht verstreut im Zeichencode.

---

## 3. Phasen

Eine Konversation je Phase, wie bisher. Nach jeder Phase `pytest`, dann
`CLAUDE.md` nachziehen. Die Aufwandsangaben sind Schätzungen in
Claude-Code-Sitzungen, keine Zusagen.

### Phase 0 — Festlegen, nichts bauen (½ Sitzung) — erledigt 14.11.2026

- Elementliste endgültig machen: Tabelle 1.2 gegen das Pichia-Modell gegenlesen,
  `f_aeration` in `Mode_pO2` 2/3 nachlesen.
- Die offenen Entscheidungen aus Abschnitt 6 treffen.
- Abschnitt „Der PCS-Tab" in `python/CLAUDE.md` anlegen: Elementliste, die Regel
  Befehl/Rückmeldung, der Schreibweg.

**Fertig, wenn** jede Zeile der Elementliste einen Leser im Modell hat, der
mit Zeilennummer benannt ist.

### Phase 1 — Bausteine (1 Sitzung) — erledigt 16.11.2026

Neue Datei `gui/widgets/pcs_elements.py`: `ValveButton`, `TankGauge`,
`VesselWidget`, Hilfsfunktion zum Zeichnen einer Leitung (Polylinie, aktiv/inaktiv).
Jeder Baustein einzeln, ohne Fenster und ohne Simulation.

Tests (`tests/test_pcs.py`):
- `test_a_loaded_valve_neither_moves_nor_reports`
- `test_clicking_a_valve_reports_it_once`
- `test_a_disabled_valve_does_not_report`
- `test_a_gauge_clamps_its_level_between_empty_and_full`
- `test_a_gauge_without_a_maximum_shows_no_level`

**Fertig, wenn** die Bausteine in `gui/screenshots.py` einzeln abgebildet werden
können.

### Phase 2 — Spezifikation und Layoutdatei (1 Sitzung) — erledigt 16.11.2026

`gui/pcs_specs.py` (Qt-frei, daher nicht unter `gui/widgets/`), `gui/pcs_layout.py`,
`resources/layouts/pcs.yaml`, Tests in `tests/test_pcs_specs.py`. Stand und
Abweichungen: `python/CLAUDE.md`, „Stand nach Phase 2".

- Spezifikation mit `{n}`-Auflösung über die Reservoirzahl.
- `pcs.yaml`: Position je Element, Stützpunkte je Leitung; Kommentar am
  Dateikopf wie bei `control_options.yaml`.
- `load_pcs_layout()` fängt alles und liefert Ersatzanordnung plus Grund.
- ~~Menüeintrag **Settings → PCS layout…**~~ — nach Phase 3 verschoben.

Tests:
- `test_every_valve_writes_a_flag_the_model_reads` — liest die Flags per Regex
  aus der Modellquelle, wie der Anti-Windup-Test
- `test_every_valve_parameter_is_a_switch_in_parameterTab`
- `test_every_flow_and_volume_name_is_a_series_the_model_writes`
- `test_a_broken_pcs_layout_falls_back_and_says_why`
- `test_the_bundled_pcs_layout_places_every_element`

**Fertig, wenn** ein Tippfehler in `pcs.yaml` den Tab nicht leert.

### Phase 3 — Tab einhängen, nur lesend (1 Sitzung) — erledigt 16.11.2026

`gui/widgets/pcs_view.py` setzt Fläche und Bausteine zusammen. Einhängen in
`control_app.py`: `self.pages["PCS"]`, Zweig in `refresh()`, Aufruf in
`load_panels()`; `HIDEABLE_TABS` ergänzen. Menüeintrag **Settings → PCS
layout…** analog zu „Panel layout…" (aus Phase 2 hierher verschoben).

Zu diesem Zeitpunkt sind alle Ventile abgeschaltet. Das ist Absicht: erst wenn
die Anzeige stimmt, darf sie schreiben.

Tests:
- `test_the_pcs_tab_is_built_even_when_hidden`
- `test_only_the_visible_pcs_tab_is_refreshed`
- `test_a_pipe_is_live_exactly_when_its_flow_is` (Lauf mit `f_feed = 1`, dann 0)
- `test_levels_follow_the_volumes` (Kessel, Reservoir, Säure, Lauge)
- `test_pichia_shows_two_reservoirs_and_coli_one`
- `test_the_pcs_tab_does_not_widen_the_window` (bestehenden Breitentest erweitern)

**Fertig, wenn** ein Lauf von Projekt 716 im PCS-Tab dieselben Zahlen zeigt wie
der Variable Pool.

### Phase 4 — Bedienung (1 Sitzung)

- `parameter_changed` an `_set_parameter` anschließen, danach `load_panels()`;
  Paneländerungen rufen `pcs_view.load(state)` (Abschnitt 2.4).
- Bedienbarkeit je Modus in `PcsView.load(state)`; Tooltip nennt den Regler, der
  das Ventil gerade führt.
- Im Automatikbetrieb folgt das Symbol dem Fluss.
- Reservoirwahl: Klick auf das Feedventil eines anderen Reservoirs setzt
  `R_feed` — oder das bleibt dem Feed-Panel vorbehalten (Entscheidung 6.3).

Tests:
- `test_a_valve_click_goes_through_the_guard`
- `test_a_valve_click_is_logged_as_a_parameter_change`
- `test_a_valve_and_its_panel_switch_never_disagree` (PCS → Panel und Panel → PCS)
- `test_a_phase_that_changes_a_mode_regreys_the_valves`
- `test_an_automatic_valve_shows_the_flow_not_the_flag`

**Fertig, wenn** der E.-coli-Referenzlauf nach der Änderung bitgleich ist. Der
Tab darf nichts rechnen.

### Phase 5 — Feinschliff und Dokumentation (1 Sitzung)

- Messwerte am Kessel (pH, pO2, Temperatur, Drehzahl), Strichanimation,
  Farben in die QSS.
- Bild für `gui/screenshots.py`, Abschnitt in `docs/manual.md` (englisch) und
  ein Absatz in `docs/architecture.md`.
- `tests/test_packaging.py`: `pcs.yaml` ist im Bündel.
- `CLAUDE.md`: Stand und neue Regeln.

### Phase 6 — Alarme (später, 2–3 Sitzungen)

Siehe Abschnitt 5. Die Vorbereitung dafür steckt bereits in den Phasen 1–3
(Abschnitt 5.5).

---

## 4. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Ein Ventil wirkt im aktuellen Modus nicht, sieht aber bedienbar aus | Modusbedingung aus einer Quelle, Test gegen die Modellquelle, Tooltip mit Begründung |
| PCS und Control Options zeigen verschiedene Stellungen | ein Schreibweg, danach immer `load_panels()`; Test in beide Richtungen |
| Der Tab erzwingt eine Fensterbreite | normierte Koordinaten, kleine `minimumSize`, Breitentest nennt den Tab |
| Zeichnen bremst bei hohem Speedfactor | nur der sichtbare Tab; `refresh` setzt Werte und ruft `update()` nur, wenn sich etwas geändert hat |
| Pichia verhält sich anders als E. coli | Phase 0 liest das Modell gegen; nichts wird aus E. coli geschlossen |
| Kühl- und Heizfluss fehlen nach dem Wiederöffnen | Leitung bleibt bis zum ersten Schritt inaktiv; das ist richtig und steht im Handbuch |

---

## 5. Alarmkonzept

### 5.1 Grundsatz

**Ein Alarm meldet, er greift nicht ein.** Die Auswertung liegt außerhalb des
Modells, liest `v`, `a` und `p` und schreibt in keines davon. Damit bleibt jeder
Lauf bitgleich, ob Alarme an sind oder nicht. Verriegelungen (etwa „Feed zu bei
`VL >= VLmax`") wären eine bewusste Abweichung vom Original und eine eigene,
gemessene Entscheidung — nicht Teil dieses Konzepts.

### 5.2 Aufbau

```
control/alarms.py        AlarmSpec, AlarmState, AlarmEngine — no Qt, testable headless
resources/alarms.yaml    limits and texts; user copy next to the database
gui/widgets/alarm_bar.py banner, list, acknowledge button
```

```python
@dataclass(frozen=True)
class AlarmSpec:
    tag: str                 # "VL_HIGH"
    source: str              # "v:VL", "a:temperature_exceeded"
    comparison: str          # ">=", "<=", "=="
    limit: str | float       # parameter name ("VLmax") or a number
    severity: str            # "warning" or "alarm"
    deadband: float = 0.0    # distance the value must retreat before it clears
    delay_steps: int = 0     # steps the condition must hold before it raises
    element: str | None = None  # PCS element to highlight
    message: str = ""
```

`AlarmEngine.evaluate(state) -> list[AlarmEvent]` läuft einmal je Block, vom
Fenster nach `block_completed` gerufen. Totband und Verzögerung verhindern, dass
ein Wert, der auf seiner Grenze sitzt, den Alarm bei jedem Schritt neu auslöst —
laut `CLAUDE.md` liegt der pH im Referenzlauf in 19 % der Schritte näher als
1e-3 an der Schaltschwelle seines Reglers, das Problem ist in diesem Prozess
also real.

### 5.3 Zustände

Vier Zustände nach dem Zustandsmodell der ISA-18.2:

| Zustand | Bedingung erfüllt | quittiert | Anzeige |
|---|---|---|---|
| Normal | nein | — | nichts |
| Unacknowledged | ja | nein | blinkend, Banner |
| Acknowledged | ja | ja | dauerhaft markiert |
| Return to normal, unacknowledged | nein | nein | gedämpft, bis quittiert |

Die Norm kennt weitere Zustände (Latch, Shelved, Suppressed by Design,
Out-of-Service); sie werden hier bewusst weggelassen. Die Zustandsnamen sind aus
einer Herstellerdokumentation zur ISA-18.2 belegt, die Norm selbst habe ich
nicht eingesehen (kostenpflichtig) — vor einer Formulierung im Handbuch, die sich
auf die Norm beruft, bitte dort nachlesen.

### 5.4 Kandidaten

| Tag | Bedingung | Stufe | Quelle heute |
|---|---|---|---|
| `VL_HIGH` | `VL >= VLmax` | Alarm | `a.VolumeFlag` existiert |
| `VL_LOW` | `VL <= VLmin` | Warnung | neu |
| `TEMP_LIMIT` | `thetaL` auf 100 °C begrenzt | Alarm | `a.temperature_exceeded` existiert |
| `RES{n}_LOW` / `RES{n}_EMPTY` | `VR{n}` unter 10 % von `VR{n}0` / `<= 0` | Warnung / Alarm | neu |
| `ACID_LOW`, `BASE_LOW` | `VT1`, `VT2` unter 10 % des Anfangsvolumens | Warnung | neu |
| `FEED_LIMIT` | Exponentialfeed erreicht `FR{n}max` | Warnung | `a.feed_limit_hit` existiert |
| `PH_NUMERIC` | pH-Iteration lief ins Negative | Alarm | `a.pH_negative` existiert |
| `PO2_LOW` | `pO2` unter Grenze, länger als n Schritte | Warnung | neu, Grenze in `alarms.yaml` |
| `PH_DEVIATION`, `TEMP_DEVIATION` | Abstand zum Sollwert über Grenze | Warnung | neu, Grenze in `alarms.yaml` |
| `SIM_FAILED` | `runner.failed` | Alarm | Signal existiert |

Zwei Dinge dazu:

- **`thetaLmingr`/`thetaLmaxgr` und `pHLmingr`/`pHLmaxgr` sind keine
  Alarmgrenzen.** Die Regler normieren ihre Abweichung damit. Sie als Alarmgrenze
  zu benutzen hieße, dass eine Änderung der Alarmgrenze den Regler verstellt.
  Alarmgrenzen stehen deshalb in `alarms.yaml` und nicht in `parameterTab` — die
  Datenbank bekommt keine neue Spalte und keinen neuen Parameter.
- **Die 10 % sind ein Vorschlag**, kein gemessener Wert.

### 5.5 Anzeige und Protokoll

- **Banner** oben im PCS-Tab: jüngster unquittierter Alarm, Zähler, „Acknowledge".
- **Dritte Lampe** in der Menüleiste neben „Process Running" und „Inoculated",
  damit ein Alarm auch aus jedem anderen Tab sichtbar ist.
- **Markierung am Element** im Fließbild: Rahmen plus Symbol, nicht nur Farbe.
- **Log**: neuer Ereignistyp „Alarm" über `note()`, immer sichtbar. Auslösen,
  Quittieren und Verschwinden sind je ein Eintrag. Damit landen Alarme über den
  bestehenden Weg in `logTab` — ohne Schemaänderung.
- **Alarmliste** (Tag, Prozesszeit, Text, Zustand) als aufklappbarer Bereich im
  PCS-Tab.
- Der Alarmzustand wird nicht gespeichert. Nach dem Wiederöffnen wertet die
  Engine den geladenen Stand neu aus; die Historie steht im Log.

### 5.6 Was die PCS-Entwicklung jetzt schon dafür tut

Das ist der Teil, der in den Phasen 1–3 mitgebaut wird, damit Phase 6 nichts
umbauen muss:

1. **Jedes Element hat eine stabile `element`-Id** in Spezifikation und
   `pcs.yaml`. Alarme zeigen über diese Id auf ihr Element.
2. **Jeder Baustein hat `set_alarm(level)`** mit `None`, `"warning"`, `"alarm"`.
   In Phase 1 zeichnet es nur einen Rahmen und wird von niemandem gerufen.
3. **`PcsView` reserviert die Bannerzeile** im Layout (Höhe 0, solange leer).
4. **`PcsView.refresh(state, alarms=())`** nimmt die Alarmliste schon entgegen.
5. **Zustandsfarben als benannte Konstanten** neben `GREY`/`ACCENT` in
   `indicators.py`, damit Ventil, Lampe und Banner dieselben benutzen.

---

## 6. Entscheidungen

Festgelegt in Phase 0 (14.11.2026) jeweils mit der ersten Option, solange
nichts anderes gesagt wird. Punkt 7 kam in Phase 0 dazu.

1. **Tabname**: „PCS" · „Process View" · „Plant".
2. **Position**: direkt nach „Control Options" · am Ende.
3. **Reservoirwahl im Fließbild**: nur Anzeige, gewählt wird im Feed-Panel ·
   Klick auf ein Reservoir setzt `R_feed`.
4. **Antischaum- und Erntegefäß**: ohne Füllstand zeigen · weglassen · Ernte als
   aufsummiertes `FH` in der Oberfläche (wäre eine Rechnung im Tab, die es
   sonst nirgends gibt).
5. **Ventilklick**: sofort schalten · mit Rückfrage. Sofort passt zum
   `SlideSwitch`; jede Stellung steht ohnehin im Log.
6. **Beimpfung**: bleibt der vorhandene Knopf · zusätzlich als Element im Bild.
7. **Begasungsventil in `Mode_pO2` 2/3**: gesperrt, Tooltip nennt den
   pO2-Regler · bedienbar (wirkt dann nur auf N2/CO2 und lässt `FnG[i]` NaN
   werden, siehe CLAUDE.md).
8. **Symbole und Farben** (16.11.2026): Symbolik nach `matlab/RI.drawio`
   (Pumpen, Regelventile, Flaschen, Rührwerk mit Motor), Farben nach ISA-101
   Variante b (grau, gedeckte Medienfarbe nur auf aktiven Leitungen), Ids
   `<x>_pump`; die Ernte als Ventil am Reaktorboden (`harvest_valve`). Abschnitt 2.5 („kräftige Farbe je Medium") ist damit überholt.

---

## 7. Startprompt für Claude Code

```
Wir bauen den PCS-Tab nach python/Projektplan_PCS_Tab.md, heute Phase <N>.
Lies zuerst python/CLAUDE.md und den Plan. Halte dich an die Regeln dort:
jeder Schreibzugriff durch runner.editing(), Zustand in Qt-Elementen,
Verdrahtung in pcs_specs.py, Anordnung in pcs.yaml, Kommentare englisch.
Arbeite nur an dieser Phase, lass pytest laufen, bevor du weitermachst,
und trage am Ende Stand und neue Regeln in CLAUDE.md ein.
Behaupte nichts über das Modell, was du nicht in der Quelle nachgelesen hast.
```
