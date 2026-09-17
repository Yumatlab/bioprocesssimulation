-- Schema migration for SimulationAppDB (plan section 1.1).
--
-- The MATLAB version left three defects in the schema and one in the
-- bioreactor defaults. This script repairs them in place, on any database
-- that still carries the 2.x schema:
--
--   1. MATCH SIMPLE is stripped from every foreign key. SQLite parses the
--      clause and then ignores it, so this is cosmetic in SQLite itself, but
--      it keeps the schema portable and stops it from suggesting a matching
--      rule that is not in force.
--   2. project_parameterTab gets UNIQUE (projectID, parameterID). Duplicates
--      there once blocked the creation of Pichia projects.
--   3. processTab.start_typeID and end_typeID are retargeted from
--      process_typeTab to process_conditiontypeTab. The columns hold
--      condition types (1, 2 for start; 6, 7 for end), not process types,
--      which produced twelve foreign key violations on end_typeID; the start
--      values happened to fall into both id ranges and stayed invisible.
--   4. The BIOSTAT B carries the BIOSTAT ED's values in
--      default_bioreactorTab for six parameters, and eight of the ED's rows
--      are missing for it altogether. The bioreactors were never finished in
--      the database while the focus was on the organisms; the spreadsheet
--      additional_files/Parameter Overview.xlsx has the correct values and
--      wins here. It is the only place where it does — everywhere else the
--      database is authoritative.
--
-- SQLite cannot alter a foreign key in place, so every affected table is
-- rebuilt following the documented ALTER TABLE procedure
-- (https://sqlite.org/lang_altertable.html#otherkinds):
-- foreign keys off, rebuild inside one transaction, verify, commit.
--
-- legacy_alter_table = ON keeps ALTER TABLE ... RENAME from rewriting
-- references in other objects and from re-parsing the "Variable Table" view,
-- which does not survive the window in which dataTab is absent.
--
-- The script is idempotent: rerunning it rebuilds the same tables from
-- themselves and changes nothing.
--
-- A fifth defect is repaired next to this script rather than in it: logTab
-- is missing the event type and the process time that belong to every entry,
-- and both are added by migrate.apply_migration(). They are ALTER TABLE ...
-- ADD COLUMN, which SQLite cannot make conditional and this file cannot
-- branch on — rebuilding the table instead would drop the two columns again
-- on the next run. See migrate.py, LOG_COLUMNS.
--
-- Usage:
--   python -c "from biofermentation.db import apply_migration; \
--              apply_migration('SimulationAppDB.db')"
--
-- Running the script on its own repairs defects 1 to 4 but not 5:
--   sqlite3 SimulationAppDB.db < migrate_schema.sql
--   sqlite3 SimulationAppDB.db "PRAGMA foreign_key_check;"   -- must be empty
--
-- Take a backup first. Test on a copy before touching a production database.

PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

BEGIN;

-- AUTOINCREMENT counters live in sqlite_sequence and are dropped along with
-- their table. They run far ahead of the current MAX(id) here (dataTab is at
-- 11307627 with no rows left), so they are saved and restored explicitly —
-- letting them fall back to MAX(id) would hand out ids that older exports and
-- the production database still use.
CREATE TEMP TABLE _seq_backup AS SELECT name, seq FROM sqlite_sequence;


-- ---------------------------------------------------------------- dataTab --
DROP TABLE IF EXISTS _mig_dataTab;
CREATE TABLE _mig_dataTab (
    dataID     INTEGER NOT NULL UNIQUE PRIMARY KEY AUTOINCREMENT,
    variableID INTEGER NOT NULL REFERENCES variableTab (variableID) ON DELETE CASCADE ON UPDATE CASCADE,
    timeID     INTEGER REFERENCES timeTab (timeID) ON DELETE CASCADE,
    value      REAL
);
INSERT INTO _mig_dataTab (dataID, variableID, timeID, value)
    SELECT dataID, variableID, timeID, value FROM dataTab;
DROP TABLE dataTab;
ALTER TABLE _mig_dataTab RENAME TO dataTab;


-- ---------------------------------------------------- default_bioreactorTab --
DROP TABLE IF EXISTS _mig_default_bioreactorTab;
CREATE TABLE _mig_default_bioreactorTab (
    default_bioreactorID INTEGER PRIMARY KEY UNIQUE NOT NULL,
    bioreactorID         INTEGER REFERENCES bioreactorTab (bioreactorID) ON DELETE CASCADE ON UPDATE CASCADE,
    parameterID          INTEGER REFERENCES parameterTab (parameterID) ON DELETE CASCADE ON UPDATE CASCADE,
    value                REAL,
    description          TEXT
);
INSERT INTO _mig_default_bioreactorTab (default_bioreactorID, bioreactorID, parameterID, value, description)
    SELECT default_bioreactorID, bioreactorID, parameterID, value, description FROM default_bioreactorTab;
DROP TABLE default_bioreactorTab;
ALTER TABLE _mig_default_bioreactorTab RENAME TO default_bioreactorTab;


-- --------------------------------------------------------- default_modelTab --
DROP TABLE IF EXISTS _mig_default_modelTab;
CREATE TABLE _mig_default_modelTab (
    default_modelparameterID INTEGER NOT NULL UNIQUE PRIMARY KEY AUTOINCREMENT,
    organismID               INTEGER NOT NULL REFERENCES organismTab (organismID),
    parameterID              INTEGER REFERENCES parameterTab (parameterID),
    value                    REAL NOT NULL,
    description              TEXT
);
INSERT INTO _mig_default_modelTab (default_modelparameterID, organismID, parameterID, value, description)
    SELECT default_modelparameterID, organismID, parameterID, value, description FROM default_modelTab;
DROP TABLE default_modelTab;
ALTER TABLE _mig_default_modelTab RENAME TO default_modelTab;


-- ------------------------------------------------- default_plot_variableTab --
-- selected_variable and limit_type are declared without a type in the 2.x
-- schema (BLOB affinity). Kept verbatim so stored values keep their type.
DROP TABLE IF EXISTS _mig_default_plot_variableTab;
CREATE TABLE _mig_default_plot_variableTab (
    default_plot_variableID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
    variableID              INTEGER REFERENCES variableTab (variableID) ON DELETE CASCADE ON UPDATE CASCADE,
    selected_variable,
    limit_type,
    ymin                    REAL,
    ymax                    REAL,
    decimalID               INTEGER REFERENCES plot_decimalTab (decimalID) ON DELETE CASCADE ON UPDATE CASCADE,
    colorID                 INTEGER REFERENCES plot_colorTab (colorID) ON DELETE CASCADE ON UPDATE CASCADE,
    linestyleID             INTEGER REFERENCES plot_linestyleTab (linestyleID) ON DELETE CASCADE ON UPDATE CASCADE
);
INSERT INTO _mig_default_plot_variableTab (default_plot_variableID, variableID, selected_variable,
                                           limit_type, ymin, ymax, decimalID, colorID, linestyleID)
    SELECT default_plot_variableID, variableID, selected_variable,
           limit_type, ymin, ymax, decimalID, colorID, linestyleID FROM default_plot_variableTab;
DROP TABLE default_plot_variableTab;
ALTER TABLE _mig_default_plot_variableTab RENAME TO default_plot_variableTab;


-- --------------------------------------------------------------- modelTab --
DROP TABLE IF EXISTS _mig_modelTab;
CREATE TABLE _mig_modelTab (
    modelID      INTEGER PRIMARY KEY UNIQUE NOT NULL,
    bioreactorID INTEGER REFERENCES bioreactorTab (bioreactorID) ON DELETE CASCADE ON UPDATE CASCADE,
    organismID   INTEGER REFERENCES organismTab (organismID) ON DELETE CASCADE ON UPDATE CASCADE,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    display_rank INTEGER
);
INSERT INTO _mig_modelTab (modelID, bioreactorID, organismID, name, description, display_rank)
    SELECT modelID, bioreactorID, organismID, name, description, display_rank FROM modelTab;
DROP TABLE modelTab;
ALTER TABLE _mig_modelTab RENAME TO modelTab;


-- ------------------------------------------------------- model_parameterTab --
DROP TABLE IF EXISTS _mig_model_parameterTab;
CREATE TABLE _mig_model_parameterTab (
    model_parameterID INTEGER NOT NULL UNIQUE,
    modelID           INTEGER REFERENCES modelTab (modelID) ON DELETE CASCADE ON UPDATE CASCADE,
    parameterID       INTEGER REFERENCES parameterTab (parameterID) ON DELETE CASCADE ON UPDATE CASCADE,
    value             REAL NOT NULL,
    description       TEXT,
    PRIMARY KEY (model_parameterID AUTOINCREMENT)
);
INSERT INTO _mig_model_parameterTab (model_parameterID, modelID, parameterID, value, description)
    SELECT model_parameterID, modelID, parameterID, value, description FROM model_parameterTab;
DROP TABLE model_parameterTab;
ALTER TABLE _mig_model_parameterTab RENAME TO model_parameterTab;


-- ----------------------------------------------------------- parameterTab --
DROP TABLE IF EXISTS _mig_parameterTab;
CREATE TABLE _mig_parameterTab (
    parameterID    INTEGER PRIMARY KEY NOT NULL UNIQUE,
    categoryID     INTEGER NOT NULL REFERENCES categoryTab (categoryID) ON DELETE CASCADE ON UPDATE CASCADE,
    name           TEXT NOT NULL UNIQUE,
    tex            TEXT UNIQUE,
    unit           TEXT,
    tex_unit       TEXT,
    type           TEXT DEFAULT editfield NOT NULL,
    internal_order INTEGER,
    external_order INTEGER
);
INSERT INTO _mig_parameterTab (parameterID, categoryID, name, tex, unit, tex_unit,
                               type, internal_order, external_order)
    SELECT parameterID, categoryID, name, tex, unit, tex_unit,
           type, internal_order, external_order FROM parameterTab;
DROP TABLE parameterTab;
ALTER TABLE _mig_parameterTab RENAME TO parameterTab;


-- -------------------------------------------------------- plot_variableTab --
DROP TABLE IF EXISTS _mig_plot_variableTab;
CREATE TABLE _mig_plot_variableTab (
    plot_variableID INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL UNIQUE,
    templateID      INTEGER REFERENCES plot_templateTab (templateID) ON DELETE CASCADE ON UPDATE CASCADE,
    variableID      INTEGER REFERENCES variableTab (variableID) ON DELETE CASCADE ON UPDATE CASCADE,
    selected_axis   INTEGER DEFAULT (0) NOT NULL,
    limit_type      INTEGER DEFAULT (1) NOT NULL,
    ymin            REAL DEFAULT (0) NOT NULL,
    ymax            REAL NOT NULL DEFAULT (10),
    decimalID       INTEGER NOT NULL DEFAULT (1) REFERENCES plot_decimalTab (decimalID) ON UPDATE CASCADE,
    colorID         INTEGER DEFAULT (1) NOT NULL REFERENCES plot_colorTab (colorID) ON UPDATE CASCADE,
    linestyleID     INTEGER NOT NULL DEFAULT (1) REFERENCES plot_linestyleTab (linestyleID) ON UPDATE CASCADE
);
INSERT INTO _mig_plot_variableTab (plot_variableID, templateID, variableID, selected_axis,
                                   limit_type, ymin, ymax, decimalID, colorID, linestyleID)
    SELECT plot_variableID, templateID, variableID, selected_axis,
           limit_type, ymin, ymax, decimalID, colorID, linestyleID FROM plot_variableTab;
DROP TABLE plot_variableTab;
ALTER TABLE _mig_plot_variableTab RENAME TO plot_variableTab;


-- ------------------------------------------------------------- processTab --
-- start_typeID and end_typeID now reference process_conditiontypeTab, which is
-- where the stored values (1, 2 and 6, 7) come from. Defect 3 above.
--
-- Left unchanged deliberately: start_operatorID still references
-- process_conditiontypeTab while its sibling end_operatorID references
-- process_operatorTab, and the stored values (1, 3) are comparison operators.
-- This is the same kind of mistake as end_typeID, but it is outside the scope
-- of this migration and needs a decision before it is changed.
DROP TABLE IF EXISTS _mig_processTab;
CREATE TABLE _mig_processTab (
    processID        INTEGER PRIMARY KEY UNIQUE NOT NULL,
    projectID        INTEGER REFERENCES projectTab (projectID) ON DELETE CASCADE ON UPDATE CASCADE,
    process_statusID INTEGER REFERENCES process_statusTab (process_statusID) ON DELETE CASCADE ON UPDATE CASCADE,
    process_typeID   INTEGER REFERENCES process_typeTab (process_typeID) ON DELETE CASCADE ON UPDATE CASCADE,
    name             TEXT,
    start_typeID     INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID) ON DELETE CASCADE ON UPDATE CASCADE,
    start_variableID INTEGER REFERENCES variableTab (variableID),
    start_operatorID INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
    start_value      REAL,
    start_time       REAL,
    end_typeID       INTEGER REFERENCES process_conditiontypeTab (process_conditiontypeID),
    end_variableID   INTEGER REFERENCES variableTab (variableID),
    end_operatorID   INTEGER REFERENCES process_operatorTab (process_operatorID),
    end_value        REAL,
    end_time         REAL,
    reservoirID      INTEGER
);
INSERT INTO _mig_processTab (processID, projectID, process_statusID, process_typeID, name,
                             start_typeID, start_variableID, start_operatorID, start_value, start_time,
                             end_typeID, end_variableID, end_operatorID, end_value, end_time, reservoirID)
    SELECT processID, projectID, process_statusID, process_typeID, name,
           start_typeID, start_variableID, start_operatorID, start_value, start_time,
           end_typeID, end_variableID, end_operatorID, end_value, end_time, reservoirID FROM processTab;
DROP TABLE processTab;
ALTER TABLE _mig_processTab RENAME TO processTab;


-- ----------------------------------------------------- process_parameterTab --
DROP TABLE IF EXISTS _mig_process_parameterTab;
CREATE TABLE _mig_process_parameterTab (
    process_parameterID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
    processID           INTEGER REFERENCES processTab (processID) ON DELETE CASCADE ON UPDATE SET DEFAULT,
    parameterID         INTEGER REFERENCES parameterTab (parameterID) ON DELETE CASCADE ON UPDATE CASCADE,
    value               REAL
);
INSERT INTO _mig_process_parameterTab (process_parameterID, processID, parameterID, value)
    SELECT process_parameterID, processID, parameterID, value FROM process_parameterTab;
DROP TABLE process_parameterTab;
ALTER TABLE _mig_process_parameterTab RENAME TO process_parameterTab;


-- ------------------------------------------------------ process_variableTab --
DROP TABLE IF EXISTS _mig_process_variableTab;
CREATE TABLE _mig_process_variableTab (
    process_variableID INTEGER PRIMARY KEY UNIQUE NOT NULL,
    organismID         INTEGER REFERENCES organismTab (organismID) ON DELETE CASCADE ON UPDATE CASCADE,
    variableID         INTEGER REFERENCES variableTab (variableID) ON DELETE CASCADE ON UPDATE CASCADE
);
INSERT INTO _mig_process_variableTab (process_variableID, organismID, variableID)
    SELECT process_variableID, organismID, variableID FROM process_variableTab;
DROP TABLE process_variableTab;
ALTER TABLE _mig_process_variableTab RENAME TO process_variableTab;


-- ------------------------------------------------------------- projectTab --
DROP TABLE IF EXISTS _mig_projectTab;
CREATE TABLE _mig_projectTab (
    projectID    INTEGER NOT NULL UNIQUE PRIMARY KEY AUTOINCREMENT,
    name         TEXT UNIQUE,
    description  TEXT,
    author       TEXT,
    created_on   TEXT,
    recent_use   TEXT,
    organismID   INTEGER REFERENCES organismTab (organismID) ON DELETE CASCADE ON UPDATE CASCADE,
    bioreactorID INTEGER REFERENCES bioreactorTab (bioreactorID) ON DELETE CASCADE ON UPDATE CASCADE,
    modelID      INTEGER REFERENCES modelTab (modelID)
);
INSERT INTO _mig_projectTab (projectID, name, description, author, created_on, recent_use,
                             organismID, bioreactorID, modelID)
    SELECT projectID, name, description, author, created_on, recent_use,
           organismID, bioreactorID, modelID FROM projectTab;
DROP TABLE projectTab;
ALTER TABLE _mig_projectTab RENAME TO projectTab;


-- ------------------------------------------------------ variable_handlingTab --
DROP TABLE IF EXISTS _mig_variable_handlingTab;
CREATE TABLE _mig_variable_handlingTab (
    default_variableID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE,
    organismID         INTEGER REFERENCES organismTab (organismID) ON DELETE CASCADE ON UPDATE CASCADE,
    variableID         NUMERIC REFERENCES variableTab (variableID) ON DELETE CASCADE ON UPDATE CASCADE,
    visible            INTEGER NOT NULL DEFAULT (1),
    upload_rate        TEXT DEFAULT cyclic,
    initial_assignment TEXT
);
INSERT INTO _mig_variable_handlingTab (default_variableID, organismID, variableID, visible,
                                       upload_rate, initial_assignment)
    SELECT default_variableID, organismID, variableID, visible,
           upload_rate, initial_assignment FROM variable_handlingTab;
DROP TABLE variable_handlingTab;
ALTER TABLE _mig_variable_handlingTab RENAME TO variable_handlingTab;


-- ----------------------------------------------------- project_parameterTab --
-- Defect 2. Rebuilt unconditionally so the constraint is guaranteed no matter
-- which revision of the schema the database carries. Should duplicates exist,
-- the row with the highest project_parameterID wins — it was written last and
-- therefore holds the most recent value. Rows with a NULL parameterID are not
-- covered by the constraint (SQLite treats NULLs as distinct) and pass through
-- unchanged.
DROP TABLE IF EXISTS _mig_project_parameterTab;
CREATE TABLE _mig_project_parameterTab (
    project_parameterID INTEGER PRIMARY KEY AUTOINCREMENT UNIQUE NOT NULL,
    projectID           INTEGER NOT NULL REFERENCES projectTab (projectID) ON DELETE CASCADE ON UPDATE CASCADE,
    parameterID         INTEGER REFERENCES parameterTab (parameterID),
    value               REAL,
    description         TEXT,
    UNIQUE (projectID, parameterID)
);
INSERT INTO _mig_project_parameterTab (project_parameterID, projectID, parameterID, value, description)
    SELECT project_parameterID, projectID, parameterID, value, description
      FROM project_parameterTab
     WHERE parameterID IS NULL
        OR project_parameterID IN (
               SELECT MAX(project_parameterID) FROM project_parameterTab
                WHERE parameterID IS NOT NULL
                GROUP BY projectID, parameterID
           );
DROP TABLE project_parameterTab;
ALTER TABLE _mig_project_parameterTab RENAME TO project_parameterTab;


-- --------------------------------------------- BIOSTAT B default values --
-- Defect 4. bioreactorID 2 is the BIOSTAT B, bioreactorID 1 the BIOSTAT ED.
-- Six values were left at the ED's figures; the correct ones come from the
-- 'bioreactors' sheet, column BBI_ED. Written by parameter name rather than
-- by id, because the spreadsheet's ids are stale.
UPDATE default_bioreactorTab
   SET value = (
       SELECT v FROM (
           SELECT 'FnAIRmax' AS n,  10.0 AS v UNION ALL
           SELECT 'FnGmax',         17.0    UNION ALL
           SELECT 'FT1max',          1.0    UNION ALL
           SELECT 'FT2max',          1.0    UNION ALL
           SELECT 'mdotCmax',      150.0    UNION ALL
           SELECT 'mdotHmax',        6.0
       ) AS fix
        WHERE fix.n = (SELECT name FROM parameterTab p
                        WHERE p.parameterID = default_bioreactorTab.parameterID))
 WHERE bioreactorID = 2
   AND parameterID IN (SELECT parameterID FROM parameterTab
                        WHERE name IN ('FnAIRmax', 'FnGmax', 'FT1max', 'FT2max',
                                       'mdotCmax', 'mdotHmax'));

-- The eight rows the BIOSTAT B never got. Only PHmax actually differs from
-- the ED (2000 W against 10000 W); the rest matches but was simply absent.
-- default_bioreactorID is an INTEGER PRIMARY KEY, so leaving it out of the
-- column list lets SQLite assign the next free id.
INSERT INTO default_bioreactorTab (bioreactorID, parameterID, value, description)
SELECT 2, p.parameterID, missing.value,
       (SELECT d.description FROM default_bioreactorTab d
         WHERE d.bioreactorID = 1 AND d.parameterID = p.parameterID)
  FROM (
      SELECT 'PHmax' AS n, 2000.0 AS value UNION ALL
      SELECT 'VH',            0.0003      UNION ALL
      SELECT 'rhoH',          1.6831      UNION ALL
      SELECT 'rhoH2O',      998.2         UNION ALL
      SELECT 'rhoL',          1.0         UNION ALL
      SELECT 'thetaCin',     15.0         UNION ALL
      SELECT 'thetaHin',    134.0         UNION ALL
      SELECT 'thetaU',       25.0
  ) AS missing
  JOIN parameterTab p ON p.name = missing.n
 WHERE NOT EXISTS (SELECT 1 FROM default_bioreactorTab d
                    WHERE d.bioreactorID = 2 AND d.parameterID = p.parameterID);


-- Restore the AUTOINCREMENT counters saved above. UPDATE covers tables that
-- got a fresh sqlite_sequence row from the copied rows, INSERT covers tables
-- that were empty and therefore have no row at all.
UPDATE sqlite_sequence
   SET seq = (SELECT b.seq FROM _seq_backup b WHERE b.name = sqlite_sequence.name)
 WHERE name IN (SELECT name FROM _seq_backup)
   AND seq < (SELECT b.seq FROM _seq_backup b WHERE b.name = sqlite_sequence.name);
INSERT INTO sqlite_sequence (name, seq)
    SELECT name, seq FROM _seq_backup
     WHERE name NOT IN (SELECT name FROM sqlite_sequence);
DROP TABLE _seq_backup;

-- ---------------------------------------------------------------------
-- 8. Indizes auf die Fremdschlüssel, an denen die Kaskade entlangläuft.
--
-- SQLite legt für einen Fremdschlüssel keinen Index an. Beim Löschen eines
-- Projekts muss es dann für JEDE gelöschte Zeitzeile die ganze dataTab
-- durchsuchen, um deren Datenzeilen zu finden. Bei zwei Stunden Prozesszeit
-- sind das 3 601 Zeitzeilen gegen 201 656 Datenzeilen.
--
-- Gemessen an genau diesem Projekt:
--     ohne Index   22,84 s
--     mit Index     0,28 s      -- Faktor 80
--
-- Die Schreibkosten sind nicht messbar (0,54 gegen 0,53 s fürs Speichern);
-- bezahlt wird mit Dateigröße, 8,1 auf 11,0 MB.
--
-- Das ist die Antwort, die in CLAUDE.md schon vorgesehen war: "Ist das
-- Löschen zu langsam, ist der Index das Mittel, nicht das Abschalten der
-- Integritätsprüfung."
CREATE INDEX IF NOT EXISTS timeTab_projectID          ON timeTab (projectID);
CREATE INDEX IF NOT EXISTS dataTab_timeID             ON dataTab (timeID);
CREATE INDEX IF NOT EXISTS dataTab_variableID         ON dataTab (variableID);
CREATE INDEX IF NOT EXISTS processTab_projectID       ON processTab (projectID);
CREATE INDEX IF NOT EXISTS logTab_projectID           ON logTab (projectID);
CREATE INDEX IF NOT EXISTS process_parameterTab_processID
    ON process_parameterTab (processID);

COMMIT;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;

-- The rebuild leaves the freelist and the ANALYZE statistics behind.
VACUUM;
ANALYZE;
