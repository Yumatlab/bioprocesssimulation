# Handbuch

Biofermentation Simulation 3.0 — für Anwenderinnen und Anwender.

Dieses Handbuch beschreibt, was die Anwendung tut und wie man sie bedient.
Es setzt Grundkenntnisse der Bioverfahrenstechnik voraus, aber keine
Programmierkenntnisse. Wer wissen will, wie die Anwendung *gebaut* ist, findet
das in [`architektur.md`](architektur.md); wer sie weiterentwickeln will, in
[`weiterentwicklung.md`](weiterentwicklung.md).

Jede Aussage hier lässt sich nachprüfen. Wo ein Parameter genannt wird, steht
sein Name so, wie er in der Anwendung und in der Datenbank heißt — `pHw`,
`cS1Lw`, `Mode_pO2`. Wer ihn sucht, findet ihn unter **Project → Parameters…**.

---

## 1. Was die Anwendung simuliert

Einen Rührkesselreaktor im Batch-, Fed-Batch- oder Induktionsbetrieb. In jedem
Zeitschritt werden gerechnet:

- **Stoffbilanzen** für Biomasse, Substrate, Produkt, gelösten Sauerstoff,
  gelöstes CO₂ und die Titriermittel — achtzehn gekoppelte
  Differentialgleichungen, gelöst mit LSODA.
- **Vier Regelkreise**: pH, Temperatur, Sauerstoffpartialdruck und Füllstand.
- **Die Fütterung**: von Hand, exponentiell, als Puls oder geregelt gegen eine
  Substratkonzentration.
- **Ein Phasenautomat**, der den Prozess anhand von Bedingungen weiterschaltet,
  die Sie selbst festlegen.

Mitgeliefert sind zwei Organismen: *Escherichia coli* und *Pichia pastoris*.

Die Schrittweite steht als `deltatsec` im Projekt — die mitgelieferten
Organismen bringen 2 Sekunden Prozesszeit mit. Das Feld **Δt [s]** im
Kontrollfenster zeigt und ändert genau diesen Wert; die Anwendung übernimmt
ihn beim Öffnen aus dem Projekt und nicht aus einer eigenen Vorgabe. Eine
Fermentation über 24 Stunden rechnet damit in wenigen Sekunden.

**Was die Anwendung nicht ist:** kein Ersatz für ein Experiment. Sie rechnet
ein Modell, und ein Modell ist so gut wie seine Parameter. Abschnitt 9 sagt,
was davon gegen echte Daten geprüft ist und was nicht.

---

## 2. Der erste Lauf

### Projekt anlegen

Nach dem Start sehen Sie vier Schaltflächen. **Start New Project** öffnet das
Anlegefenster. Dort geben Sie einen Namen ein und wählen ein **Modell** aus der
Liste.

Ein Modell ist die Kombination aus einem Organismus und einem Bioreaktor —
etwa „Escherichia coli in BIOSTAT ED". Aus ihm wird der komplette
Parametersatz des Projekts kopiert: rund 280 Werte, von der Kesselgeometrie
bis zur Wachstumskinetik. Diese Kopie gehört danach dem Projekt allein. Ändern
Sie später die Vorgabewerte des Organismus, wirkt das auf **neue** Projekte,
nicht auf bestehende. Das ist Absicht — nur so bleibt ein gespeicherter Lauf
reproduzierbar.

### Das Kontrollfenster

Danach öffnet sich das Kontrollfenster. Links die Tabs, rechts die
Laufsteuerung:

| Element | Bedeutung |
|---|---|
| **Run / Pause** | startet und hält die Simulation an |
| **Inoculate** | beimpft den Kessel |
| **Parameters…** | der vollständige Parametersatz |
| **Δt [s]** | Schrittweite in Sekunden Prozesszeit |
| **Speed factor [x]** | wie viele Schritte je Bildschirmaktualisierung |
| **Open Plot / Save / Exit** | Diagramm, Speichern, Beenden |

Oben rechts zwei Lampen: **Process Running** und **Inoculated**.

### Beimpfen und starten

**Vor** dem ersten Schritt ist `Inoculate` ein Umschalter: gedrückt heißt, der
Lauf beginnt mit Zellen im Kessel (`cXL0`, standardmäßig 3 g/l). Nicht
gedrückt heißt, der Kessel startet steril.

**Während** des Laufs ist es ein einmaliger Druck: die Beimpfung geschieht im
nächsten Schritt, die Schaltfläche wird danach dunkel.

Ohne Beimpfung wächst nichts — die Wachstumsterme sind an `f_Inoc` gebunden.
Wer den Lauf startet und nichts passieren sieht, hat meistens das vergessen.

---

## 3. Die Tabs

| Tab | Wofür |
|---|---|
| **Control Options** | die fünf Regelpanels — der Arbeitsplatz |
| **Controllers** | was jeder Regler gerade rechnet |
| **Variable Pool** | alle Zustandsgrößen als Zahlen |
| **Process Manager** | die Phasen des Prozesses |
| **Log** | das Protokoll der Sitzung |
| **Information** | Projektdaten und Herkunft der Anwendung |

Vier davon lassen sich unter **Settings…** auf dem Startbildschirm abschalten;
Control Options und Information bleiben immer.

---

## 4. Die Regelpanels

Jedes Panel hat denselben Aufbau: oben die **Modusauswahl** mit einer Lampe,
darunter die **Sollwerte** (links) und **Messwerte** (rechts, grau, nicht
beschreibbar), darunter **Schalter**, und am Fuß eine Schaltfläche
**Parameters** für die Reglerverstärkungen dieses Kreises.

Die Lampe neben dem Modus sagt, ob dieser Kreis gerade *regelt* — nicht,
welcher Modus gewählt ist. Das sagt die Taste.

### pH-Control

| | |
|---|---|
| Modi | `Mode_pH`: **Manual**, **Auto** |
| Sollwert | `pHw` — Sollwert des pH |
| Messwert | `pHL` |
| Schalter | `f_alkali`, `f_acid` — Laugen- und Säurepumpe von Hand |

Im Auto-Modus arbeitet eine Kaskade: ein Master-Regler bestimmt aus der
Abweichung eine Stellgröße, zwei Slave-Regler bedienen Säure und Lauge. Der
Regler hat ein **hartes Totband von 0,1 pH** — innerhalb davon tut er nichts.
Das ist kein Fehler, sondern verhindert dauerndes Hin- und Herpumpen.

### Temperature-Control

| | |
|---|---|
| Modi | `Mode_temp`: **Manual**, **Auto** |
| Sollwert | `thetaLw` [°C] |
| Messwert | `thetaL` |
| Schalter | `f_cooling`, `f_heating` |

Geregelt wird über den Doppelmantel; das Modell rechnet Kühlwasser- und
Dampfmassenstrom mit.

### pO2-Control

Der einzige Kreis mit fünf Modi, deshalb als **Drehschalter** dargestellt. Der
Punkt am Knopf ist grün für einen Regelmodus und rot für Handbetrieb.

| `Mode_pO2` | Stellgröße |
|---|---|
| **Manual** | nichts wird geregelt; es gelten die Sollwerte darunter |
| **Agitation** | Rührerdrehzahl `NSt` (Grenzen 0,3 bis 1,0 der Maximaldrehzahl) |
| **Aeration** | Gesamtbegasungsrate `FnG` (30 bis 100 %) |
| **Gasmix** | Sauerstoffanteil im Zuluftgemisch `xOGin` |
| **Feed** | die Fütterungsrate — Sauerstoffbedarf über das Substrat begrenzen |

Felder: `pO2w` [%] Sollwert, `NStw` [1/min] Rührerdrehzahl, `FnGw` [l/min]
gewählte Begasungsrate, `FnAIRw` [l/min] Luft, `FnO2w` [l/min] reiner
Sauerstoff. Welches Feld aktiv ist, hängt vom Modus ab; die übrigen werden
grau.

> **pO2 über 100 % ist kein Rechenfehler.** Die Sonde wird gegen Luft
> kalibriert. Wer mit angereichertem Sauerstoff begast, kann darüber kommen —
> gemessen 124 % bei 15 l/min Luft plus 1 l/min O₂. Das ist physikalisch
> richtig.

### Liquid Weight

| | |
|---|---|
| Modi | `Mode_harvest`: **Manual**, **Auto** |
| Sollwerte | `LWw` [kg] Füllstandssollwert, `FHrelw` [%] Ernterate |
| Schalter | `f_harvest` |

### Feed Control

| | |
|---|---|
| Modi | `Mode_feed`: **Manual**, **Closed loop** |
| Sollwerte | `cS1Lw` [g/l] Substratsollwert, `FR1w` [l/h] Pumpenrate |
| Nur lesbar | `FR1max` [l/h] maximale Pumpenrate des Reservoirs |
| Schalter | `f_feed` — die Pumpe |

Hat der Organismus mehrere Reservoirs, steht darüber eine Auswahl **R1 / R2**;
der Parameter dahinter ist `R_feed`.

> **Der Modus wählt, *wie* gepumpt wird — der Schalter, *ob*.** Steht `f_feed`
> auf aus, passiert nichts, egal welcher Modus gewählt ist. Der Regler rechnet
> dann nicht einmal. Das ist die häufigste Ursache für „der Feed-Regler tut
> nichts".

Im Closed-Loop-Modus regelt ein PID-Regler die Pumpe so, dass `cS1L` auf
`cS1Lw` gehalten wird. Er kann nur zufüttern, nicht entziehen: liegt die
Substratkonzentration **über** dem Sollwert, steht die Pumpe, bis der
Organismus den Überschuss verbraucht hat.

---

## 5. Der Prozessablauf: Phasen

Im **Process Manager** steht der Prozess als Reihe von Phasen, mit Pfeilen
dazwischen. Jede Phase hat einen Namen, einen Typ, eine Start- und eine
Endbedingung sowie eine Statuslampe.

### Die fünf Phasentypen

| Typ | Was beim Start der Phase geschieht |
|---|---|
| **Manual** | nichts; die Phase wartet nur auf ihre Endbedingung |
| **Update Parameter Set** | die hinterlegten Parameterwerte werden gesetzt |
| **Exponential Feed** | die Pumpenrate wächst mit `FR = FRj · e^(qXpX1w·(t−tj))` |
| **Pulse Feed** | die Pumpe läuft mit `FR1max · kR1` |
| **Stop** | der Lauf wird angehalten |

### Bedingungen

**Start**: „End of previous phase", eine Variablenbedingung (`cXL > 5 g/l`),
oder „Batch end" — die Erkennung des Substratendes über den pO2-Anstieg.

**Ende**: „Next phase condition", eine Variablenbedingung oder ein Timer.

### Was eine Phase an Parametern anbietet

Die Schaltfläche **Parameters…** im Phasendialog zeigt je nach Typ
Verschiedenes:

- **Update Parameter Set**: alle Parameter, die während eines Laufs änderbar
  sind — Sollwerte, Modi, Flags, Reglerverstärkungen.
- **Exponential Feed**: die fünf Werte, aus denen die Rate berechnet wird, für
  das Reservoir dieser Phase.
- **Pulse Feed**: `kR1` und `FR1max`.
- **Manual** und **Stop**: nichts, die Schaltfläche bleibt aus.

Gespeichert wird nur, was Sie tatsächlich ändern. Ein unberührtes Feld heißt
„so lassen, wie es dann gerade ist" — nicht „auf diesen Wert setzen".

> **Eine laufende oder abgeschlossene Phase lässt sich nicht mehr bearbeiten.**
> Der Automat hat ihre Bedingungen bereits gelesen und ihre Parameter
> angewandt; eine Änderung danach beschriebe einen Prozess, der so nicht
> stattgefunden hat.

Der **Pfeil** zwischen zwei Panels erzwingt den Übergang zur nächsten Phase,
ohne auf die Bedingung zu warten. Er ist nur nach der aktiven Phase bedienbar.

Phasen bearbeiten geht nur bei **angehaltenem** Prozess.

---

## 6. Den Regler verstehen: der Controllers-Tab

Die Anwendung rechnet in jedem Schritt für jeden Regler den P-, I- und
D-Anteil aus — und zeigte davon in der MATLAB-Fassung nichts. Wer pO2 schwingen
sah, sah nicht den I-Anteil auflaufen, und das ist meist die Erklärung.

Der Tab zeigt je Regelkreis Sollwert, Messwert, Abweichung, die drei Anteile
als vorzeichenbehaftete Balken auf gemeinsamer Skala, die Verstärkung und die
Stellgröße.

**Das ist das wichtigste Werkzeug, um Regelverhalten zu lernen.** Ein Regler,
dessen I-Balken immer weiter wächst, während die Stellgröße am Anschlag steht,
ist im Windup — er wird noch lange falsch stellen, nachdem die Abweichung
längst das Vorzeichen gewechselt hat.

---

## 7. Auswerten

### Plot

**Open Plot** (Ctrl+G) öffnet ein Diagrammfenster, das dem Lauf folgt. Mehrere
Fenster gleichzeitig sind möglich. Unter **Plots → Open plot from template**
liegen gespeicherte Achsen- und Kurvenzusammenstellungen.

### Datentabelle

**Export → Open data table** (Ctrl+T) zeigt alle Zeitreihen als Tabelle.

### Export

**Export → Export project…** (Ctrl+E) schreibt den Lauf in lesbare Dateien:
CSVs für Menschen — Phasentyp, Status und Einheit ausgeschrieben statt als
Nummer — und daneben ein Manifest `project.yaml`, das die Anwendung selbst
wieder einlesen kann.

---

## 8. Speichern, Schließen, Einrichten

### Speichern

**Save** (Ctrl+S) schreibt Parameter, Zeitreihen, Phasen und Protokoll in
**einer** Transaktion und legt danach eine Sicherungskopie neben der Datenbank
an. Während der Simulation wird nicht auf die Datenbank zugegriffen: einmal
lesen beim Öffnen, einmal schreiben am Ende.

### Schließen

Jeder Weg aus einem Projekt heraus führt über denselben Dialog: Name, Autor,
Beschreibung, die gespeicherte Auflösung, und dann **Save**, **Discard**,
**Delete**, **Export** oder **Cancel**. Export schließt den Dialog nicht —
eine Entscheidung über das Projekt steht ja noch aus. Löschen fragt ein
zweites Mal.

Das Feld **„Store one point per … steps"** ist mit der Einstellung aus
**Settings…** vorbelegt und lässt sich hier für diesen einen Lauf ändern; der
Text daneben sagt, was der Wert bei diesem Δt bedeutet. Siehe „Gespeicherte
Auflösung" weiter unten.

Es ist immer nur ein Projekt gleichzeitig geöffnet.

### Drei Textdateien neben der Datenbank

Sie liegen neben der Datenbank und lassen sich mit jedem Editor ändern:

| System | Ort |
|---|---|
| macOS | `~/Library/Application Support/Biofermentation Simulation/` |
| Windows | `%APPDATA%\Biofermentation Simulation\` |
| Linux | `~/.local/share/biofermentation/` |

Die Umgebungsvariable `BIOFERMENTATION_DB` überschreibt den Ort — damit lassen
sich zwei Installationen nebeneinander betreiben, ohne dass sie sich eine
Datenbank teilen.


| Datei | Wofür |
|---|---|
| `style.qss` | Farben, Abstände, Schriften |
| `control_options.yaml` | Anordnung der Regelpanels und Art der Modusauswahl |
| `settings.yaml` | welche Tabs erscheinen, Studierendenansicht, Refresh, gespeicherte Auflösung |

`control_options.yaml` legt **Settings → Panel layout…** im Kontrollfenster an
und öffnet sie. Eine fehlerhafte Datei wirft nie den Tab weg: die Anwendung
nimmt die Ersatzanordnung und schreibt den Grund ins Protokoll.

### Bibliothek

**Library…** auf dem Startbildschirm verwaltet Organismen und Bioreaktoren und
importiert oder exportiert sie. Eine Kopie eines Organismus mit anderen Werten
ist ein neuer Organismus und braucht kein Python — die Kinetik übernimmt die
Kopie von ihrer Vorlage.

**Wichtig:** Ein neuer Organismus oder Kessel ist erst auswählbar, wenn es ein
**Modell** dazu gibt. Dafür ist die Schaltfläche **Make selectable…** da.

### Refreshrate und Δt entkoppeln

Unter **Settings…** steht die Checkbox **„Refreshrate an Δt koppeln"**.
Angehakt — die Vorgabe — rechnet die Anwendung einen Schritt je Taktschlag:
ein Speedfactor von 1 läuft dann in Echtzeit, egal wie Δt eingestellt ist.

Nehmen Sie den Haken heraus, wird das Feld darunter aktiv und bestimmt den
Takt. **Das ändert auch das Tempo:** bei Δt = 10 s und 2 s Refresh schreitet
der Prozess je Taktschlag zehn Sekunden voran, geschlagen wird aber alle zwei
— der Lauf ist fünffach schneller als die Wirklichkeit. Das Verhältnis Δt zu
Refresh *ist* der Faktor.

Kurz: **Δt bestimmt, wie fein gerechnet wird, der Refresh, wie oft man es
sieht.** Wie viel davon in der Datei landet, ist eine dritte Frage — der
nächste Abschnitt.

### Gespeicherte Auflösung

Ein Lauf über 14 Stunden bei Δt = 2 s sind 25 200 Zeitpunkte und, mal 56
Variablen, rund 1,44 Millionen Messwerte. Das ist der Grund, warum Projekte
groß werden.

**Δt zu vergrößern ist dafür der falsche Hebel.** Die Regler sind auf Δt = 2 s
eingestellt, und ein größeres Δt verschlechtert die Regelung messbar: die
pO2-Abweichung (RMS) liegt bei Δt = 2 s bei 9, bei 20 s bei 37 und bei 60 s
bei 121. Sie bekämen eine kleinere Datei und einen anderen Prozess.

Deshalb steht unter **Settings…** die Gruppe **Stored resolution** mit dem
Feld **„Store one point per … steps"**:

- **1 Schritt** — die Vorgabe, alles wird gespeichert.
- **5 Schritte** — jeder fünfte Zeitpunkt wird gespeichert, bei Δt = 2 s also
  einer alle 10 Sekunden. Die Datei wird etwa fünfmal kleiner.

**Am Lauf ändert das nichts.** Gerechnet, geregelt und geplottet wird jeder
Schritt; nur beim Schreiben wird ausgedünnt. Der letzte gerechnete Schritt
wird immer gespeichert, egal welcher Wert eingestellt ist — sonst startete ein
fortgesetzter Lauf nicht dort, wo er aufgehört hat.

**Beim Speichern lässt sich der Wert noch einmal ändern.** Im Schließen-Dialog
steht dasselbe Feld, vorbelegt mit der Einstellung. Das ist der einzige
Moment, in dem jemand weiß, wie lang der Lauf tatsächlich geworden ist.

**Was ein ausgedünntes Projekt beim Laden zeigt:** genau die gespeicherten
Punkte. Plot, Datentabelle und Export haben dann die gröbere Auflösung — die
Zwischenschritte sind nicht verloren gegangen, sie wurden bewusst nicht
geschrieben. Der fortgesetzte Lauf rechnet wieder mit dem vollen Δt weiter.
Wenn Sie einen Lauf für eine Auswertung brauchen, lassen Sie den Wert auf 1.

### Studierendenansicht

Unter **Settings…** lässt sich die Laufsteuerung sperren: Δt bleibt sichtbar,
aber unveränderlich, und der Speedfactor verschwindet ganz. Ein Lauf, den alle
mit derselben Schrittweite gestartet haben, ist vergleichbar. Ist sie aktiv,
steht es im Fenstertitel.

---

## 9. Was geprüft ist, und was nicht

Ehrlichkeit über die Grenzen gehört zu einem Simulationswerkzeug.

**Verifiziert: das *E.-coli*-Modell.** Gegen einen Referenzlauf der
MATLAB-Anwendung. Über die Batch-Phase stimmen Biomasse, Substrat, pH und
Temperatur auf ≤ 1,5·10⁻⁶ überein, das Flüssigvolumen auf 5,5·10⁻¹⁴. Der
Vergleich reicht bis in die Fed-Batch-Phase und deckt damit auch den
Exponentialfeed und einen Phasenübergang ab. Einzelheiten und die Begründung,
warum es dafür ein Zeitfenster und keine globale Toleranz geben kann, stehen in
[`verifikation_escherichia_coli.md`](verifikation_escherichia_coli.md).

**Nicht verifiziert: das *Pichia*-Modell.** Der einzige verfügbare Referenzlauf
ist 14 Monate älter als die Modellquelle und reproduziert deren kLa-Formel
nicht. Die Übersetzung folgt der Quelle zeilengenau und ist über Struktur- und
Plausibilitätstests abgesichert — aber das ist keine Verifikation, und sie wird
auch nicht als solche ausgegeben.

**Ungeprüft im Einzelnen:** `Mode_pH` = Manual, `Mode_temp` = Manual und
`Mode_pO2` = Aeration / Gasmix / Feed. Der Referenzlauf benutzt sie nicht. Der
Pulsfeed ist nur strukturell getestet.

**Bekannte Eigenheit:** Einige Zeitreihen werden gerechnet, aber nicht
gespeichert. Die Abgasanteile heißen im Modell `xO2` und `xCO2` und haben in
`variableTab` gar keine Zeile — was dort steht, sind `xOG`, `xCG`, `xOGin` und
`xOL`. Was keine Zeile hat, wird nicht geschrieben, und ein fortgesetzter Lauf
startet diese Größen bei ihrem Anfangswert neu. Das betrifft ODE-Zustände,
ist also nicht kosmetisch; die Anwendung schreibt beim Öffnen eines
fortgesetzten Projekts in den Log, welche Größen davon betroffen sind.

---

## 10. Wenn etwas nicht funktioniert

| Beobachtung | Wahrscheinliche Ursache |
|---|---|
| Nichts wächst | nicht beimpft — `Inoculate` |
| Der Feed-Regler tut nichts | `f_feed` steht auf aus |
| Ein Regler stellt nicht | Modus steht auf **Manual** |
| Ein Sollwert lässt sich nicht ändern | Parameter wird nur beim ersten Schritt gelesen (`reading_rate` = `once`) |
| Das Fenster ist breiter als der Bildschirm | Control Options rollt; oder eine schmalere Anordnung in `control_options.yaml` |
| Der pH bewegt sich kaum | Totband von 0,1 pH |

Das **Log** ist die erste Anlaufstelle. Es protokolliert Phasenübergänge,
Parameteränderungen und Fehler mit Uhrzeit und Prozesszeit. Der Filter
„Include operations" blendet zusätzlich ein, was mit der Anwendung selbst
gemacht wurde — Plot geöffnet, Prozess pausiert.
