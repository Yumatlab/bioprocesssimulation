# MATLAB-Referenzläufe

Diese Dateien sind die Absicherung, dass die Python-Portierung dasselbe
rechnet wie die MATLAB-Anwendung (Projektplan §0.3, §2.4). Erzeugt werden sie
von `extract.py`; die CSVs sind eingecheckt, das Skript braucht man nur zum
Neubauen.

Eine MATLAB-Lizenz war nicht verfügbar. Beide Läufe stammen deshalb aus
Material, das bereits vorlag.

## Bestand

| Datei | Inhalt |
|---|---|
| `ecoli_reference.csv.gz` | 43 Variablen, 2983 Schritte, dt = 2 s |
| `ecoli_reference_p.csv` | Parametersatz (`app.p`), `name,value` |
| `ecoli_reference_meta.csv` | `deltat`, `steps`, `projectID`, Inokulationsschritt |
| `pichia_reference.csv.gz` | 51 Variablen, 14 799 Schritte, dt = 2,16 s, 7 Phasen |
| `pichia_reference_p.csv` | Parametersatz des Laufs |
| `pichia_reference_meta.csv` | wie oben, plus `batch_end_step` |

## E. coli — gültig und in Benutzung

Quelle ist `MyProject_11.txt`, ein Export, den die Anwendung selbst
geschrieben hat (27. April 2026). `Escherichia_coli.m` ist vom 22. April
2026 — der Lauf stammt also vom selben Code.

Der Export enthält **keinen Parametersatz**. Verwendet wird der von Projekt
716 der mitgelieferten Datenbank: jeder Startwert des Laufs stimmt exakt
überein, bis hin zu `pG` = `pGcal` + `deltapGw`·10⁵ = 200000 und dem Sprung
der Rührerdrehzahl von 400 auf 450 = 0,3 · `NStmax`, der unteren Begrenzung
des pO2-Reglers. Die Übereinstimmung auf 1e-09 in den ersten Schritten
bestätigt die Wahl.

**Verglichen wird bis Schritt 402.** Danach beginnt im Lauf eine Fed-Batch-
Phase, und Phase 2 hat keinen Phasenautomaten — ab dort simulieren die beiden
Läufe verschiedene Experimente. Gemessen über Schritte 0–402:

| Größe | rel. Abweichung |
|---|---|
| `cXL`, `cS1L`, `pHL`, `thetaL` | ≤ 1,5e-06 |
| `VL` | 5,5e-14 |
| `pHLm`, `thetaLm`, `pO2m` | ≤ 1e-11 |
| `pO2`, `kLa`, `OTR`, `RQ` | absolut ≤ 2,2e-01 |

Die schnelle Sauerstoffschleife bekommt eine absolute Schranke, weil ihre
Größen durch null gehen und eine relative dort bedeutungslos wird.

Der Lauf deckt ab: beide pH-Pumpenrichtungen, den Rührwerksregler über
400–1306 rpm, Acetatbildung, Fütterung. Nicht abgedeckt: reine O₂/N₂/CO₂-
Begasung, Antischaum, Ernte, Glycerin.

## Pichia — vorhanden, aber nicht verwendbar

Quelle ist `Thesis_SimulationAppDB.db` (Stand der Abgabe, 2. März 2025),
Projekt 520. Der Lauf selbst ist ausgezeichnet: 8,2 h, beide Reservoirs, die
vollständige AOX-Induktions- und Expressionskette, sieben Phasen
(Batch → Fed-Batch → Puls-Feed → Produktionsphase → Puls-Feed 2 →
Produktion 2 → Methanol-Toxizitätstest).

**Er verifiziert die aktuelle Quelle trotzdem nicht.**
`Pichia_pastoris.m` ist vom 22. April 2026, also **14 Monate jünger** als der
Lauf. Nachweisbar an `kLa`: die Formel der aktuellen Quelle reproduziert die
Werte des Laufs nicht, obwohl die Übersetzung ihr zeilengenau folgt. Ein
Abweichen würde also über die Übersetzung nichts aussagen.

Der zugehörige Test ist deshalb `skip`, nicht `xfail` — er ist nicht
fehlgeschlagen, er ist nicht anwendbar. Sobald ein Pichia-Lauf aus der
aktuellen Quelle vorliegt, wird er scharf; die Fixture bleibt bis dahin
liegen und ist ohnehin der natürliche Test für den Phasenautomaten aus
Phase 3.

### Eine Eigenheit des Pichia-Parametersatzes

`project_parameterTab` hat in der Thesis-Datenbank **doppelte Zeilen** für
`yXpOgr`, `yCpO` und `qOpXm` — den richtigen Wert zuerst, einen verirrten
danach. MATLABs `loadPhases` schreibt in einer Schleife und lässt die spätere
Zeile gewinnen, hat also mit 40,0 / 15,0 / 0,5 gerechnet statt mit
1,773 / 1,375 / 0,0117. `extract.py` bildet das nach: der Parametersatz gibt
wieder, womit MATLAB tatsächlich gerechnet hat, nicht was richtig gewesen
wäre. Für einen Referenzlauf ist das die einzig brauchbare Wahl.

Das ist zugleich der Beleg für die fehlende `UNIQUE (projectID, parameterID)`
aus Plan §1.1.

## Wenn wieder MATLAB zur Verfügung steht

Am wertvollsten wäre **ein Pichia-Lauf aus der aktuellen Quelle**. Das
Exportskript unten schreibt alles Nötige, auch Parametersatz und Metadaten,
die dem vorhandenen E.-coli-Export fehlen.

```matlab
%% Referenzlauf exportieren
outdir = fullfile(pwd, 'reference_export');
if ~exist(outdir, 'dir'); mkdir(outdir); end
prefix = 'pichia';                     % für E. coli: 'ecoli'

% --- 1) Zeitreihen: alle Felder von app.v, ohne Preallokations-NaNs -----
n     = app.nxtidx;
names = fieldnames(app.v);
keep  = false(numel(names), 1);
M     = nan(n, numel(names));
for i = 1:numel(names)
    col = app.v.(names{i});
    if isnumeric(col) && numel(col) >= n
        M(:, i) = col(1:n).';
        keep(i) = true;
    end
end
names = names(keep);
M     = M(:, keep);

fid = fopen(fullfile(outdir, [prefix '_reference.csv']), 'w');
fprintf(fid, '%s\n', strjoin(names(:).', ','));
fmt = [repmat('%.17g,', 1, numel(names) - 1) '%.17g\n'];
fprintf(fid, fmt, M.');
fclose(fid);

% --- 2) Parameter (app.p) und Hilfsgrößen (app.a) ----------------------
for src = {'p', 'a'}
    s   = app.(src{1});
    fn  = fieldnames(s);
    fid = fopen(fullfile(outdir, sprintf('%s_reference_%s.csv', prefix, src{1})), 'w');
    fprintf(fid, 'name,value\n');
    for i = 1:numel(fn)
        val = s.(fn{i});
        if (isnumeric(val) || islogical(val)) && isscalar(val)
            fprintf(fid, '%s,%.17g\n', fn{i}, double(val));
        end
    end
    fclose(fid);
end

% --- 3) Metadaten -------------------------------------------------------
fid = fopen(fullfile(outdir, [prefix '_reference_meta.csv']), 'w');
fprintf(fid, 'key,value\n');
fprintf(fid, 'projectID,%d\n', app.projectID);
fprintf(fid, 'deltat,%.17g\n', app.a.deltat);
fprintf(fid, 'steps,%d\n', n);
fclose(fid);

fprintf('Referenzlauf exportiert nach %s\n', outdir);
```

Ein reiner Batch-Lauf genügt für Phase 2.4. Für Phase 3 ist ein Lauf mit
Phasenwechseln wertvoller — der Pichia-Lauf oben zeigt, wie so etwas aussieht.
