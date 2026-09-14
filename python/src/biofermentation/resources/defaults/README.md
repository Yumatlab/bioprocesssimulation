# Default-Datensatz als CSV

Referenzdaten der Anwendung: alles, was zum Laufen gebraucht wird, aber nicht
zu einem einzelnen Projekt gehört — Parameter- und Variablendefinitionen,
Lookup-Tabellen, Defaultwerte je Bioreaktor, je Organismus und je Modell.

Zweck: Wiederaufbau. Ist die Datenbank leer oder verloren, stellt
`load_defaults()` diesen Stand her. Weil es Textdateien sind, taucht die
Änderung eines Defaultwerts außerdem im Diff auf.

**Projektdaten sind nicht enthalten** — `projectTab`, `project_parameterTab`,
`processTab`, `process_parameterTab`, `timeTab`, `dataTab`, `logTab`. Das sind
Anwenderdaten, keine Defaults.

## Verwendung

```python
from biofermentation.db.seed import export_defaults, load_defaults

load_defaults("SimulationAppDB.db")  # CSV -> DB, Reihenfolge FK-sicher
export_defaults("SimulationAppDB.db")  # DB -> CSV, nach Pflege der Werte
```

`load_defaults` verweigert den Dienst, solange Projekte in der Datenbank
liegen: die Referenztabellen sind deren Elterntabellen, ein Leeren würde per
`ON DELETE CASCADE` die Projektdaten mitnehmen. `force=True` hebt das auf.

## Dateiformat

Eine Datei pro Tabelle, benannt wie die Tabelle. Kopfzeile mit den
Spaltennamen, danach eine Zeile pro Datensatz. UTF-8, LF, minimales Quoting.

`\N` steht für NULL, ein leeres Feld für den leeren String. Diese
Unterscheidung ist nötig, weil beides vorkommt: `parameterTab.unit` enthält
bei dimensionslosen Parametern `''`, bei anderen NULL. Die Konvention ist von
PostgreSQL `COPY` übernommen.

Die Ladereihenfolge steht in `db/seed.py` als `DEFAULT_TABLES` und ist so
sortiert, dass jede Tabelle nach ihren Referenzzielen kommt. Der Datensatz
lässt sich damit in eine leere Datenbank mit `PRAGMA foreign_keys = ON`
einspielen.

## Herkunft und Stand

Exportiert aus `SimulationAppDB_template.db` nach der Schema-Migration
(Plan §1.1). 23 Tabellen, 2203 Zeilen. Die Datenbank ist die maßgebliche
Quelle, nicht die Excel: `additional_files/Parameter Overview.xlsx` war die
Erstbefüllung, ist aber an mehreren Stellen überholt (siehe unten).

## Abweichungen Excel gegen Datenbank

Beim Abgleich gefunden. Grundregel: **die Datenbank gilt.** Sie ist der
gepflegte Stand, die Excel die Erstbefüllung. Einzige Ausnahme sind die
Bioreaktoren — die wurden damals nicht zu Ende gepflegt, weil der Fokus auf
den Organismen lag und die Reaktoren sich kaum unterschieden. Dort gilt die
Excel.

1. **`parameterID` verschiebt sich bei 105 von 316 Parametern.** Die Excel
   führt eigene IDs, die Datenbank hat später umnummeriert. Die IDs der
   Datenbank gelten; die Excel-IDs sind als Referenz unbrauchbar.
2. **BIOSTAT B: behoben.** Der Reaktor trug bei sechs Parametern die Werte
   des BIOSTAT ED und acht seiner Zeilen fehlten ganz. `migrate_schema.sql`
   korrigiert das jetzt aus der Excel, Blatt `bioreactors`, Spalte `BBI_ED`:
   `FnAIRmax` 20 → 10, `FnGmax` 27 → 17, `FT1max`/`FT2max` 0,5 → 1,
   `mdotCmax` 1500 → 150, `mdotHmax` 1500 → 6; ergänzt `PHmax` (2000 W gegen
   10000 W beim ED), `VH`, `rhoH`, `rhoH2O`, `rhoL`, `thetaCin`, `thetaHin`,
   `thetaU`. Beide Reaktoren haben nun 60 Zeilen. Der BIOSTAT ED stimmte
   bereits in allen 54 vergleichbaren Werten mit der Excel überein.

   Sechs Parameter der Datenbank kommen im Blatt gar nicht vor und bleiben
   unverändert: `VLmax`, `VLmin`, `VT10`, `VT20`, `kLamax`, `kLamin`. Das
   Blatt schreibt `lamda` statt `lambda`; die Zuordnung erfolgt über einen
   Alias. `FRmax` aus dem Blatt hat kein Ziel — die Datenbank hat es durch
   `FR1max`/`FR2max`/`FR3max` ersetzt, drei Reservoirs statt einer Pumpe.
3. **Fünf Kinetikwerte von Pichia weichen ab**, die Datenbank gilt:
   `my1opt` 0,219 → 0,4, `my2opt` 0,1 → 0,01, `yXpOgr` 1,773 → 40, `yCpO`
   1,375 → 15, `qOpXm` 0,0117 → 0,5 (Excel → Datenbank). Die Excel-Werte sind
   überholt und wurden nicht übernommen.
4. **`process_typeTab` und `process_statusTab` der Excel sind veraltet.** Das
   Blatt `Process Tables` beschreibt einen früheren Entwurf mit
   `Process_phaseTab` und `Process_conditionTab`, Typen `Costum`/`Batch`/
   `Fed-Batch`/`Pulse-Feed` und drei Status. Die Datenbank hat fünf Typen
   (`Manual`, `Stop`, `Update Parameter Set`, `Pulse Feed`, `Exponential
   Feed`) und vier Status. Nicht übernommen.
5. **Das Blatt `Model Properties` führt als zweiten Organismus „Bacillus
   academii".** Die Werte in dieser Spalte sind aber zu 218 von 223 die von
   Pichia pastoris. Die Überschrift ist irreführend; das separate Blatt
   `Bacillus properties` gehört zu einem Organismus, den die Datenbank nicht
   kennt. Nicht übernommen — sinnvoll erst mit der Plugin-Registry aus
   Phase 2.
6. **Vier Variablen der Excel fehlen in `variableTab`:** `xCGin`, `FR1j`,
   `FR2j`, `FR3j`. `FR1j`–`FR3j` sind Schreibvarianten der vorhandenen `FR1`
   bis `FR3`; `xCGin` (CO2-Anteil im Zulauf) hat mit `xOGin` ein Gegenstück in
   der Datenbank und fehlt dort tatsächlich.
7. **Grenzwerte `min_limit`/`max_limit` werden nicht übernommen.** Die Excel
   führt sie zu 308 der 320 Parameter, 326 Einträge über beide Organismen.
   `parameterTab` hat dafür keine Spalten. Als irrelevant eingestuft und
   verworfen — bewusst, nicht übersehen.
8. **Blatt `Assisting properties`, 55 Namen**, ist in keiner Tabelle
   abgebildet. Das ist die Inventarliste des Hilfsgrößen-Containers `a`
   (`ApH`, `cOLmax`, `CHmax`, …) und gehört nach Phase 2, nicht in die
   Datenbank.

Übereinstimmend und damit bestätigt: `categoryTab` (19 Zeilen),
`parameter_controlmodesTab` (13), die E.-coli-Defaults (189 von 189
vergleichbaren Werten) und die BIOSTAT-ED-Defaults (54 von 54).
