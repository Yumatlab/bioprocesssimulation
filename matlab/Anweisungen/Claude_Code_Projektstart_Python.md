# Claude Code: Projektstart Python-Migration

---

## Vorbereitung, bevor du Claude Code öffnest

1. Leeren Ordner anlegen, z. B. `biofermentation_sim/`
2. `Projektplan_Python_Migration.md` und `CLAUDE.md` (aus der vorherigen Session) dort hineinlegen
3. Die aktuelle `SimulationAppDB.db` hineinkopieren
4. Falls vorhanden: einen MATLAB-Referenzlauf als CSV (E. coli, alle Variablen) — falls noch nicht exportiert, ist das der erste Auftrag an Claude Code selbst, dich durch den Export in MATLAB anzuleiten
5. In diesem Ordner `claude` starten

`CLAUDE.md` muss vor dem Kickoff-Prompt einmal aktualisiert werden — sie beschreibt aktuell die MATLAB-Architektur als Ist-Zustand. Für das neue Projekt beschreibt sie stattdessen die MATLAB-Architektur als **Referenz für die Portierung**. Das ist im Prompt unten mit adressiert.

---

## Kickoff-Prompt

```
Ich starte ein neues Projekt: eine vollständige Neuimplementierung meiner
MATLAB-Bioreaktor-Simulationssoftware in Python. Kein Zeitdruck, Hobby-Tempo.

Kontext liegt bereit:
- CLAUDE.md beschreibt die MATLAB-Architektur, die als fachliche Referenz dient
  (Datenmodell, Phasenautomat, Regler-Logik, Preallokations-Prinzip)
- Projektplan_Python_Migration.md ist der Phasenplan, an den wir uns halten
- SimulationAppDB.db ist die produktive Datenbank, die unverändert weiterverwendet wird

Zielarchitektur: Python 3.11+, PySide6 für die GUI, pyqtgraph für Live-Plots,
scipy für die ODE-Integration, sqlite3 (Standardbibliothek) für die Datenbank.
Zielplattformen: Windows und macOS, verteilt als einzelne ausführbare Datei
über PyInstaller.

Zentrale Anforderung: Neue Mikroorganismusmodelle müssen sich ohne Eingriff
in bestehenden Code hinzufügen lassen. Der Projektplan beschreibt dafür eine
Plugin-Registry plus eine optionale YAML-Konfigurationsebene für reine
Parameterdefinitionen.

Fang mit Phase 0 aus dem Projektplan an:

1. Lies CLAUDE.md und Projektplan_Python_Migration.md vollständig
2. Lege die Repository-Struktur aus Abschnitt 0.1 des Plans an
3. Richte pyproject.toml mit den genannten Abhängigkeiten ein
   (pyside6, pyqtgraph, scipy, numpy, pytest, ruff)
4. Initialisiere git, erstelle eine sinnvolle .gitignore für Python/Qt
5. Kopiere SimulationAppDB.db nach src/biofermentation/resources/
6. Erstelle eine neue CLAUDE.md für dieses Python-Repository, die auf die
   alte MATLAB-CLAUDE.md als fachliche Referenz verweist, aber den
   Python-spezifischen Stand beschreibt (Verzeichnisstruktur, Konventionen,
   aktueller Phasenfortschritt)

Bevor du Code schreibst: Wenn dir für Phase 0 etwas fehlt oder unklar ist,
frag nach statt zu raten. Ich habe noch keinen MATLAB-Referenzlauf als CSV
exportiert — sag mir, welche Variablen und welches Format du dafür brauchst,
dann exportiere ich das aus MATLAB und lege es in tests/reference_data/ ab.

Am Ende von Phase 0: kurze Zusammenfassung was steht, und was der erste
Schritt von Phase 1 (Datenschicht) wäre.
```

---

## Wie du Claude Code für dieses Projekt am besten führst

### Ein Claude-Code-Lauf pro Phase, nicht pro Frage

Die neun Phasen aus dem Plan sind bewusst so geschnitten, dass jede ein abgeschlossenes, testbares Ergebnis liefert. Starte jede Phase als eigene Konversation:

```
/clear
Wir sind jetzt bei Phase 2 aus Projektplan_Python_Migration.md.
Phase 0 und 1 sind abgeschlossen, siehe CLAUDE.md für den aktuellen Stand.
Fang mit Abschnitt 2.1 an: die OrganismModel-Basisklasse.
```

Das hält den Kontext klein und den Fortschritt nachvollziehbar.

### Bei den testbaren Phasen (0–3): Claude Code eigenständig verifizieren lassen

Für Datenschicht, Kern und Phasenautomat gilt: bitte explizit darum, nach jeder Änderung `pytest` laufen zu lassen und erst weiterzumachen, wenn es grün ist.

```
Schreibe die load_phases-Funktion, dann einen Test dafür, führe pytest aus
und zeig mir das Ergebnis, bevor du weitermachst.
```

Das ist der Bereich, in dem Claude Code am wenigsten Rückfragen von dir braucht — nutze das aus, indem du größere, in sich abgeschlossene Aufträge gibst statt einzelner Funktionen.

### Bei der ODE-Übersetzung (Phase 2.4): Referenzdaten zuerst verlangen

Bevor eine Zeile Python-ODE-Code entsteht, sollte der Referenzlauf vorliegen. Sag das explizit:

```
Bevor du Escherichia_coli.m übersetzt: prüfe ob tests/reference_data/
ecoli_reference.csv existiert. Falls nicht, sag mir welches Format und
welche Spalten du brauchst, bevor du mit der Übersetzung anfängst.
```

Eine Übersetzung ohne Referenz zu beginnen ist der teuerste Fehler, den man hier machen kann — jede Zeile müsste sonst später nochmal geprüft werden.

### Bei den GUI-Phasen (4–6): Screenshots sind das Werkzeug, nicht Beschreibungen

Claude Code sieht keine Fenster. Wenn ein Layout nicht stimmt, ist ein Screenshot mit einer kurzen Anmerkung effizienter als eine Beschreibung in Worten — das hat sich bereits in der MATLAB-Session so gezeigt (der Screenshot des kaputten Phasen-Grids hat den Fehler sofort sichtbar gemacht, eine Textbeschreibung hätte länger gedauert).

Praktischer Ablauf für ein neues Fenster:

1. Claude Code baut das Fenster
2. Du startest es lokal (`python -m biofermentation.gui.app` oder ähnlich)
3. Screenshot zurück an Claude Code, mit „das hier stimmt nicht: ..."
4. Iterieren, bis es passt

### Wiederkehrender Fehler in MATLAB, der sich in Python leicht vermeiden lässt

In der MATLAB-Session sind mehrfach Bugs entstanden, weil eine Datenbankverbindung nicht geschlossen wurde oder eine Transaktion verschachtelt war. Bitte Claude Code, von Anfang an konsequent den Context-Manager aus Abschnitt 1.2 des Plans zu verwenden (`with get_connection(...) as conn:`) statt manuellem `open`/`close`. Wenn du irgendwo `sqlite3.connect(` ohne `with` im Code siehst, ist das ein Hinweis, das anzusprechen.

### CLAUDE.md nach jeder Phase aktualisieren lassen

Am Ende jeder Phase:

```
Aktualisiere CLAUDE.md: aktueller Stand, was in dieser Phase fertig wurde,
was in der nächsten ansteht, und trage neue Konventionen ein, die wir
gerade festgelegt haben.
```

Das hält den Einstieg in die nächste Phase günstig, weil du nicht den ganzen Verlauf neu erklären musst.

### Wann du selbst eingreifen solltest statt zu delegieren

- MATLAB-Referenzläufe exportieren — das kann nur in MATLAB passieren
- Visuelle Feinabstimmung der GUI — Layout, Abstände, Farben nach Geschmack
- Code-Signing-Zertifikate besorgen, falls du dich später dafür entscheidest
- Entscheidung, wann eine Phase „fertig genug" ist, um weiterzugehen

### Kosten niedrig halten

Die gleichen Prinzipien wie zuvor gelten hier verstärkt, weil das Projekt größer ist:

- `/clear` zwischen Phasen, nicht nur zwischendurch
- Claude Code liest Dateien selbst per `grep`/`find` — sag *was* zu tun ist, nicht *wo genau*, wenn du es nicht auswendig weißt
- Große generierte Dateien (z. B. eine vollständige `FigureApp`-Portierung) in Unterschritten verlangen, nicht auf einmal — dann bleibt jeder Turn klein und du kannst zwischendurch abbrechen, falls die Richtung nicht passt
