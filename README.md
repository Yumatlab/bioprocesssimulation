# Biofermentation Simulation

Simulation von Bioreaktorprozessen (Batch, Fed-Batch, Induktion) für
verschiedene Mikroorganismen. Python-Portierung der MATLAB-App-Designer-
Anwendung Version 2.x.

Pro Zeitschritt werden Regler (pO2, pH, Temperatur, Füllstand), Fütterung und
Stoffbilanzen berechnet; ein Phasenautomat schaltet Prozessphasen anhand
konfigurierbarer Start- und Endbedingungen weiter.

## Stand

Phase 0 (Fundament) abgeschlossen. Der Simulationskern entsteht ab Phase 2.
Der aktuelle Fortschritt steht in `CLAUDE.md`.

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
