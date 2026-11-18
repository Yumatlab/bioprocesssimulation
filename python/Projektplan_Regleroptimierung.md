# Projektplan: Werkzeug zur Reglereinstellung

Stand der Grundlage: Arbeitsverzeichnis vom 18.11.2026. Aussagen über den Code
nennen Funktionen; Zahlen sind gemessen und mit ihrer Messung angegeben.

**Fassung 2 (18.11.2026), mit dem Anwender abgestimmt:** zweistufig — erst ein
begründeter **Vorschlag** aus einem Sprungversuch und einer Einstellregel
(SIMC), dann **Prüfen und Feinjustieren** mit log10-Schiebern an einer
Vorausrechnung. Abschnitt K7 sagt warum.

**Wunsch des Anwenders:** Die Reglerparameter passen bei Pichia und bei
geändertem Δt nicht mehr. Ein Werkzeug soll mit drei Schiebern (P, I, D,
logarithmisch) die Verstärkungen **eines** Reglers im laufenden Prozess oder in
einer Simulation verstellen und die Wirkung in einem kleinen Plot zeigen, damit
man die passenden Werte findet.

---

## 1. Kritische Einschätzung

Der Wunsch ist berechtigt und das Werkzeug machbar. Sechs Punkte ändern aber,
*was* gebaut werden sollte.

### K1 · Am laufenden Prozess lässt sich nicht vergleichen

Ein Schieber, der direkt in den laufenden Prozess schreibt, zeigt die Wirkung
nur einmal und nur vorwärts. Der Zustand von vorher kommt nicht wieder: Die
Biomasse ist gewachsen, das Substrat verbraucht, der I-Anteil aufgelaufen. Zwei
Einstellungen nacheinander auszuprobieren heißt, sie an zwei verschiedenen
Prozessen zu messen. Und jeder Fehlgriff landet im echten Lauf.

**Stattdessen: eine Vorausrechnung ab einem Schnappschuss.** Der aktuelle
Zustand wird kopiert und mit den alten und den neuen Verstärkungen je einmal
vorausgerechnet, über dieselbe Zeit und mit identischem Start. Beide Verläufe
liegen übereinander im Plot. Der echte Prozess läuft unberührt weiter oder
steht. Erst **„Übernehmen"** schreibt die Werte in den Prozess, über
`runner.editing()` und mit Logeintrag, wie jede andere Parameteränderung.

Gemessen, dass das trägt: Den Zustand eines 4-h-Laufs zu kopieren kostet unter
2 ms. Die Kopie berührt das Original nicht.

| Vorausrechnung, 1 h | Δt = 2 s | Δt = 10 s |
|---|---|---|
| E. coli (716) | 0,58 s | 0,15 s |
| Pichia (519) | 0,95 s | 0,20 s |

Neu gerechnet wird beim **Loslassen** eines Schiebers, nicht bei jedem Pixel,
und in einem Hintergrund-Thread. Eine Rechnung bei jedem Pixel Schieberweg wäre
bei 2 s zu langsam.

### K2 · Δt ist kein Einheitenfehler, sondern Abtastung

Nachgelesen in beiden Modellen: Die Regler rechnen dimensionsrichtig in Stunden
(I-Anteil `× dt`, D-Anteil `/ dt`). Es gibt keinen Fehler wie damals bei
`meas_transfer_function`. Dass Verstärkungen bei anderem Δt versagen, hat drei
Ursachen:

- Jeder Regler reagiert einmal pro Schritt und arbeitet mit dem Messwert des
  Vorschritts. Pichias D-Anteil liest sogar zwei Schritte zurück. Ein größeres
  Δt ist mehr Totzeit im Kreis.
- Das Fehlerfilter `pt1_filter` hat eine feste Zeitkonstante von 0,001 h =
  3,6 s. Bei 2 s glättet es, bei 60 s wirkt es praktisch nicht mehr.
- Der Prozess selbst (pO2 bei hohem kLa) ist schneller als ein grobes Δt.

Schon gemessen: pO2-RMS 9,1 bei 2 s, 121 bei 60 s, mit denselben
Verstärkungen.

**Folge: Optimale Verstärkungen gelten nur für das Δt, bei dem sie gefunden
wurden.** Das Werkzeug rechnet deshalb immer mit dem Δt des Projekts und zeigt
es an. Wer die Werte für ein anderes Δt sucht, stellt Δt vorher um.

### K3 · Bei Pichia gibt es am pO2-Kreis nichts zu finden

Schon gemessen und in `CLAUDE.md` festgehalten: Der pO2-Kreis von Pichia ist
**versorgungsbegrenzt**. Der Rührer sitzt in 100 % der Schritte an einem
Anschlag. Acht Verstärkungssätze über drei Größenordnungen liefern denselben
RMS von 29,6. Ein Werkzeug, das dort Schieber anbietet, lässt jemanden eine
Stunde vergeblich schieben.

**Das Werkzeug muss es sagen:** Es zeigt den Anteil der Zeit, in der das
Stellglied am Anschlag steht. Über etwa 80 % erscheint ein Hinweis: „Der Regler
kann den Sollwert nicht erreichen; Verstärkungen ändern daran nichts. Ändere die
Begasung oder den Sollwert." Für Pichia ist das die wichtigste Auskunft des
ganzen Werkzeugs.

Dazu: **Projekt 519 trägt noch die falschen Feed-Verstärkungen** für Reservoir 2
(−2/−15/−0,009). Die Korrektur (1/5/0,005) steht nur in den Modellvorgaben,
weil bestehende Projekte ihre Werte behalten. Das Werkzeug wird das sichtbar
machen; die Ursache ist dort schon bekannt.

### K4 · log10-Schieber: Vorzeichen und Null

Gemessene Spannweite der heutigen Verstärkungen: **0,0005** (`KD_gasmix`) bis
**10 000** (`KP_pH`), also sieben Zehnerpotenzen. Ein logarithmischer Schieber
ist dafür richtig, kann aber zwei Dinge nicht darstellen:

- **Negative Werte.** Die drei pO2-Feed-Verstärkungen sind absichtlich negativ
  (viel pO2 heißt: es darf mehr gefüttert werden). Das Vorzeichen wird nicht
  geschoben, sondern steht fest neben dem Schieber; der Schieber stellt den
  Betrag.
- **Null.** Ein abgeschalteter Anteil (KD = 0) hat keinen Logarithmus. Jeder
  Anteil bekommt ein Kästchen „aus".

Der Bereich jedes Schiebers ist der aktuelle Wert ± 3 Zehnerpotenzen, in
Schritten von 0,05 Dekaden (≈ 12 %). Daneben steht ein Zahlenfeld für den
genauen Wert.

### K5 · „Jeder Regler einzeln" — die Regler sind verschieden gebaut

| Kreis | Verstärkungen | Besonderheit |
|---|---|---|
| pH | nur `KP_pH` (10 000) | P-Regler mit Totband ± 0,1, praktisch Zweipunkt; kein I, kein D |
| Temperatur | `KP_temp1`, `KI_temp1` (Master) | Kaskade: der Folgeregler hat `KP_temp2c`/`KP_temp2h` (Split Range), die in `CONTROL_LOOPS` **nicht** vorkommen; ein D-Anteil existiert nicht |
| pO2 (4 Regler) | je KP/KI/KD | nur der Regler des aktuellen `Mode_pO2` wirkt |
| Feed (Closed Loop) | `KP/KI/KD_feedR{n}` | je Reservoir; nur bei `Mode_feed` = 1 |
| Füllgewicht | `KP/KI/KD_LW` | nur bei `Mode_harvest` = 1 |

Also: drei Schieber nur, wo es drei Anteile gibt. Ein Regler, der im aktuellen
Modus nicht wirkt, wird grau mit Begründung gezeigt, statt Wirkung
vorzutäuschen. Der Modus wird im Werkzeug **nicht** umgeschaltet; das wäre ein
anderer Prozess.

### K6 · „Optimal" braucht ein Maß und ein Szenario

Sitzt der Prozess ruhig auf dem Sollwert, zeigt jede Einstellung dieselbe flache
Linie. Damit man etwas sieht, braucht es eine Anregung:

- **„Weiter wie bisher"**: Störungen aus dem Prozess selbst (Wachstum, Feed,
  Phasenwechsel). Das ist das, was im Kurs zählt.
- **„Sollwertsprung"**: zu Beginn der Vorausrechnung wird der Sollwert um einen
  einstellbaren Betrag verschoben (z. B. pO2 30 → 40 %). Das ist die klassische
  Sprungantwort.

Als Maß stehen nebeneinander, alt gegen neu: integrierte Abweichung (IAE),
größtes Überschwingen, Zeit bis zum Toleranzband, Stellweg und Zeit am Anschlag.
Ein einziges Maß „optimal" gibt es nicht: Weniger Abweichung kostet Stellweg.
Das Werkzeug zeigt beides, die Entscheidung trifft der Mensch. Eine
automatische Suche ist eine mögliche spätere Phase (Abschnitt 4, Phase 7) und
hätte genau das Problem, dass sie auf ein Szenario hin optimiert.

### K7 · Probieren von Hand ist nicht die beste Art zu finden

In der Praxis werden Regler nicht von null aus durch Probieren eingestellt,
sondern ausgehend von einem berechneten Startwert:

- **Sprungversuch:** die Stellgröße wird im offenen Kreis um einen kleinen
  Betrag verstellt (z. B. Rührer +10 %), aus der Antwort der Regelgröße folgen
  drei Kennwerte — Streckenverstärkung *K*, Zeitkonstante *T*, Totzeit *L*.
- **Einstellregel:** heute empfohlen sind die SIMC-Regeln (Skogestad) bzw.
  Lambda-Tuning: man gibt vor, wie schnell der geschlossene Kreis sein soll
  (τc), daraus folgen KP und die Nachstellzeit. Ziegler-Nichols gilt als zu
  aggressiv. Ein Knopf statt drei.

Für diese Anwendung passt das besonders gut:

- **Δt wird Teil der Regel.** Abtastung wirkt wie zusätzliche Totzeit, nach
  der üblichen Faustregel etwa Δt/2, dazu das Fehlerfilter (3,6 s). Für dieses
  Modell **nicht nachgemessen** — Phase 0 prüft es. Trägt die Faustregel, liefert
  das Werkzeug für jedes Δt eigene Startwerte, statt bei 2 s gefundene Werte
  bei 10 s weiterzuverwenden (K2).
- **Der Sprungversuch kostet nichts:** er läuft auf derselben Kopie wie die
  Vorausrechnung (K1), der echte Prozess bleibt unberührt.
- **Er zeigt Unerreichbares vorher:** reicht die Streckenverstärkung über den
  ganzen Stellbereich nicht bis zum Sollwert, gibt es keinen Vorschlag, sondern
  den Hinweis aus K3.

Grenzen, die bleiben: Der Prozess ändert sich (Biomasse, Sauerstoffverbrauch,
kLa mit der Drehzahl) — ein Satz passt zu einem Arbeitspunkt. Ausweg ohne
neuen Code: Verstärkungen je Prozessphase über „Update Parameter Set".
Strukturfehler (Anschlag, Vorzeichen, Anti-Windup — siehe `FEHLER.md`) behebt
keine Einstellregel. **Und:** die Regler rechnen mit normierten Größen
(Fehler / 99, Stellgröße 0…1, Gasmischung / (1 − xOAIR)); *K* muss in genau
diesen Einheiten bestimmt werden, sonst stimmen die Vorschläge um
Größenordnungen nicht. Die Normierung je Kreis gehört deshalb in den
Reglerkatalog.

Die Schieber bleiben: zum Prüfen, zum Feinjustieren und im Kurs zum
Verstehen, was P, I und D bewirken.

### Weitere Punkte

- **Phasen gehören in die Vorausrechnung.** Startet in der Vorausrechnung eine
  Phase (Feed, Update Parameter Set), ändert sie Sollwerte und Stellgrößen. Ohne
  den Phasenautomaten in der Kopie wiche die Vorausrechnung vom echten Lauf ab.
  Er wird mitkopiert.
- **Die Kreise beeinflussen sich.** Die Vorausrechnung ist das ganze Modell,
  das ist gut so. Es heißt aber: Ein neuer pO2-Regler ändert auch Temperatur
  und pH ein wenig. Das Werkzeug zeigt den gewählten Kreis, nicht alle.
- **Anti-Windup** verändert das Verhalten stark (Pichia: pO2 108,7 % gegen
  78,3 %). Der Schalter des Kreises gehört neben die Schieber.
- **Wohin übernommen wird:** in das Projekt (`p`, wird mit dem Projekt
  gespeichert). Optional, getrennt und mit Rückfrage: als Vorgabe ins Modell,
  damit neue Projekte die Werte bekommen. Bestehende Projekte behalten ihre
  Werte, wie immer.
- **Lehre:** Ob Studierende das Werkzeug sehen, sollte eine Einstellung sein,
  wie bei den Prozessvorlagen.

---

## 2. Entscheidungen

Empfehlungen markiert. **Vor Phase 1 bestätigen.**

| # | Frage | Empfehlung |
|---|---|---|
| D1 | Ausprobieren am echten Prozess oder an einer Vorausrechnung? | **Vorausrechnung ab Schnappschuss**, alt und neu überlagert; „Übernehmen" schreibt in den Prozess (K1) |
| D2 | Zeithorizont | wählbar 15 min / 30 min / 1 h / 2 h, Vorgabe 30 min |
| D3 | Szenario | „Weiter wie bisher" und „Sollwertsprung" (K6) |
| D4 | Welche Verstärkungen | die des gewählten Kreises; zusätzlich die Folgeregler der Temperaturkaskade (`KP_temp2c`, `KP_temp2h`) und die Feed-Regler je Reservoir (K5) |
| D5 | Schieber | Betrag log10, ± 3 Dekaden um den aktuellen Wert, 0,05 Dekaden; Vorzeichen fest daneben; „aus" je Anteil; Zahlenfeld (K4) |
| D6 | Anti-Windup-Schalter im Werkzeug | **ja**, je Kreis wie im Dialog der Verstärkungen |
| D7 | Übernehmen | ins Projekt; „Als Modellvorgabe speichern" als eigener Schritt mit Rückfrage |
| D8 | Einstellung zum Ausblenden | ja, Vorgabe an |
| D9 | Wo das Werkzeug aufgeht | eigenes, nicht-modales Fenster; Schaltfläche „Tune…" je Kreis im Tab Controllers und Menü „Settings → Tune controllers…" |
| D10 | Vorschlag | **Sprungversuch + SIMC** (K7), mit τc als einzigem Knopf (Vorgabe τc = L, „straff") und Δt in der Totzeit; der Vorschlag füllt die Schieber, übernommen wird nie automatisch |
| D11 | Automatische Suche (Optimierung) | **nicht** in dieser Fassung; später möglich (Phase 7) |

---

## 3. Architektur

| Schicht | Datei (neu) | Inhalt |
|---|---|---|
| Kern, ohne Qt | `core/forecast.py` | `fork(state, automaton)` (tiefe Kopien); `forecast(state, model, automaton, hours, gains, scenario) → Forecast(t, setpoint, measurement, outputs, metrics)`; `metrics(...)` |
| Katalog, ohne Qt | `control/tuning.py` | `TUNABLE_LOOPS`: je Kreis Name, Modusbedingung, Sollwert, Messgröße, Stellgröße(n) mit Anschlägen, **Normierung von Fehler und Stellgröße**, Verstärkungen mit festem Vorzeichen, Anti-Windup-Flag; `to_slider`/`from_slider` (log10-Abbildung) |
| Identifikation, ohne Qt | `control/identification.py` | `step_test(fork, loop, size)` (offener Kreis auf der Kopie); `fit_fopdt(t, y, u) → K, T, L, Güte`; `simc(K, T, L, dt, tau_c) → KP, KI, KD` in den Einheiten des Codes (`KI = KP/τI` in 1/h) |
| Oberfläche | `gui/windows/tuning.py` | Fenster mit Kreiswahl, Schiebern, Szenario, Horizont, zwei kleinen Plots (Mess-/Sollwert; Stellgröße), Kennzahlen alt/neu, Hinweis „am Anschlag", Schaltflächen „Übernehmen", „Zurücksetzen" |
| Rechnen im Hintergrund | in `gui/windows/tuning.py` | ein `QThread`, der die jeweils letzte Anfrage rechnet und ältere verwirft |

Regeln, die durchgehen:

- **Die Vorausrechnung schreibt nie in den echten Zustand.** Ein Test hält das
  bitgenau fest.
- **Mit unveränderten Verstärkungen ist die Vorausrechnung der echte Lauf.**
  Kopie mit denselben Werten rechnen und den Originalprozess dieselbe Zeit
  weiterlaufen lassen: bitgleich. Das ist der Prüfstein des Ganzen. Fällt er,
  zeigt das Werkzeug etwas, das nicht passieren würde.
- **Übernehmen ist ein gewöhnlicher Schreibzugriff** (`_set_parameter`), also
  geschützt, protokolliert, mit dem Projekt gespeichert.
- **Kein Regler wird umgebaut.** Das Werkzeug stellt Zahlen ein, die es schon
  gibt.

---

## 4. Phasen

Eine Sitzung je Phase, nach jeder die ganze Suite, dann `CLAUDE.md`.

### Phase 0 — Festlegen und messen (½ Sitzung)

- Entscheidungen D1–D11 bestätigen (D10 ist mit Fassung 2 entschieden).
- **Trägt das Modell erster Ordnung mit Totzeit?** Für jeden Kreis einen
  Sprung im offenen Kreis auf der Kopie fahren und die Antwort ansehen: passt
  *K*, *T*, *L*, oder schwingt/integriert die Strecke (dann andere Regel)?
- **Trägt die Faustregel Δt/2?** Dieselbe Sprungantwort bei Δt = 2, 5, 10 s:
  wächst die scheinbare Totzeit um etwa Δt/2?
- **Ausgangslage messen**, damit später klar ist, was das Werkzeug gebracht hat:
  für jeden Kreis und beide Organismen die heutigen Kennzahlen bei Δt = 2, 5,
  10 s (Szenario „weiter wie bisher", 2 h). Welche Kreise sind
  versorgungsbegrenzt?
- Nachprüfen, dass `copy.deepcopy` des `PhaseAutomaton` samt Detektor
  vollständig ist.
- Klären, ob die heutigen Pichia-Projekte die alten Feed-Verstärkungen tragen.

### Phase 1 — Vorausrechnung, ohne Oberfläche (1 Sitzung)

Tests:
- `test_a_fork_leaves_the_original_untouched` (bitgenau, auch `a` und Phasen)
- `test_a_forecast_with_the_same_gains_is_the_real_run` (der Prüfstein)
- `test_phases_start_in_the_forecast_as_they_would_in_the_run`
- `test_a_setpoint_step_is_applied_at_the_start_of_the_forecast`
- `test_the_metrics_on_known_signals` (IAE, Überschwingen, Ausregelzeit,
  Stellweg, Anschlagzeit an konstruierten Reihen)
- `test_a_supply_limited_loop_is_reported` (Pichia 519, pO2: Anschlag > 80 %)

### Phase 2 — Reglerkatalog und Schieberabbildung (½ Sitzung)

Tests:
- `test_every_gain_in_the_catalogue_exists_in_both_models` (gegen die Quelle,
  wie bei den Anti-Windup-Schaltern)
- `test_the_sign_of_a_gain_is_kept` (`KP_feedpO2` bleibt negativ)
- `test_the_log_slider_round_trips_within_half_a_step`
- `test_zero_is_off_not_a_slider_position`
- `test_only_the_loop_of_the_current_mode_is_active`
- `test_each_loop_knows_how_its_error_and_output_are_normalised` (gegen die Modellquelle)

### Phase 3 — Sprungversuch und Einstellregel (1 Sitzung)

- `control/identification.py`: Sprungversuch auf der Kopie, Anpassung an
  *K*, *T*, *L*, SIMC mit Δt in der Totzeit, Prüfung „erreichbar".

Tests:
- `test_a_known_first_order_plant_is_identified` (konstruierte Strecke mit
  bekannten K, T, L: auf wenige Prozent getroffen)
- `test_the_step_test_leaves_the_process_untouched`
- `test_simc_gives_the_textbook_numbers` (Beispiel aus Skogestad 2003)
- `test_the_suggestion_is_in_the_units_of_the_code` (Normierung je Kreis)
- `test_a_larger_dt_gives_gentler_gains` (mehr Totzeit → kleineres KP)
- `test_a_supply_limited_loop_gets_no_suggestion` (Pichia pO2)
- **Messung, kein Test:** die SIMC-Vorschläge für die E.-coli-Kreise bei 2 s
  gegen die heutigen, gemessenen Werte (`tools/tune_po2.py`) — liegen sie in
  derselben Größenordnung? Wenn nicht: warum.

### Phase 4 — Werkzeugfenster (1–2 Sitzungen)

- Fenster, Schieber, Plots, Kennzahlen, Hintergrund-Thread, Rechnung beim
  Loslassen; Schaltfläche **„Vorschlag berechnen"** (Phase 2) mit τc-Regler,
  die die Schieber füllt; Kennwerte K, T, L und Güte der Anpassung sichtbar.

Tests:
- `test_moving_a_slider_recomputes_once_on_release`
- `test_an_older_request_is_dropped_for_a_newer_one`
- `test_the_old_curve_and_the_new_curve_start_at_the_same_point`
- `test_an_inactive_loop_is_shown_grey_with_its_reason`
- `test_the_window_never_writes_into_the_process` (bis zum Übernehmen)

### Phase 5 — Übernehmen und Einstellung (1 Sitzung)

- „Übernehmen" über `_set_parameter`, „Als Modellvorgabe speichern" über
  `save_model_parameters` mit Rückfrage, Einstellung zum Ausblenden.

Tests:
- `test_applying_is_the_same_as_setting_the_gains_by_hand` (bitgleicher Lauf)
- `test_applying_is_logged_as_a_parameter_change`
- `test_storing_as_model_default_reaches_new_projects_not_old_ones`
- `test_switched_off_there_is_no_way_to_the_tool`

### Phase 6 — Einsatz, Messung, Dokumentation (1 Sitzung)

- Mit dem Werkzeug die Pichia-Kreise bei Δt = 2, 5 und 10 s einstellen
  (Vorschlag, dann Feinjustieren) und das Ergebnis messen und festhalten, wie
  bei `tools/tune_pichia.py`: was besser wurde, was nicht ging und warum, und
  wie weit der SIMC-Vorschlag schon trug.
- Handbuch (englisch), `architecture.md`, `CLAUDE.md`, Bild für
  `gui/screenshots.py`.

### Phase 7 — optional, später: Optimierung per Suche

- Koordinatensuche auf dem log10-Raster, Ziel IAE plus Strafterm für Stellweg
  und Anschlagzeit; das Ergebnis erscheint als **Vorschlag** in den Schiebern,
  nie automatisch übernommen. Erst angehen, wenn Phase 5 zeigt, dass das
  Ausprobieren von Hand nicht reicht.

---

## 5. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Die Vorausrechnung zeigt etwas anderes als der echte Lauf | Prüfsteintest (Phase 1): gleiche Verstärkungen → bitgleich |
| Werte, die für ein Szenario gut sind, sind im anderen schlecht | zwei Szenarien, Kennzahlen nebeneinander, Entscheidung beim Menschen |
| Optimiert für ein Δt, benutzt mit einem anderen | Δt steht im Fenster; Doku sagt, dass Verstärkungen Δt-gebunden sind (K2) |
| Stundenlanges Schieben an einem versorgungsbegrenzten Kreis | Hinweis bei hoher Anschlagzeit (K3) |
| Zu langsam zum Arbeiten | Rechnen beim Loslassen, Hintergrund-Thread, Horizont wählbar; gemessen 0,15–0,95 s je Stunde |
| Ein Fehlgriff landet im echten Prozess | nichts wird geschrieben bis „Übernehmen"; Übernehmen ist protokolliert |
| Der Vorschlag stimmt um Größenordnungen nicht | Normierung je Kreis im Katalog; Test in den Einheiten des Codes; Vergleich mit den gemessenen E.-coli-Werten (Phase 2) |
| Die Strecke ist nicht erster Ordnung (Schwingen, integrierend) | Phase 0 prüft es je Kreis; Güte der Anpassung wird angezeigt, bei schlechter Güte kein Vorschlag |

---

## 6. Startprompt für Claude Code

```
Wir bauen das Werkzeug zur Reglereinstellung nach
python/Projektplan_Regleroptimierung.md, heute Phase <N>. Lies zuerst
python/CLAUDE.md und den Plan. Regeln: die Vorausrechnung schreibt nie in den
echten Zustand; mit unveränderten Verstärkungen muss sie bitgleich zum echten
Lauf sein; Übernehmen geht durch runner.editing(); kein Regler wird umgebaut;
Kommentare englisch. Arbeite nur an dieser Phase, lass pytest laufen, bevor du
weitermachst, und trage am Ende Stand und neue Regeln in CLAUDE.md ein.
Behaupte nichts über die Regler, was du nicht nachgelesen oder gemessen hast.
```
