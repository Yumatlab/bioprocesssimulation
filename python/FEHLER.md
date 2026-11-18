# Fehlerliste

Bekannte Fehler der Anwendung, mit Herkunft, Wirkung und Stand. Ziel des
Anwenders (18.11.2026): **Fehler aus MATLAB werden nicht übernommen und nicht
unbehoben gelassen.** Diese Datei ist die Liste, an der das abgearbeitet wird.

Regeln für Einträge:

- **Eine Nummer bleibt**, auch wenn der Fehler behoben ist; behobene wandern
  in den unteren Teil.
- **Herkunft** ist eine von: *MATLAB* (im Original so, bei der Portierung
  bewusst mitgenommen), *Portierung* (beim Übersetzen entstanden), *Daten* (in
  einer mitgelieferten Datenbank).
- **Wirkung** sagt, ob gemessen oder nur gelesen. Nichts wird behauptet, was
  nicht nachgelesen oder gemessen ist.
- Die ausführliche Begründung steht in `CLAUDE.md`; hier steht, was zu tun ist.

---

## 1. Warum MATLAB-Fehler bisher drin sind, und wie sie herauskommen

E. coli ist gegen einen echten MATLAB-Lauf verifiziert (Schritte 0–903,
`docs/verification_escherichia_coli.md`). Diese Verifikation beweist, dass die
Übersetzung stimmt — **gerade weil** sie die Rechenfehler des Originals
bitgenau mitrechnet. Wer sie behebt, ändert genau die Zahlen, die verglichen
werden.

**Entschieden am 18.11.2026 (Anwender):** kein Kompatibilitätsschalter,
sondern ein abgeschlossener, verifizierter Stand und danach saubere
Behebungen.

- **Version 3.0.1 ist der verifizierte Stand**, mit allen MATLAB-Fehlern
  dieser Liste. Ihr Verifikationsprotokoll steht gemessen in
  `docs/verification_escherichia_coli.md` („Record for version 3.0.1"), der
  Stand ist als Tag `v3.0.1` im Repository und jederzeit nachprüfbar.
- **Ab Version 3.1.0 werden die Fehler behoben.** Jede Behebung kommt mit
  Version, Grund und **gemessener Wirkung** nach
  `docs/changes_from_matlab.md`, und ihr Eintrag hier wandert nach „Behoben".
- **Der Referenztest** wird bei einer Behebung, die verglichene Größen ändert,
  für genau diese Größen angepasst — mit Verweis auf den Eintrag hier und auf
  das Protokoll von 3.0.1. Er wird nicht gelockert, um grün zu bleiben.

Pichia ist nicht verifiziert (kein Referenzlauf aus der aktuellen Quelle);
dort wurde schon vorher ohne diesen Umweg korrigiert, wie bei F-01 und
`sensor_lag`.

---

## 2. Offen

| Nr. | Fehler | Herkunft | Organismus | Wirkung | Vorschlag |
|---|---|---|---|---|---|
| F-02 | Messwertverzögerung rechnet Δt zweimal in Stunden um (`meas_transfer_function`): ein Schritt schließt 2,6e-09 des Abstands | MATLAB | E. coli | gemessen: `pHLm`, `thetaLm`, `pO2m`, `cS1Lm` bleiben auf ihrem Anfangswert stehen; kein E.-coli-Regler liest sie, aber Plot, Datentabelle und Export zeigen eingefrorene „Messwerte" | `sensor_lag` wie bei Pichia, in 3.1.0; Referenztest für die Messgrößen anpassen (Abschnitt 1) |
| F-03 | Index-Verzug („MATLAB lag"): ein Wert wird bei `idx` berechnet und im nächsten Ausdruck bei `idx-1` gelesen — Feed-Regler (P-Anteil liest `idx-1`, I und D `idx`), `QCO2max`, `OTRmax` | MATLAB | E. coli | gelesen; Wirkung nicht gemessen (ein Schritt Verzug) | Index angleichen, Wirkung messen, in 3.1.0 |
| F-04 | Pumpengrenzen von Säure und Lauge über Kreuz: die Säurerate wird mit `FT2max`, die Laugenrate mit `FT1max` skaliert | MATLAB | beide | gelesen; wirkt nur, wenn `FT1max` ≠ `FT2max` | richtige Grenze je Pumpe, in 3.1.0 |
| F-05 | RQ-Korrektur schreibt in den **vorigen** Schritt (`v.RQ[prev] = 0.0001`), überschreibt also Geschichte | MATLAB | E. coli | gelesen | den aktuellen Schritt korrigieren |
| F-06 | Anti-Windup des Rührerreglers in falscher Einheit: `clamp(cI_agi, 0, NStmax)` begrenzt einen normierten Wert mit rpm — die Untergrenze 0 hält den I-Anteil positiv, ein hochgefahrener Rührer kommt nicht mehr herunter | MATLAB | Pichia | gemessen (Projekt 519, `Mode_pO2` = 1): pO2 108,7 % mit Original, 78,3 % mit Schalter | teilweise behoben: der Anti-Windup-Schalter ersetzt die Klammer. Vorschlag: Schalter in den Vorgaben auf **an** |
| F-07 | Antischaum dosiert nie, wenn zur Zeit 0 beimpft wurde: das Modell liest `a.ToI != 0` als „beimpft" | MATLAB | beide | im Probelauf bestätigt: das Flag ändert dann nichts; seit der Antischaum-Vorlage auch sichtbar (Pumpe bleibt stehen) | `inoc_occ` statt `ToI != 0` abfragen |
| F-08 | `f_aeration` schaltet in `Mode_pO2` 2/3 das Gas nicht ab; mit 0 bleibt `FnN2`/`FnCO2` NaN, `xOGin` fällt auf 0, `FnG` läuft per `carry_forward` weiter | MATLAB | beide | gelesen, nicht gemessen; der PCS-Tab sperrt das Ventil in diesen Modi | im Modell sauber abschalten, dann die Sperre lösen |
| F-09 | `f_FR1`, `f_FR2`, `f_FR3` haben keinen Leser | MATLAB | beide | gelesen (Suche über den ganzen Baum) | entfernen oder anschließen |
| F-10 | Pulsfeed protokolliert „`f_feed` von 1 auf 0", setzt es aber nie | MATLAB | beide | gelesen (`control/phases.py`) | Protokoll oder Zuweisung angleichen |
| F-11 | Kühlwasserstrom im Automatikbetrieb mit Faktor 10: `mdotC = yC/100 · mdotCmax · 10` | MATLAB | beide | gelesen; ob gewollt, nicht geprüft. Gemessen bisher höchstens 121,6 kg/h gegen `mdotCmax` = 1 500 kg/h | in der MATLAB-Quelle und Arbeit klären |
| F-12 | Reglerzustände (I-Anteile) werden nicht gespeichert; ein fortgesetzter Lauf beginnt jeden I-Anteil bei null | MATLAB | beide | gemessen (Projekt 716): Rührer 469 → 1276 rpm nach Neuladen, pO2-RMS 7,06 → 9,85 | Zustände mitspeichern (neue Tabelle oder Spalte) |
| F-13 | `variable_handlingTab` passt nicht zu den Modellen: sieben E.-coli- und sechs Pichia-Reihen werden nie gespeichert (darunter die ODE-Zustände `xO2`, `xCO2`, die in `variableTab` gar keine Zeile haben); E. coli sind 19 Pichia-Variablen zugeordnet | Daten | beide | gemessen; ein fortgesetzter Lauf startet sie neu (`a.restarted_variables`, im Log gemeldet); `xfail(strict=True)` | Zeilen ergänzen, Zuordnung bereinigen |
| F-14 | `processTab.start_operatorID` verweist auf `process_conditiontypeTab` statt `process_operatorTab` | Daten (Schema) | — | gelesen; unsichtbar, weil die Werte 1 und 3 zufällig in beide Tabellen fallen | Schema korrigieren (Tabellenneuaufbau in der Migration) |
| F-15 | `xCGin` fehlt in `variableTab` (das Gegenstück `xOGin` ist da) | Daten | — | gelesen | Zeile ergänzen |
| F-16 | Vorlageprojekte: `LWw` = 14 kg bei `VLmax` = 11 l und `rhoL` = 1 — der Füllgewichtsregler lässt nie etwas ab | Daten | — | gelesen | Sollwert in den Vorgaben prüfen |
| F-32 | **PySide6 6.12.0 lässt den Interpreter abstürzen**, wenn Fenster abgebaut werden, deren Schaltflächen an ein `lambda` gebunden sind, das das Fenster festhält: „Fatal Python error: bool_dealloc: deallocating True or False" — ein Referenzzählerfehler in der Erweiterung, der sich je abgebautem Fenster aufsummiert. Unter Python 3.11 sind `True`/`False` nicht unsterblich | Fremdbibliothek | — | gemessen (18.11.2026): alle Tests bestehen, der Prozess endet mit Exit-Code 134/139 (Linux-CI, macOS). Nachgestellt: 30 × „Load Project" auf- und abgebaut → Absturz; mit 6.11.2 und 6.11.3 nicht. Eingegrenzt auf die Verbindung `compact_button.clicked → lambda: self.compact()` in `SelectProjectWindow`; ein gleich gebautes Minimalbeispiel stürzt auch nach 5000 Fenstern nicht ab, das Muster allein reicht also nicht. 28 solcher Verbindungen im Code | **umgangen**: `PySide6<6.12` in `pyproject.toml`. Aufheben, sobald eine neuere Version mit `tests/test_gui.py` allein und der ganzen Suite mit Exit-Code 0 durchläuft. Beim Wechsel auf Python ≥ 3.12 wäre der Absturz vermutlich weg (unsterbliche `True`/`False`), der Zählerfehler nicht |
| F-17 | `AAF` heißt „added antifoam [l]", ist aber eine abklingende Wirkgröße; ob `VAF ** (TON/Ttast)` eine sich leerende Vorlage beschreiben sollte, ist ungeklärt | MATLAB | beide | gelesen | Bedeutung klären, Beschriftung korrigieren |

---

## 3. Behoben

| Nr. | Fehler | Herkunft | Behoben | Wie |
|---|---|---|---|---|
| F-01 | Feed-Verstärkungen von Reservoir 2 (Pichia) mit falschem Vorzeichen: `KP/KI/KD_feedR2` = −2/−15/−0,009 sind eine Kopie des pO2-Feed-Reglers; auf einem Substratkreis kehrt das den Regler um, die Pumpe bleibt zu (gemessen: 100 % der Zeit am Anschlag) | Daten (MATLAB-Datenbank) | Vorgaben früher (`CLAUDE.md`, „Reglereinstellung“); Projekte und ältere Datenbanken 18.11.2026 | gemessene Werte 1/5/0,005. `repair.correct_pichia_feed_gains` prüft Vorgaben, Modelle und Projekte einzeln und ersetzt nur Werte, die noch auf der falschen Zahl stehen; Projekte mit gespeicherter Aufzeichnung behalten ihre Werte. Läuft beim Programmstart (mit Kopie `.pre-correction.db`), ein korrigiertes Projekt meldet es beim Öffnen im Log |
| F-18 | Vier Fehler in der Begasung (`FnO2` mit Vorschritt-`FnAIR`; Pichia summiert `FnG` aus dem Vorschritt; `0/0` bei `FnG = 0`; `f_O2 = 0` schaltete die **Luft** ab) | MATLAB | bei der Portierung | korrigiert; Referenzlauf blieb bitgleich (außerhalb des verifizierten Fensters) |
| F-19 | Messwertverzögerung bei Pichia (wie F-02) | MATLAB | bei der Portierung | `sensor_lag`; der Closed-Loop-Feed regelte vorher auf einer Konstanten |
| F-20 | Gleichheitsoperator „=" löste nie aus (MATLAB prüfte `==`) | MATLAB | bei der Portierung | beide Schreibweisen akzeptiert |
| F-21 | Variable Pool zeigte `FT1`/`FT2` vertauscht | MATLAB | bei der Portierung | richtig zugeordnet |
| F-22 | Pichia-Vorgaben verfälscht (`yXpOgr`, `yCpO`, `qOpXm` mit Werten der Toxizitätsparameter, etwa dreifache Sauerstoffaufnahme) | Daten | Phase 2 | `db/repair.py` |
| F-23 | BIOSTAT B trug die Werte des BIOSTAT ED | Daten | Phase 1 | aus `Parameter Overview.xlsx` |
| F-24 | Schema: `end_typeID` auf falscher Tabelle, fehlende `logTab`-Spalten, `processID` je Projekt statt tabellenweit, keine Indizes auf Fremdschlüsseln | Daten (Schema) | Phase 1 | `apply_migration`, `_claim_free_process_ids`, Indizes |
| F-25 | Projekt anlegen und löschen ohne Transaktion, Löschen mit `foreign_keys = OFF` — so ist die produktive Datenbank zerstört worden | MATLAB | Phase 4 | je eine Transaktion, Kaskade durch SQLite |
| F-26 | `tmax` war ein Parameter ohne Leser | MATLAB | Phase 1 | entfernt (`remove_dead_parameters`) |
| F-27 | Füllgewichtsregler ließ auch unter dem Sollwert ab (I-Anteil) | MATLAB | 16.11.2026 | bewusste Abweichung, vom Autor gewünscht |
| F-28 | Plotachsen: negative Untergrenze verschob die Teilstriche gegen alle anderen Achsen | MATLAB (`calculateYLimits`) | 17.11.2026 | `aligned_limits` (nur Anzeige) |
| F-29 | Wiedergeöffnetes Projekt wurde neu beimpft (`inoc_occ`) | Portierung | Phase 5 | `_adopt_inoculation` |
| F-30 | Löschen einer kommenden Phase startete die laufende neu (Startzeit überschrieben, `FR1j` = 0) | Portierung | 18.11.2026 | `adopt_active_phase` statt `current = None` |
| F-31 | Achsenbeschriftung zeigte bei krummen Schritten falsche Zahlen (0,36 als „0,4") | Portierung (pyqtgraph) | 17.11.2026 | `HonestTicksAxis` |

---

## 4. Keine Fehler, aber Prüflücken

Nicht falsch, nur nicht gegen eine Vorlage geprüft — gehört nicht in die
Fehlerliste, aber hierher, damit es nicht vergessen wird:

- Pichia als Ganzes (kein Referenzlauf aus der aktuellen Quelle).
- `Mode_pH` 0, `Mode_temp` 0, `Mode_pO2` 2/3/4 (der Referenzlauf benutzt sie
  nicht); der Pulsfeed nur strukturell.
- Der Windows-Build läuft in der CI, ist aber nie von Hand benutzt worden.
- Der pO2-Kreis von Pichia ist mit der mitgelieferten Begasung
  versorgungsbegrenzt — kein Fehler, aber Verstärkungen ändern dort nichts.
