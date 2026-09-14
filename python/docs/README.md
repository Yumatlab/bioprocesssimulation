# Dokumentation

Fünf Dokumente, je eines pro Frage.

| Sie wollen… | Lesen Sie |
|---|---|
| die Anwendung **bedienen** | [`handbuch.md`](handbuch.md) |
| sie **installieren** oder verteilen | [`installation.md`](installation.md) |
| wissen, wie sie **gebaut** ist | [`architektur.md`](architektur.md) |
| sie **weiterentwickeln** | [`weiterentwicklung.md`](weiterentwicklung.md) |
| wissen, ob die **Zahlen stimmen** | [`verifikation_escherichia_coli.md`](verifikation_escherichia_coli.md) |

Dazu, eine Ebene höher: [`../CLAUDE.md`](../CLAUDE.md) — *warum* die Anwendung
so gebaut ist, wie sie gebaut ist. Jede Regel mit ihrer Begründung und jede
Messung mit ihrer Zahl. Das ist die Datei, die ein KI-Assistent zuerst liest,
und die, in die neue Erkenntnisse gehören.

## Einstieg in zehn Minuten

1. [`installation.md`](installation.md) → Anwendung starten
2. [`handbuch.md`](handbuch.md), Abschnitt 2 → erstes Projekt anlegen,
   beimpfen, laufen lassen
3. [`handbuch.md`](handbuch.md), Abschnitt 4 → die fünf Regler verstehen

Wer danach weitermachen will, nimmt
[`weiterentwicklung.md`](weiterentwicklung.md) — dort steht auch der fertige
Startprompt für eine Version 4 mit Claude Code.

## Als PDF

Für alle, die lieber auf Papier oder im Reader lesen:

```bash
pip install -e ".[docs]"
python tools/make_pdfs.py
```

Das legt `docs/pdf/` an — je ein gesetztes PDF mit Seitenzahlen, 31 Seiten
zusammen. Gesetzt wird mit Chrome im Hintergrund; fehlt es, weicht das
Werkzeug auf Qt aus und sagt es. Die PDFs liegen nicht im Repository: sie sind
jederzeit neu erzeugbar, und als Binärdateien in der Historie wären sie nur
Rauschen.
