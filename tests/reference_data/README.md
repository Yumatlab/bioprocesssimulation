# MATLAB-Referenzläufe

Diese Dateien sind die einzige Absicherung, dass die Python-Portierung
dasselbe rechnet wie die MATLAB-Anwendung (Projektplan §0.3). Ohne sie ist
jede spätere Abweichung nicht mehr nachweisbar — deshalb entsteht **kein**
ODE-Code in Phase 2.4, bevor mindestens `ecoli_reference.csv` hier liegt.

## Erwartete Dateien

| Datei | Inhalt |
|---|---|
| `ecoli_reference.csv` | Zeitreihen eines vollständigen E.-coli-Laufs, alle `app.v`-Felder |
| `ecoli_reference_p.csv` | Parametersatz des Laufs (`app.p`), `name,value` |
| `ecoli_reference_a.csv` | Hilfs-/Reglergrößen (`app.a`), skalare Felder, `name,value` |
| `ecoli_reference_meta.csv` | `projectID`, `deltat`, Schrittzahl |
| `pichia_reference*.csv` | dasselbe für Pichia pastoris |

## Format

Komma-separiert, Punkt als Dezimaltrennzeichen, eine Kopfzeile mit den
`app.v`-Feldnamen (`cXL`, `cS1L`, `pO2`, `pHL`, `thetaL`, `VL`, …) — **ohne**
die Einheiten-Suffixe des App-Exports (`cXL in g/l`), damit die Spalten direkt
auf die Feldnamen im Code abbilden. Zahlen mit `%.17g`, damit die volle
double-Genauigkeit erhalten bleibt; `NaN` ist zulässig und wird von pandas
korrekt gelesen.

Der bestehende Export der App (`MyProject_11.txt`, 43 Spalten) hat das
richtige Format, deckt aber nur einen Teil der Variablen ab und enthält
weder Parametersatz noch Metadaten. Deshalb das Skript unten.

## Welcher Lauf

Am wertvollsten ist ein Lauf, der **mindestens einen Phasenwechsel und
aktives Feeding** enthält — dann validiert derselbe Datensatz die ODE (Phase
2.4) und den Phasenautomaten (Phase 3). Ein reiner Batch-Lauf reicht für
Phase 2.4 aus, lässt aber die Umschaltlogik ungeprüft.

## Export aus MATLAB

Im laufenden `ControlApp` ausführen (das `app`-Objekt muss im Workspace
liegen, z. B. über einen Haltepunkt in einer Callback-Funktion):

```matlab
%% Referenzlauf exportieren
outdir = fullfile(pwd, 'reference_export');
if ~exist(outdir, 'dir'); mkdir(outdir); end
prefix = 'ecoli';                      % für Pichia: 'pichia'

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

Die vier Dateien aus `reference_export/` anschließend in dieses Verzeichnis
kopieren.

Die Phasenkonfiguration des Laufs muss nicht exportiert werden — sie wird
über die `projectID` aus `processTab` / `process_parameterTab` der
mitgelieferten Datenbank gelesen.
