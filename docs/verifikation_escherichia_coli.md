# Verifikation des E.-coli-Modells gegen MATLAB

Stand: 9. September 2026 · Projektplan §2.4 · Commit `ee24379`

---

## Frage

Rechnet die Python-Portierung dasselbe wie die MATLAB-Anwendung?

Das ist keine Frage nach der Physik — die steckt unverändert im Modell —,
sondern nach der **Übersetzungstreue** von 953 Zeilen `Escherichia_coli.m`
plus 73 Zeilen ODE-Definitionen und 257 Zeilen Initialisierung.

Fehler dieser Art sind besonders tückisch, weil sie plausible Ergebnisse
liefern: ein um eins verschobener Index, ein `end-1` statt `previdx`, ein
Vorzeichen, MATLABs 1-basierte Zählung, ein `any()` auf einem Skalar. Die
Kurven zeigen weiterhin Wachstum, Substratverbrauch und pO2-Einbruch. Keiner
der 24 Plausibilitätstests dieses Projekts würde etwas bemerken.

Erschwerend: an über zwei Dutzend Stellen schreibt das MATLAB-Original einen
Wert bei `idx` und liest im nächsten Ausdruck den bei `idx-1`. Diese
Eigenheiten sind bewusst wörtlich übernommen (im Code als `# MATLAB lag`
markiert). Wäre eine davon in die falsche Richtung übersetzt, bliebe das ohne
Referenzlauf unentdeckt.

## Datenquelle

Eine MATLAB-Lizenz stand nicht zur Verfügung. Verwendet wird stattdessen
`MyProject_11.txt` — ein Export, den die Anwendung selbst geschrieben hat.

| Datei | Datum |
|---|---|
| `Escherichia_coli.m` | 22. April 2026 |
| `Escherichia_coli_Initialization.m` | 19. April 2026 |
| **`MyProject_11.txt`** | **27. April 2026** |

Der Export ist fünf Tage jünger als die Modellquelle, stammt also
nachweislich von demselben Code. Inhalt: 43 Variablen, 2983 Schritte,
dt = 2 s (0,000555… h), 1,657 h Prozesszeit.

### Der Parametersatz musste rekonstruiert werden

Der Export enthält keinen. Das zugehörige Projekt ist gelöscht — von 733 je
angelegten Projekten existieren noch 14 (siehe `docs/` und CLAUDE.md zur
Datenbank-Forensik).

Verwendet wird der Parametersatz von **Projekt 716** der mitgelieferten
Datenbank. Die Zuordnung ist belegt, nicht geraten:

| Größe im Lauf | Wert | Parameter in Projekt 716 |
|---|---|---|
| `cS1L(0)` | 10 | `cS1L0` = 10 |
| `thetaL(0)` | 32 | `thetaL0` = 32 |
| `pHL(0)` | 7,5 | `pH0` = 7,5 |
| `pO2(0)` | 100 | `pO20` = 100 |
| `VL(0)` | 10 | `VL0` = 10 |
| `NSt(0)` | 400 | `NStw` = 400 |
| `FnAIR(0)` | 7,5 | `FnAIRw` = 7,5 |
| `xOGin(0)` | 0,2094 | `xOGcal` = 0,2094 |
| `pG(0)` | 200000 | `pGcal` + `deltapGw`·10⁵ = 150000 + 50000 |
| `kLa(0)` | 97,8605 | aus `kLamin`, `kLamax`, `FnGw`, `NStw`, `NStmax`, `VL0`, `VLmin` |
| `NSt(1)` | 450 | 0,3 · `NStmax` — untere Begrenzung des pO2-Reglers |

Elf unabhängige Größen, darunter zwei aus mehreren Parametern zusammengesetzte.
Die anschließende Übereinstimmung auf 1e-09 bestätigt die Wahl endgültig.

### Inokulation

`cXL` ist in den Zeilen 0 und 1 null und in Zeile 2 gleich 3,0. Die
Inokulation wurde also **während** des Laufs eingeschaltet, nicht davor. Der
Vergleich bildet das nach: `f_InocStart = 0`, und `f_Inoc` wird im zweiten
Schritt auf 1 gesetzt.

## Vergleichsfenster: Schritte 0 bis 402

Bei Schritt 403 beginnt im Lauf eine Fed-Batch-Phase:

```
FR1   erste Abweichung bei idx 403:   MATLAB = 0,038992   Python = 0
```

Phase 2 hat keinen Phasenautomaten — ab dort simulieren die beiden Läufe
verschiedene Experimente. Der Vergleich endet deshalb bei Schritt 402, dem
letzten Schritt der reinen Batch-Phase. **Mit Phase 3 wird das Fenster
länger.**

## Ergebnis

### Zustandsgrößen und Bilanzen

| Größe | MATLAB @402 | Python @402 | rel. | abs. |
|---|---:|---:|---:|---:|
| `cXL` | 3,22525633 | 3,22525663 | 4,9e-07 | 1,5e-06 |
| `cS1L` | 9,49029966 | 9,49029928 | 2,7e-07 | 2,7e-06 |
| `cS3L` | 0,0281950007 | 0,0281942084 | 4,1e-04 | 7,9e-07 |
| `pHL` | 6,66754008 | 6,66754960 | 1,4e-06 | 9,5e-06 |
| `thetaL` | 31,9531001 | 31,9530837 | 1,1e-06 | 3,5e-05 |
| `VL` | 10,0398611 | 10,0398611 | **5,5e-14** | 5,6e-13 |

### Messgrößen (Verzögerungsglieder erster Ordnung)

| Größe | rel. | abs. |
|---|---:|---:|
| `pHLm` | 2,5e-12 | 1,9e-11 |
| `thetaLm` | 1,0e-12 | 3,2e-11 |
| `pO2m` | 3,1e-11 | 3,1e-09 |
| `cS1Lm` | 9,3e-14 | 9,3e-13 |

### Schnelle Sauerstoffschleife

Diese Größen gehen durch null, weshalb eine relative Schranke dort
bedeutungslos wird — maßgeblich ist die absolute Abweichung im Verhältnis zum
durchlaufenen Wertebereich.

| Größe | rel. | abs. | Bereich im Lauf |
|---|---:|---:|---|
| `pO2` | 6,4e-04 | 2,1e-02 | 11,3 … 101,1 |
| `cOL` | 8,9e-04 | 3,6e-06 | 0,00128 … 0,0118 |
| `OUR` | 8,7e-05 | 8,0e-05 | 0 … 0,982 |
| `OTR` | 2,0e-03 | 1,2e-03 | 0 … 0,869 |
| `kLa` | 2,1e-03 | 2,2e-01 | 69,9 … 124,1 |
| `NSt` | 1,4e-03 | 7,1e-01 | 400 … 550 |
| `xOG` | 7,5e-05 | 1,5e-05 | 0,196 … 0,209 |
| `RQ` | 3,9e-02 | 1,4e-04 | 0,0001 … 1,047 |
| `CTR` | 1,8e-02 | 3,9e-04 | −1,271 … 0,143 |

Exakt identisch über das gesamte Fenster: `pG`, `FnG`, `FT1`, `FT2`,
`QO2max` (bis auf 5e-14).

### Die ersten zwölf Schritte

Bevor irgendein Regler schaltet, sind beide Implementierungen numerisch
dasselbe Programm:

| Größe | rel. Abweichung |
|---|---:|
| `VL` | 4,6e-15 |
| `pHL` | 1,3e-10 |
| `cS1L` | 2,8e-09 |
| `cXL` | 4,8e-09 |
| `thetaL` | 2,7e-07 |

`thetaL` liegt eine Dezimale zurück. Die Temperaturbilanz ist der steifste
Teil des Systems und zeigt MATLABs eigene Solver-Toleranz zuerst.

## Was der Lauf abdeckt

**Geprüft:** die 18 ODE-Zustände, die Newton-Iteration für den pH-Wert,
Sauerstoff- und CO₂-Transfer mit Stanton-Zahlen, das Temperatursystem mit
Doppelmantel und Kühlkreis, die Wachstumskinetik mit Substrat- und
Sauerstofflimitierung, Acetatbildung und -rückverwertung, der
Rührwerksregler über 400–1306 rpm, beide pH-Pumpenrichtungen, die
Verzögerungsglieder der Messgrößen und die Volumenbilanz mit Titration.

**Nicht geprüft:** reine O₂-, N₂- oder CO₂-Begasung (`FnO2`, `FnN2`, `FnCO2`
durchgehend null), Antischaumzugabe (`AAF` null), Ernte, Glycerin als
Substrat (`cS2L` null), Exponential- und Pulsfeed, Betriebsart `Mode_pO2` 2,
3 und 4, `Mode_pH` 0, `Mode_temp` 0.

## Warum es keine globale Toleranz geben kann

Der Plan sieht in §2.4 eine Schranke von `rtol = 1e-4` über den ganzen Lauf
vor. Für dieses System ist das unerreichbar, unabhängig von der Qualität der
Übersetzung.

Der pH-Regler hat ein hartes Totband:

```matlab
if abs(app.p.pHw - app.v.pHL(previdx)) < 0.1
    app.v.FT1(idx) = 0;  app.v.FT2(idx) = 0;
```

Der Prozess sitzt praktisch auf dieser Schwelle. In **19 % aller Schritte**
liegt MATLAB näher als 1e-3 an ihr. Bei Schritt 785 sieht das so aus:

```
MATLAB  pHL = 6,6000088   Abstand 0,0999912   Regler AUS
Python  pHL = 6,5999080   Abstand 0,1000920   Regler AN
Differenz im pH: 1,0e-04
```

Eine Differenz in der vierten Nachkommastelle entscheidet, ob die
Laugenpumpe läuft. Über den vollen Lauf fallen **1016 von 2983 Schritten**
unterschiedlich aus. Jede Rundungsdifferenz — zwischen `ode15s` und LSODA,
zwischen zwei MATLAB-Versionen, zwischen zwei Prozessoren — wird an dieser
Unstetigkeit verstärkt.

Bit-genaue Langzeitreproduktion ist hier **prinzipiell** unmöglich, nicht
bloß schwierig. Deshalb: scharfe Prüfung im Fenster vor dem ersten
Umschalten, danach keine.

Das ist kein Mangel des Modells. Ein Zweipunktregler mit Totband ist in der
Bioprozesstechnik üblich und richtig. Es ist eine Eigenschaft, die man beim
Entwurf eines Regressionstests kennen muss.

## Reproduktion

```bash
pytest tests/test_organisms.py -k reference -v
```

Die Fixtures liegen unter `tests/reference_data/` und lassen sich mit
`python tests/reference_data/extract.py ecoli` neu erzeugen, solange
`~/Documents/Biofermentation Simulation Version 2.2/MyProject_11.txt`
vorhanden ist.

Die Toleranzen in `test_organisms.py` sind aus den Tabellen oben abgeleitet
und haben mindestens Faktor zwei Reserve. Sie sind gemessen, nicht geraten —
wer sie später lockert, sollte den Grund hier nachtragen.

## Pichia pastoris

Nicht verifiziert, und das bleibt vorerst so.

Der einzige verfügbare Lauf (`Thesis_SimulationAppDB.db`, Projekt 520, 2. März
2025) ist 14 Monate älter als `Pichia_pastoris.m` (22. April 2026).
Nachweisbar an `kLa`: die aktuelle Formel reproduziert die Werte des Laufs
nicht, obwohl die Übersetzung ihr zeilengenau folgt.

Der Grund ist bekannt: die Strategie der Software wurde geändert und dabei
nur das E.-coli-Modell nachgezogen. Pichia steht noch auf dem älteren
Ansatz. Eine Vorlage aus der aktuellen Quelle existiert nicht, und solange
das so ist, kann es keine Verifikation geben.

Die Pichia-Übersetzung folgt der vorhandenen Quelle zeilengenau und ist über
Struktur- und Plausibilitätstests abgesichert — das ist schwächer als eine
Verifikation und wird hier nicht als solche ausgegeben.

Der Thesis-Lauf bleibt als Fixture liegen. Mit seinen sieben Phasen ist er
die natürliche Vorlage für den Phasenautomaten aus Phase 3, sobald das
Pichia-Modell nachgezogen wird.
