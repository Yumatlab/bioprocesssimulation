# Biofermentation Simulation

Simulation von Bioreaktorprozessen (Batch, Fed-Batch, Induktion) für
verschiedene Mikroorganismen. Python-Portierung der MATLAB-App-Designer-
Anwendung Version 2.x.

Pro Zeitschritt werden Regler (pO2, pH, Temperatur, Füllstand), Fütterung und
Stoffbilanzen berechnet; ein Phasenautomat schaltet Prozessphasen anhand
konfigurierbarer Start- und Endbedingungen weiter.

## Stand

Version 3.0 — die Portierung ist funktionsfertig. Phasen 0 bis 7 abgeschlossen
(Datenschicht, Simulationskern, Phasenautomat, Oberfläche, Plot-Engine,
Verteilung); Phase 8, das Handbuch, ist offen. Das E.-coli-Modell ist gegen
einen MATLAB-Referenzlauf verifiziert (`docs/verifikation_escherichia_coli.md`),
das Pichia-Modell bewusst nicht — die Begründung steht dort ebenfalls.

Der aktuelle Fortschritt und alle offenen Punkte stehen in `CLAUDE.md`.

## Entwicklungsumgebung

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Struktur

```
src/biofermentation/
  db/          Datenbankzugriff (Phase 1)
  core/        Simulationszustand, Preallokation, Runner (Phase 2/4)
  organisms/   Organismusmodelle + Plugin-Registry (Phase 2)
  control/     Phasenautomat und Regler (Phase 3)
  gui/         PySide6-Oberfläche (Phasen 4-6)
  resources/   SimulationAppDB_template.db
tests/         pytest, inklusive MATLAB-Referenzläufe
build/         PyInstaller-Spec-Dateien (Phase 7)
docs/          Handbuch (Phase 8)
```

## Neues Organismusmodell

Zwei Wege, beide ohne Eingriff in bestehenden Code:

- **Nur Parameter:** `definition.yaml` im Organismus-Ordner anlegen; ein
  Import-Skript befüllt die Parametertabellen der Datenbank.
- **Neue Kinetik:** Unterklasse von `OrganismModel` schreiben und mit
  `@register` versehen. Die Registry findet sie beim Start automatisch.

Details in `docs/` (Phase 8), Schnittstelle in `src/biofermentation/organisms/base.py`.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

Die Portierung stammt von der MATLAB-Anwendung Version 2.2 ab, die unter
[CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) steht. Diese führt
die Arbeit der **Vorentwicklerin Lena Sophia Kaletsch** fort, von der Version
1.3 der Biofermentation Simulation App stammt (01.03.2024), und beruht
ihrerseits auf dem BIOSIM-Programm von Prof. Dr.-Ing. R. Luttmann. Diese
Namensnennung steht in `LICENSE` und im Info-Tab der Anwendung und muss jede
Kopie begleiten.

Eine **gepackte** Fassung enthält zusätzlich Qt über PySide6 unter der LGPLv3.
Wer sie weitergibt, übernimmt deren Pflichten; siehe
`docs/installation.md`.
