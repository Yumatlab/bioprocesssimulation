# Weiterentwicklung

Für die Person, die diese Software übernimmt.

Dieses Dokument setzt voraus, dass Sie Bioverfahrenstechnik können und
Programmieren nicht unbedingt. Es führt Sie bis zu dem Punkt, an dem Sie mit
Hilfe von **Claude Code** — einem KI-Assistenten, der in Ihrem Terminal
arbeitet und Dateien lesen und schreiben kann — eine Version 4 entwickeln
können. Der fertige Startprompt steht in Abschnitt 5.

Eines vorweg, weil es den Ton des ganzen Dokuments bestimmt: **Sie müssen
nicht jede Zeile verstehen, um verantwortlich zu ändern.** Sie müssen wissen,
was Sie prüfen können und was nicht. Dafür ist Abschnitt 6 da, und das ist der
wichtigste Abschnitt hier.

---

## 1. Einrichten

### Was Sie brauchen

| | Wozu |
|---|---|
| **Python 3.11 oder neuer** | die Sprache, in der die Anwendung geschrieben ist |
| **Git** | verwaltet die Versionen des Quellcodes |
| **Ein Terminal** | „Terminal" auf macOS, „PowerShell" auf Windows |

Python von [python.org](https://www.python.org/downloads/), Git von
[git-scm.com](https://git-scm.com/downloads). Beide mit den Vorgaben
installieren.

### Den Quellcode holen

```bash
git clone git@github.com:Yumatlab/bioprocesssimulation.git
cd bioprocesssimulation/python
```

Das Repository enthält zwei Ordner: `matlab/` mit der ursprünglichen
MATLAB-Anwendung (Version 2.2) und `python/` mit dieser hier. Sie arbeiten in
`python/`.

### Die Umgebung aufsetzen

```bash
python3.11 -m venv ../.venv
source ../.venv/bin/activate          # Windows: ..\.venv\Scripts\activate
pip install -e ".[dev]"
```

Eine **virtuelle Umgebung** (`venv`) ist ein abgeschlossener Ordner mit einer
eigenen Python-Installation und eigenen Paketen. Damit stört dieses Projekt
kein anderes und umgekehrt. Das `source …/activate` schaltet sie ein; im
Terminal steht danach `(.venv)` vor der Eingabezeile. Bei jedem neuen
Terminalfenster wieder aktivieren.

### Prüfen, dass alles steht

```bash
pytest
```

Erwartet: **567 passed, 1 skipped, 1 xfailed** in gut einer Minute. Läuft das
durch, ist Ihre Umgebung in Ordnung — und Sie haben nebenbei bewiesen, dass
die Anwendung auf Ihrem Rechner richtig rechnet.

`1 skipped` und `1 xfailed` sind **kein Fehler**. Der übersprungene Test
bräuchte einen Pichia-Referenzlauf, den es nicht gibt; der erwartete
Fehlschlag hält eine bekannte Unstimmigkeit der Datenbank fest. Beide erklären
sich selbst, wenn Sie `pytest -rsx` aufrufen.

### Starten

```bash
python -m biofermentation.gui.app
```

Oder unter macOS eine Verknüpfung in `~/Applications` anlegen:

```bash
python tools/make_launcher.py
```

---

## 2. Wie Sie sich zurechtfinden

Lesen Sie in dieser Reihenfolge:

1. **[`handbuch.md`](handbuch.md)** — was die Anwendung kann. Erst bedienen,
   dann ändern.
2. **[`architektur.md`](architektur.md)** — wie sie gebaut ist, auf zehn
   Seiten.
3. **[`../CLAUDE.md`](../CLAUDE.md)** — *warum* sie so gebaut ist. Lang, aber
   die wichtigste Datei im Projekt.

`CLAUDE.md` ist kein gewöhnliches Dokument. Es ist die Datei, die Claude Code
**automatisch liest**, bevor es irgendetwas tut. Darin steht jede Regel, jede
Falle und jede Messung, die dieses Projekt teuer gelernt hat. Wenn Sie etwas
Grundsätzliches ändern, gehört die Begründung dort hinein — sonst geht sie
verloren, und der nächste Mensch macht denselben Fehler noch einmal.

---

## 3. Womit Sie arbeiten, ohne zu programmieren

Vieles lässt sich ohne eine Zeile Code ändern. Prüfen Sie zuerst, ob Ihr
Vorhaben dazugehört:

| Vorhaben | Weg |
|---|---|
| Neuer Organismus mit anderen Werten | **Library → Organisms… → New from selected…**, dann **Make selectable…** |
| Neuer Bioreaktor | **Library → Bioreactors…**, genauso |
| Andere Anordnung der Regelpanels | `control_options.yaml` neben der Datenbank |
| Andere Farben, Schriften, Abstände | `style.qss` neben der Datenbank |
| Tabs ausblenden, Studierendenansicht | **Settings…** auf dem Startbildschirm |
| Neue Diagrammvorlage | **Plots → Open plot from template** |

**Die Grenze verläuft an der Kinetik.** Andere Zahlen sind Daten; andere
Bilanzgleichungen sind ein Programm. Eine Kopie von *E. coli* mit anderen
Ausbeutekoeffizienten ist ein Formular. Ein Organismus mit
Produktinhibierung, die es bisher nicht gibt, ist Code.

---

## 4. Wie Sie mit Claude Code arbeiten

Claude Code läuft im Terminal, im Projektordner. Es liest `CLAUDE.md` selbst
und kennt damit die Regeln des Projekts, bevor Sie etwas sagen.

**Drei Gewohnheiten, die den Unterschied machen:**

**Sagen Sie, was Sie erreichen wollen — nicht, wie.** „Der Feed-Regler
schwingt bei niedrigen Sollwerten, finde heraus warum" führt zu besseren
Ergebnissen als „ändere KP_feedR1 auf 5". Die Frage ist Ihr Beitrag, die
Fehlersuche seiner.

**Verlangen Sie Messungen statt Behauptungen.** Dieses Projekt hat die
Gewohnheit, Aussagen zu belegen: „gemessen 1174 px gegen 1538", „RMS 8,3 auf
2,0". Fragen Sie nach der Zahl, wenn keine kommt. Eine Änderung ohne Messung
ist eine Vermutung.

**Lassen Sie nach jeder Änderung `pytest` laufen.** Nicht am Ende — nach
jeder. 567 Tests in einer Minute sind billig; eine Woche später
herauszufinden, welche von zwanzig Änderungen etwas kaputtgemacht hat, ist es
nicht.

**Und eine Warnung:** Prüfen Sie, was geändert wurde. `git diff` zeigt es
Ihnen. Sie sind verantwortlich für das, was Sie committen, auch wenn es jemand
anderes geschrieben hat.

---

## 5. Der Startprompt für Version 4

Kopieren Sie diesen Text in Claude Code, wenn Sie beginnen. Passen Sie den
letzten Absatz an Ihr Vorhaben an.

```text
Ich übernehme die Weiterentwicklung der Biofermentation Simulation und
beginne Version 4. Mein Hintergrund ist Pharmazeutische Biotechnologie,
nicht Informatik — erkläre mir technische Entscheidungen so, dass ich sie
beurteilen kann, und frage nach, wenn eine fachliche Entscheidung ansteht,
die nur ich treffen kann.

Lies zuerst CLAUDE.md vollständig. Dort stehen die Regeln dieses Projekts,
die Fallen, in die es schon getreten ist, und die Messwerte hinter jeder
Entscheidung. Lies danach docs/architektur.md für die Landkarte und
docs/verifikation_escherichia_coli.md dafür, was an diesem Modell geprüft
ist und was nicht.

Diese Regeln sind nicht verhandelbar:

1. Das Escherichia-coli-Modell ist gegen einen MATLAB-Referenzlauf
   verifiziert. Jede Änderung am Simulationskern wird gegen diesen Lauf
   geprüft, bevor sie bleibt: pytest tests/test_organisms.py. Weicht der
   Lauf ab, sag es mir mit Zahlen, statt die Toleranz zu lockern.
2. Datenbankzugriffe: immer `with get_connection(path) as conn:`, ein
   Block, eine Verbindung, eine Transaktion. Niemals
   `PRAGMA foreign_keys = OFF`. Das Kaskadieren macht SQLite. Die
   produktive Datenbank der MATLAB-Version ist an der Verletzung dieser
   Regeln zugrunde gegangen; die Forensik steht in CLAUDE.md.
3. Sicherungskopien über die sqlite3-Backup-API, nie über shutil.copy.
4. Der MATLAB-Code unter matlab/ ist Lesequelle. Er wird nicht verändert.
5. Kein neuer ODE-Code ohne einen Referenzlauf, gegen den er prüfbar ist.
   Ein Test, der ohne Referenz grün ist, beweist nichts.
6. Nach jeder Änderung läuft pytest. Erst weitermachen, wenn es grün ist.
7. Code-Kommentare und Docstrings auf Englisch, Antworten an mich auf
   Deutsch.

Arbeitsweise, die ich erwarte:

- Belege Aussagen mit Messungen. Wenn du sagst, etwas sei schneller,
  besser oder kaputt, nenne die Zahl und wie du sie gemessen hast.
- Ändere nicht mehr als nötig. Kleine, nachvollziehbare Commits mit einer
  Begründung, die sagt WARUM, nicht was.
- Wenn du eine Annahme triffst, sag sie mir, statt sie zu verstecken.
- Wenn etwas nicht geht, sag das. Ein ehrliches "das trägt nicht" ist mir
  lieber als eine Lösung, die im Testlauf grün ist und im Betrieb nicht.
- Trage neue Erkenntnisse in CLAUDE.md nach — dort, wo sie hingehören.

Offene Punkte stehen am Ende von CLAUDE.md unter "Offen aus Phase …".
Sieh sie dir an und sag mir, welche du für die wichtigsten hältst.

Mein erstes Vorhaben für Version 4 ist: <HIER IHR VORHABEN EINTRAGEN>.
Erkläre mir zuerst, was das berührt und was dabei schiefgehen kann, bevor
du anfängst.
```

### Warum dieser Prompt so aussieht

Jeder Absatz hat einen Grund, und die meisten sind teuer bezahlt:

**„Lies zuerst CLAUDE.md"** — ohne das fängt jede Sitzung bei null an und
wiederholt gelöste Probleme.

**Die sieben Regeln** sind die, deren Verletzung in diesem Projekt schon
Schaden angerichtet hat. Regel 2 hat eine Datenbank mit 11,3 Millionen
Datenzeilen gekostet.

**„Belege Aussagen mit Messungen"** — das ist der wirksamste einzelne Satz.
Er verwandelt „das sollte jetzt besser sein" in „RMS 8,3 auf 2,0, gemessen an
Projekt 716".

**„Sag deine Annahmen"** — eine versteckte Annahme ist ein Fehler, der später
teurer wird.

**„Erkläre zuerst, was das berührt"** — bei einer Simulation, deren Zahlen
verifiziert sind, ist der Umfang einer Änderung wichtiger als ihre Eleganz.

---

## 6. Wie Sie eine Änderung absichern

Das ist der Abschnitt, den Sie behalten sollten.

### Die drei Fragen vor jeder Änderung

1. **Berührt sie den Simulationskern?** Also `organisms/`, `core/` oder
   `control/`. Wenn ja: Der Referenzlauf ist Ihre Absicherung, und er muss
   vorher und nachher laufen.
2. **Berührt sie die Datenbank?** Also `db/` oder das Schema. Wenn ja: gegen
   eine **Kopie** arbeiten, nie gegen das Original, und `PRAGMA
   foreign_key_check` hinterher.
3. **Berührt sie nur die Oberfläche?** Dann ist das Risiko klein — aber
   Layoutzusagen halten nur auf dem System, auf dem Sie sie gemessen haben.

### Messen, ändern, wieder messen

Die Regel lautet nicht „teste danach", sondern: **erst die Zahl, dann die
Änderung.** Ein Beispiel aus diesem Projekt, das Sie nachvollziehen können:

Der Feed-Regler traf einen Sollwert nicht. Statt Verstärkungen zu raten,
wurde das Projekt auf einer Kopie der Datenbank gerechnet:

```
ohne Anti-Windup   cS1L = 2.377 bei Sollwert 3,  I-Anteil -13.4
mit  Anti-Windup   cS1L = 3.005,                 I-Anteil   0.277
```

Erst diese beiden Zeilen rechtfertigen die Änderung. Ohne sie wäre es eine
Meinung gewesen.

### Ein neuer Organismus: der Weg

1. Ordner unter `src/biofermentation/organisms/` anlegen.
2. Klasse von `OrganismModel` ableiten, `@register` darüber.
3. Die vier Initialisierungsmethoden und `calculate_step` schreiben.
4. **Eintrag in `build/specs.py`** — sonst fehlt der Organismus in der
   gebauten Anwendung, ohne jede Fehlermeldung.
5. Datenbankzeilen über `db/definitions.py` anlegen oder importieren.
6. Ein **Modell** anlegen (Organismus × Kessel), sonst ist er nicht wählbar.
7. Einen Referenzlauf beschaffen und die Vergleichstests schreiben.

Schritt 7 ist der, den man weglassen möchte, und der, ohne den die anderen
sechs wertlos sind.

### Was Ihnen niemand abnimmt

Die Anwendung kann prüfen, ob sie dasselbe rechnet wie gestern. Sie kann
**nicht** prüfen, ob das Modell die Biologie richtig beschreibt. Das ist Ihre
Aufgabe, und dafür sind Sie ausgebildet.

---

## 7. Fallen, die schon zugeschnappt sind

Alle ausführlich in `CLAUDE.md`; hier die, über die man am ehesten stolpert.

| Falle | Merksatz |
|---|---|
| `a` wird nicht gespeichert | Was einen Neustart überleben muss, gehört in `p` oder `v` — oder muss beim Laden rekonstruiert werden |
| Ein Plugin ohne Eintrag in `build/specs.py` | Die gebaute Anwendung startet mit leerer Organismusliste, ohne Fehler |
| Ein Test, der eine undeklarierte Bibliothek importiert | Läuft auf Ihrem Rechner und auf keinem anderen |
| Pixelgenaue Layoutzusagen | Halten nur bei Ihrer Schriftart |
| `findData` mit einem `IntEnum` | Liefert −1; `widgets.select_data()` benutzen |
| Ein modaler Dialog in einer Test-Fixture | Der Testlauf hängt, ohne Meldung |
| NaN in die Datenbank schreiben | Aus „nicht gemessen" wird eine gemessene Null |

---

## 8. Was offen ist

Am Ende von `CLAUDE.md` stehen die offenen Punkte, nach Phasen sortiert. Die,
die ich für eine Version 4 zuerst ansehen würde:

**Fachlich:**

- **Pichia ist nicht verifiziert.** Es fehlt ein Referenzlauf aus der
  aktuellen MATLAB-Quelle. Solange der fehlt, ist jede Aussage über die
  Pichia-Zahlen unbelegt.
- **`variable_handlingTab` passt zu keinem der beiden Modelle.** Sieben
  E.-coli-Zeitreihen werden gerechnet und nie gespeichert, darunter
  ODE-Zustände. Ein fortgesetzter Lauf startet sie neu.
- **Ungeprüfte Regelmodi**: `Mode_pH` = Manual, `Mode_temp` = Manual,
  `Mode_pO2` = Aeration / Gasmix / Feed. Der Referenzlauf benutzt sie nicht.

**Technisch:**

- **Anti-Windup ist halb fertig.** Der Reglerbaustein und die vier
  Datenbankparameter (`f_awpO2`, `f_awtemp`, `f_awLW`, `f_awfeed`) sind da und
  wirken; die Bedienelemente im Reglerdialog und in den Settings fehlen, und
  das Pichia-Modell ist noch nicht verdrahtet.
- **`PhaseFeedEditor`** aus der MATLAB-Version ist nicht portiert.
- **Zwei Plot-Einstellungen wirken nicht**: `axisyoffset` und
  `axisylabeloffsetabove`/`-below`.

---

## 9. Wenn Sie nicht weiterkommen

**Der Log ist die erste Anlaufstelle** — in der Anwendung, und bei einem Start,
der gar nicht erst zu einem Fenster führt, unter `/tmp/biofermentation-launch.log`
(macOS).

**`git diff` zeigt, was Sie geändert haben.** `git stash` legt es beiseite,
wenn Sie zurück auf einen funktionierenden Stand wollen. `git log --oneline`
zeigt, was vorher geschah — die Commit-Nachrichten dieses Projekts erklären
absichtlich das *Warum*, nicht das Was.

**Und wenn etwas kaputtgeht:** Jeder Speichervorgang legt eine
Sicherungskopie neben der Datenbank an (`SimulationAppDB.backup.db`). Das
mitgelieferte Template lässt sich jederzeit neu ausrollen, indem Sie die
Arbeitsdatenbank umbenennen — die Anwendung legt beim nächsten Start eine
frische Kopie an.
