# Biofermentation Simulation

Simulation von Bioreaktorprozessen (Batch, Fed-Batch, Induktion) für
verschiedene Mikroorganismen. Pro Zeitschritt werden Regler (pO2, pH,
Temperatur, Füllstand), Fütterung und Stoffbilanzen gerechnet; ein
Phasenautomat schaltet Prozessphasen anhand konfigurierbarer Start- und
Endbedingungen weiter.

Dieses Repository enthält **zwei Fassungen derselben Anwendung**.

| Ordner | Fassung | Stand |
|---|---|---|
| [`matlab/`](matlab/) | MATLAB App Designer | Version 2.2, der Stand der Masterarbeit (Tag `v2.2`) |
| [`python/`](python/) | Python, PySide6 | Version 3.0, die Neuimplementierung |

Sie stehen nebeneinander, nicht übereinander: die MATLAB-Fassung ist die
Vorlage, aus der portiert wurde, und bleibt als solche lesbar und lauffähig.

**Die Python-Fassung ist die, die weiterentwickelt wird.** Sie rechnet dieselbe
Simulation — das *Escherichia-coli*-Modell ist gegen einen Referenzlauf der
MATLAB-Anwendung verifiziert, nachzulesen in
[`python/docs/verifikation_escherichia_coli.md`](python/docs/verifikation_escherichia_coli.md).
Was sie zusätzlich kann und woran sie anders gebaut ist, steht in
[`python/CLAUDE.md`](python/CLAUDE.md).

## Womit anfangen

- **Anwenden**: fertige Installationsdateien für Windows und macOS hängen an
  jedem Release. Einrichtung und bekannte Einschränkungen in
  [`python/docs/installation.md`](python/docs/installation.md).
- **Entwickeln**: `python/README.md` beschreibt die Entwicklungsumgebung und
  wie ein neues Organismusmodell entsteht.
- **Nachvollziehen, wie es gebaut ist**: `python/CLAUDE.md` ist der lange Text
  dazu — Datenmodell, Reglerlogik, Datenbankregeln und jede Entscheidung, die
  nicht selbsterklärend war.

## Lizenz

Die Python-Fassung steht unter der MIT-Lizenz, siehe
[`python/LICENSE`](python/LICENSE). Die MATLAB-Anwendung steht unter
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/); sie führt die Arbeit
der Vorentwicklerin **Lena Sophia Kaletsch** fort (Version 1.3, 01.03.2024)
und beruht auf dem BIOSIM-Programm von Prof. Dr.-Ing. R. Luttmann. Entwickelt
für das Labor für Bioprozessautomatisierung der HAW Hamburg.
