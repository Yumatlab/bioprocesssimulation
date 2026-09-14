# Architektur

Wie die Anwendung gebaut ist — für alle, die den Quellcode lesen oder ändern.

Dieses Dokument ist ein **Wegweiser**, keine vollständige Beschreibung. Die
Begründungen für jede nicht offensichtliche Entscheidung stehen in
[`../CLAUDE.md`](../CLAUDE.md), und zwar ausführlich. Sie hier zu wiederholen
hieße, zwei Texte zu pflegen, die nach der dritten Änderung
auseinanderlaufen. Was hier steht, ist die Landkarte; `CLAUDE.md` ist das
Reisetagebuch.

---

## 1. Die fünf Pakete

```
src/biofermentation/
├── db/           3 700 Zeilen   Datenbankzugriff
├── core/           650 Zeilen   Zustand, Preallokation, Runner
├── organisms/    3 150 Zeilen   Basisklasse, Registry, die Modelle
├── control/        540 Zeilen   Phasenautomat
└── gui/          9 550 Zeilen   PySide6-Oberfläche
```

Die Abhängigkeiten laufen in **eine** Richtung: `gui` kennt alle, `control`
kennt `core`, `organisms` kennt `core`, `core` kennt nichts von den anderen,
`db` kennt nur sich selbst und die Datenklassen.

**Zwei Regeln, die diese Richtung schützen:**

`core/runner.py` läuft ohne Oberfläche und ohne PySide6. Nur
`core/simulation_runner.py` importiert Qt, und `core/__init__.py` zieht es
nicht mit herein. Ein Referenzlauf oder ein Test darf nie eine
GUI-Abhängigkeit brauchen.

Fenster öffnen keine Fenster. Jedes meldet über ein Signal, was der Anwender
wollte; `gui/app.py` entscheidet, was aufgeht. Nur so ist ein Fenster einzeln
testbar.

---

## 2. Das Datenmodell: `p`, `v`, `a`

Aus MATLAB übernommen, samt Namen — und das ist Absicht, weil jeder Vergleich
mit dem Referenzlauf sonst unlesbar würde.

| | Was darin liegt | Gespeichert? |
|---|---|---|
| **`p`** | Parameter: Sollwerte, Konstanten, Modi, Flags | ja, `project_parameterTab` |
| **`v`** | Zeitreihen: je Variable ein numpy-Array über alle Schritte | ja, `dataTab`/`timeTab` |
| **`a`** | Hilfsgrößen und Reglerzustände | **nein** |

Alle drei sind `Namespace` — eine `MutableMapping` mit Attributzugriff, sodass
`state.p.pHw` und `state.p["pHw"]` dasselbe sind. Das erlaubt Formeln, die wie
die MATLAB-Vorlage aussehen, und gleichzeitig Schlüssel, die zur Laufzeit aus
Namen gebaut werden (`p[f"FR{n}max"]`).

> **`a` wird nicht gespeichert** — und das ist die Quelle mehrerer Fehler
> gewesen. Wer etwas in `a` legt, das einen Neustart überleben muss, muss es
> beim Laden aus `v` oder `p` rekonstruieren. Der Abschnitt „Ein wieder
> geöffnetes Projekt ist schon beimpft" in `CLAUDE.md` erzählt, wie das schief
> ging.

**Die Fachnotation bleibt wörtlich:** `cXL`, `cS1L`, `qXpX`, `NSt`, `kLa`,
`thetaL`. Die `pep8-naming`-Regeln sind dafür in `pyproject.toml` bewusst
abgeschaltet.

---

## 3. Ein Zeitschritt

`OrganismModel.calculate_step(state)` rechnet **einen** Schritt. Der Index
`prev = state.idx` ist der letzte gerechnete, `i = prev + 1` der neue.

```
ensure_capacity(i)      Arrays verdoppeln, wenn nötig
_feeding                Fütterung: exponentiell, Puls, pO2-geregelt, PID
_po2_control            Rührer / Begasung / Gasmischung
_aeration               Gaszusammensetzung am Einlass
_liquid_weight          Füllstand und Ernte
_antifoam               Antischaum
_ph_control             pH-Kaskade
_temperature_control    Doppelmantel
_volume                 Verdünnungsraten DR1, DT1, DT2
ode_luttmann            18 Bilanzen, gelöst mit LSODA
_growth, _ph_iteration  Kinetik und pH-Gleichgewicht
carry_forward           was nicht neu gerechnet wurde, wird fortgeschrieben
```

Drei Eigenheiten, die man kennen muss:

**Preallokation.** Zeitreihen wachsen nicht elementweise. `ensure_capacity`
verdoppelt die Arrays; `np.append` je Schritt wäre O(n²) und kostete über
20 000 Schritte 7,3 s statt 0,25 µs pro Schritt.

**NaN heißt „nicht gerechnet".** Ein Preallokationsslot ist NaN, bis jemand
hineinschreibt. `carry_forward` füllt am Ende jedes Schritts die Reihen, die
das Modell nicht angefasst hat. Vor jedem Datenbankschreiben werden NaN-Slots
herausgefiltert — **NaN wird nie geschrieben**, denn MATLAB schrieb dort 0,
und aus „nicht gemessen" wurde so eine gemessene Null.

**MATLAB-Eigenheiten sind wörtlich übersetzt.** Wo das Original bei `idx`
schreibt und im nächsten Ausdruck `idx-1` liest, steht im Code
`# MATLAB lag`. Es gibt genau **vier** bewusste Ausnahmen, alle in der
Begasung, alle außerhalb des verifizierten Fensters, alle einzeln
nachgemessen. Sie stehen in `CLAUDE.md` mit Begründung und Messwert.

---

## 4. Organismen als Plugins

Ein Organismusmodell ist ein Ordner unter `organisms/` mit einer Klasse, die
von `OrganismModel` erbt und `@register` trägt. `discover_organisms()` findet
sie über `pkgutil.iter_modules` — **niemand importiert sie beim Namen**.

Die Basisklasse verlangt vier Initialisierungsschritte und einen Rechenschritt:

```python
init_controller_states(state)   # PID-Zustände und Flags
init_physical_constants(state)  # Kessel: Wärme, Henry, pH
init_kinetics(state)            # Wachstum, Aufnahme, Ausbeuten
init_variables(state)           # Startwerte bei t = 0, nur für einen frischen Lauf
calculate_step(state)           # ein Zeitschritt
```

Was beide mitgelieferten Organismen gemeinsam haben, steht in
`organisms/shared.py`. Was sie unterscheidet, steht in ihrer eigenen Datei —
und **die beiden sind bewusst nicht vereinheitlicht**: Pichias MATLAB-Quelle
ist eine spätere Revision mit anderen Reglerabgriffen. Jede Datei ist die
Referenz für ihren Organismus.

> **Achtung beim Verteilen:** Weil die Registry über `pkgutil` sucht, sieht
> PyInstallers Importanalyse die Plugins nicht. Jedes braucht einen Eintrag in
> `build/specs.py`. Fehlt einer, startet die gebaute Anwendung **ohne
> Fehlermeldung** mit leerer Organismusliste. `tests/test_packaging.py`
> vergleicht die Liste gegen `discover_organisms()`.

---

## 5. Der Phasenautomat

`control/phases.py`. Drei Einstiegspunkte, und der Runner ruft sie in dieser
Reihenfolge:

```python
started = automaton.check_start(state)   # vor dem Block: Phase beginnen?
...                                       # die Schritte des Blocks
ended = automaton.check_end(state)        # nach dem Block: Phase beenden?
```

`check_start` wendet die Parameter der Phase an **und gibt danach** den Index
zurück; der Runner sendet erst dann sein Signal. Wer auf „eine Phase hat
etwas geändert" reagieren will, darf sich also darauf verlassen, dass die
Werte schon in `p` stehen.

`adopt_active_phase()` ist der Ladeweg: der Zustand des Automaten steht in
`processTab`, und ohne diesen Aufruf startet ein geladenes Projekt seine
laufende Phase neu.

`drain_log()` gibt die Meldungen zurück, die der Automat geschrieben hat — er
kann kein Qt-Signal senden, weil `control/` frei von Qt bleibt.

`PHASE_PARAMETERS` sagt, welche Parameter ein Phasentyp anbietet. Die Tabelle
steht absichtlich neben den Handlern, die sie lesen.

---

## 6. Die Datenbank

SQLite, `sqlite3` aus der Standardbibliothek, kein ORM.

**Zwei Zugriffe pro Sitzung.** Einmal lesen beim Öffnen (`load_phases`,
`load_project_state`), einmal schreiben am Ende (`save_project`). Während der
Simulation kein Datenbankzugriff; alle Editoren arbeiten auf dem Speicher.

**Die Regeln, die nicht verhandelbar sind:**

- Immer `with get_connection(path) as conn:` — nie `sqlite3.connect(` ohne
  Context-Manager, nie eine globale Verbindung.
- Ein Block, eine Verbindung, **eine** Transaktion. `get_connection` öffnet
  `BEGIN` und schließt mit `COMMIT` oder `ROLLBACK`.
- **Das Kaskadieren macht SQLite.** Kein Nachbauen von Hand, und unter keinen
  Umständen `PRAGMA foreign_keys = OFF`.
- Sicherungskopien über die **sqlite3-Backup-API**, nie `shutil.copy` — im
  WAL-Modus lebt eine committete Transaktion zunächst nur im WAL, und eine
  Dateikopie ohne WAL verliert sie.

Diese Regeln sind keine Stilfrage. Die produktive Datenbank der
MATLAB-Version ist an ihrer Verletzung zugrunde gegangen: von 733 Projekten
sind 14 übrig, von 11,3 Millionen Datenzeilen keine einzige. Die Forensik
dazu steht in `CLAUDE.md` unter „Anforderung an Phase 5".

**Der Wiederaufbaupfad** ist `resources/defaults/` — 23 CSVs plus
`load_defaults()` / `export_defaults()`. Projektdaten sind nicht enthalten.

---

## 7. Die Oberfläche

`gui/` ist das größte Paket und in drei Ebenen geteilt:

| | |
|---|---|
| `windows/` | die Fenster: Startbildschirm, Projektauswahl, ControlApp, FigureApp, DataTable |
| `widgets/` | die Bausteine: Regelpanels, Phasenraster, Plot, Variable Pool, Log |
| `dialogs/` | Phasen-, Parameter-, Plot-, Export- und Bibliotheksdialoge |

**Jeder Schreibzugriff läuft durch `runner.editing()`.** Ein Sollwert, der
geändert wird, während ein Timer-Tick mitten im Schritt steht, ist genau der
Fall, für den das Guard-Flag existiert.

**Drei Textdateien statt Code** — das Muster ist überall dasselbe: eine
mitgelieferte Vorgabe unter `resources/`, eine gleichnamige Datei neben der
Datenbank schlägt sie, und eine kaputte Datei nimmt nie etwas weg, sondern
liefert die Vorgabe plus einen Grund für den Log.

| Datei | Steuert |
|---|---|
| `styles/default.qss` | Farben, Abstände, Schriften |
| `layouts/control_options.yaml` | Anordnung der Panels, Art der Modusauswahl |
| `settings.yaml` | sichtbare Tabs, Studierendenansicht |

Qt hat Fallen, und dieses Projekt ist in die meisten davon einmal getreten.
Sie sind in `CLAUDE.md` gesammelt — gestylte Comboboxen, `clicked(bool)`,
`isVisible()`, kosmetische Stifte, `findData` mit einem `IntEnum`. Wer an der
Oberfläche arbeitet, liest den Abschnitt „UX-Durchgang" einmal ganz.

---

## 8. Tests

```bash
pytest                     # alles, rund 70 Sekunden
pytest tests/test_organisms.py -q    # nur die Modelle
ruff check .               # Lint
```

Aktuell **567 Tests**, ein übersprungener und ein erwarteter Fehlschlag.

**Drei Regeln:**

Gegen eine **Kopie der echten Datenbank** testen, nicht gegen Mocks. Das
Template liegt in `resources/`, jede Fixture kopiert es in ein Temp-Verzeichnis.

**Kein ODE-Code ohne vorliegenden Referenzlauf.** Die Vergleichstests
überspringen sich, solange die CSV fehlt — ein Test, der ohne Referenz grün
ist, beweist nichts.

**Ein modaler Dialog in einer Fixture ist ein hängender Testlauf.**
`conftest.py` beantwortet den Schließdialog zentral mit „verwerfen". Das ist
zweimal passiert, bevor es dort stand.

Der `xfail(strict=True)` in `test_organisms.py` ist kein vergessener Fehler,
sondern eine festgehaltene Unstimmigkeit der Datenbank: `variable_handlingTab`
passt zu keinem der beiden Modelle. Solange das so ist, **muss** der Test
fehlschlagen; repariert jemand die Tabelle, schlägt er nicht mehr fehl und
meldet sich als `XPASS`.

---

## 9. Bauen und Verteilen

| Was | Wie |
|---|---|
| Entwickeln | `pip install -e ".[dev]"`, dann `python -m biofermentation.gui.app` |
| Verknüpfung auf den Quellbaum | `python tools/make_launcher.py` |
| Einzeldatei für die Verteilung | `pyinstaller --noconfirm build/macos.spec` bzw. `build/windows.spec` |
| Beides zugleich | GitHub Actions, auf einen `v*`-Tag oder auf Zuruf |

**Cross-Compiling gibt es bei PyInstaller nicht.** Eine Windows-`.exe`
entsteht nur auf Windows; dafür ist die CI-Matrix da.

Einzelheiten und die bekannten Einschränkungen stehen in
[`installation.md`](installation.md).

---

## 10. Wo was zu finden ist

| Frage | Datei |
|---|---|
| Warum ist das so gebaut? | `../CLAUDE.md` |
| Stimmen die Zahlen? | `verifikation_escherichia_coli.md` |
| Wie bediene ich das? | `handbuch.md` |
| Wie entwickle ich weiter? | `weiterentwicklung.md` |
| Wie installiere ich das? | `installation.md` |
| Woher kommen die Vorgabewerte? | `../src/biofermentation/resources/defaults/README.md` |
| Woher kommen die Referenzläufe? | `../tests/reference_data/README.md` |
