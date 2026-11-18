"""The PCS tab's wiring and its layout file — PCS plan, phase 2.

No Qt here except in the one test that compares with the panels. The wiring is
checked against the models twice: by reading their source (which flags exist)
and by running them (whether a locked valve really changes nothing, and an
owned one really changes something).
"""

import csv
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

from biofermentation.core.runner import build_state, run_steps
from biofermentation.db import load_phases
from biofermentation.gui import pcs_layout
from biofermentation.gui.pcs_layout import (
    BUNDLED_PCS_LAYOUT,
    fallback,
    load_pcs_layout,
    write_user_pcs_layout,
)
from biofermentation.gui.pcs_specs import MEDIA, REACTOR, SYMBOLS, Lock, pcs_spec, read
from biofermentation.organisms import discover_organisms, get_organism

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "src" / "biofermentation"
TEMPLATE_DB = SOURCE / "resources" / "SimulationAppDB_template.db"
DEFAULTS = SOURCE / "resources" / "defaults"

ORGANISMS = [("escherichia_coli", 716), ("pichia_pastoris", 519)]


@pytest.fixture(autouse=True, scope="module")
def _registry():
    discover_organisms()


#: Steps per probe run. Enough for every flag to reach the balances.
PROBE_STEPS = 10


def _parameter_table() -> dict[str, dict[str, str]]:
    with (DEFAULTS / "parameterTab.csv").open(encoding="utf-8") as handle:
        return {row["name"]: row for row in csv.DictReader(handle)}


def _mode_values() -> dict[str, tuple[int, ...]]:
    """Every value each Mode_ parameter can take, from parameter_controlmodesTab."""
    ids = {row["parameterID"]: name for name, row in _parameter_table().items()}
    values: dict[str, list[int]] = {}
    with (DEFAULTS / "parameter_controlmodesTab.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            values.setdefault(ids[row["parameterID"]], []).append(int(row["value"]))
    return {name: tuple(sorted(found)) for name, found in values.items()}


def _flags_read_by(organism: str) -> set[str]:
    source = (SOURCE / "organisms" / organism / "model.py").read_text(encoding="utf-8")
    return set(re.findall(r"\bp\.(f_\w+)", source))


def _spec_for(organism: str):
    return pcs_spec(get_organism(organism).metadata.n_reservoirs)


def _probe_parameters(project: int) -> dict[str, float]:
    """A project with cells in it and every flow it could have set non-zero."""
    p = dict(load_phases(TEMPLATE_DB, project).p)
    p.update(f_Inoc=1.0, f_InocStart=1.0, FnO2w=1.0, FnN2w=1.0, FnCO2w=0.5)
    # What a feed phase would have frozen into p before it starts.
    for n in (1, 2):
        p.setdefault(f"FR{n}j", 0.01)
        p.setdefault(f"t{n}j", 0.0)
        p.setdefault(f"qXpX{n}w", 0.1)
        p.setdefault(f"kR{n}", 0.1)
        # A closed-loop feed that wants to pump: setpoint out of reach and a
        # plain positive gain (project 519 has negative gains on reservoir 2).
        p[f"cS{n}Lw"] = 1000.0
        p[f"KP_feedR{n}"] = 1.0
        p[f"KI_feedR{n}"] = 0.0
        p[f"KD_feedR{n}"] = 0.0
    return p


def _run(organism: str, project: int, setting: dict[str, float]):
    """A short run in which `setting` is applied after the start.

    After, not before: shared.py derives the starting flows from the flags
    without looking at the modes, and a click on a valve happens during a run.
    """
    model = get_organism(organism)
    state = build_state(_probe_parameters(project), model, dt=2 / 3600)
    for name, value in setting.items():
        container, _, key = name.partition(":")
        if container == "p":
            state.p[key] = value
        else:
            state.a[key] = value
    run_steps(state, model, PROBE_STEPS)
    return state.trimmed()


def _same_run(first, second) -> bool:
    if first.keys() != second.keys():
        return False
    return all(np.array_equal(first[name], second[name], equal_nan=True) for name in first)


def _owned(valve) -> dict[str, float]:
    """A setting in which every lock of the valve leaves it to the operator."""
    setting = {lock.source: lock.values[0] for lock in valve.locks}
    if valve.parameter == "f_antifoam":
        # The model doses only while a.ToI != 0, and a culture inoculated at
        # t = 0 keeps ToI at 0 — so a probe that starts inoculated never
        # doses. Inoculated a moment after the start, as far as the timer
        # knows; ToI has to lie before t, or the dosing time is negative.
        setting["a:ToI"] = 1e-6
    return setting


def _locked_values(lock: Lock, n_reservoirs: int) -> tuple[int, ...]:
    container, _, name = lock.source.partition(":")
    if container == "a":
        candidates = (0, 1)
    elif name == "R_feed":
        candidates = tuple(range(1, n_reservoirs + 1))
    else:
        candidates = _mode_values()[name]
    return tuple(value for value in candidates if value not in lock.values)


# ------------------------------------------------------- the wiring --


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_every_valve_writes_a_flag_the_model_reads(organism, project):
    """A valve whose flag nothing reads would be a switch that does nothing."""
    read_flags = _flags_read_by(organism)
    for valve in _spec_for(organism).valves:
        assert valve.parameter in read_flags, valve.element


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_every_flag_the_model_reads_has_a_valve(organism, project):
    """A new flag in a model shows up here before it is missing from the sheet.

    f_Inoc is the inoculation button, which stays where it is (decision 6).
    """
    offered = {valve.parameter for valve in _spec_for(organism).valves}
    assert _flags_read_by(organism) - offered == {"f_Inoc"}


def test_every_valve_parameter_is_a_switch_in_the_parameter_table():
    table = _parameter_table()
    for valve in pcs_spec(2).valves:
        assert table[valve.parameter]["type"] == "switch", valve.parameter


def test_every_parameter_the_sheet_reads_exists():
    """Levels, marks and lock conditions name parameters the database has."""
    table = _parameter_table()
    spec = pcs_spec(2)
    sources = [lock.source for valve in spec.valves for lock in valve.locks]
    sources += [tank.maximum for tank in spec.tanks if tank.maximum]
    sources += [tank.minimum for tank in spec.tanks if tank.minimum]
    sources += [pipe.counts_when.source for pipe in spec.pipes if pipe.counts_when]
    for source in sources:
        if source.startswith("p:"):
            assert source[2:] in table, source


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_every_flow_and_volume_name_is_a_series_the_model_writes(organism, project):
    model = get_organism(organism)
    state = build_state(_probe_parameters(project), model, dt=2 / 3600)
    run_steps(state, model, 3)

    spec = pcs_spec(model.metadata.n_reservoirs)
    names = [valve.feedback for valve in spec.valves if valve.feedback]
    names += [pipe.flow for pipe in spec.pipes if pipe.flow]
    names += [tank.volume for tank in spec.tanks if tank.volume]
    for name in names:
        container, _, key = name.partition(":")
        assert container in ("v", "a"), name
        store = state.v if container == "v" else state.a
        assert key in store, name
        if container == "v":
            assert np.isfinite(store[key][state.idx]), name


def test_ids_are_unique_and_pipes_connect_elements_on_the_sheet():
    for n in (1, 2):
        spec = pcs_spec(n)
        pipes = [pipe.element for pipe in spec.pipes]
        ids = spec.elements() + pipes
        assert len(ids) == len(set(ids))

        valves = {valve.element: valve for valve in spec.valves}
        for pipe in spec.pipes:
            assert pipe.source in spec.elements(), pipe.element
            assert pipe.target in spec.elements(), pipe.element
            assert pipe.medium in MEDIA, pipe.element
            if pipe.valve:
                # The valve draws itself from the same series its pipe shows.
                assert valves[pipe.valve].feedback == pipe.flow, pipe.element


def test_every_element_is_drawn_as_a_known_symbol():
    """Pumps where the model meters a pump rate, control valves on the gases."""
    spec = pcs_spec(2)
    symbols = {valve.element: valve.symbol for valve in spec.valves}
    assert set(symbols.values()) <= set(SYMBOLS)
    for element in ("acid_pump", "alkali_pump", "antifoam_pump", "feed2_pump"):
        assert symbols[element] == "pump", element
    # The harvest leaves through a valve in the bottom of the reactor.
    assert symbols["harvest_valve"] == "valve"
    for gas in ("air", "o2", "n2", "co2"):
        assert symbols[f"{gas}_valve"] == "control_valve", gas
    assert symbols["stirrer"] == "motor"


def test_pichia_has_two_feed_lines_and_coli_one():
    assert [t.element for t in _spec_for("escherichia_coli").tanks].count("reservoir2") == 0
    pichia = _spec_for("pichia_pastoris")
    assert {"reservoir1", "reservoir2"} <= {t.element for t in pichia.tanks}
    assert {"feed1_pump", "feed2_pump"} <= {v.element for v in pichia.valves}


def test_locked_by_names_who_drives_the_valve():
    acid = pcs_spec(1).valve("acid_pump")
    assert acid.locked_by({"Mode_pH": 0.0}, {}) is None
    assert acid.locked_by({"Mode_pH": 1.0}, {}) == "pH-Control"

    feed = pcs_spec(2).valve("feed2_pump")
    owned = {"Mode_pO2": 1.0, "R_feed": 2.0}
    assert feed.locked_by(owned, {}) is None
    assert feed.locked_by(owned, {"switch_pulse": True}) == "pulse feed phase"
    assert feed.locked_by({"Mode_pO2": 1.0, "R_feed": 1.0}, {}).startswith("Feed Control")


def test_a_condition_reads_only_p_and_a():
    assert read("p:Mode_pH", {"Mode_pH": 1.0}, {}) == 1.0
    assert read("a:switch_exp", {}, {}) == 0.0
    with pytest.raises(ValueError):
        read("v:VL", {}, {})


# ---------------------------------------- the wiring, by running it --


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_a_locked_valve_cannot_change_the_run(organism, project):
    """Outside its lock the flag must not reach the run — bit for bit.

    Each complete lock is broken in turn, with the valve's other locks left
    open, and the run is made twice: flag 0 and flag 1. Same run, or the lock
    claims a controller owns a flow it does not. A flag several valves share
    is checked on the valve's own line only.
    """
    n_reservoirs = get_organism(organism).metadata.n_reservoirs
    spec = pcs_spec(n_reservoirs)
    flags = [valve.parameter for valve in spec.valves]
    checked = 0
    for valve in spec.valves:
        for lock in valve.locks:
            if not lock.complete:
                continue
            for value in _locked_values(lock, n_reservoirs):
                setting = {**_owned(valve), lock.source: value}
                closed = _run(organism, project, {**setting, f"p:{valve.parameter}": 0.0})
                opened = _run(organism, project, {**setting, f"p:{valve.parameter}": 1.0})
                where = f"{valve.element} at {lock.source} = {value}"
                if flags.count(valve.parameter) == 1:
                    assert _same_run(closed, opened), where
                else:
                    # f_feed opens whichever reservoir R_feed names, so the
                    # run may change — only not through this valve's line.
                    name = valve.feedback.partition(":")[2]
                    assert np.array_equal(closed[name], opened[name], equal_nan=True), where
                checked += 1
    assert checked > 0


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_an_owned_valve_changes_the_run(organism, project):
    """With every lock open the flag has to matter, or the valve is a dummy."""
    for valve in _spec_for(organism).valves:
        setting = _owned(valve)
        closed = _run(organism, project, {**setting, f"p:{valve.parameter}": 0.0})
        opened = _run(organism, project, {**setting, f"p:{valve.parameter}": 1.0})
        assert not _same_run(closed, opened), valve.element


def _flag_acts(organism, project, valve, setting, shared: bool) -> bool:
    """Whether switching the valve's flag from 0 to 1 changes anything."""
    closed = _run(organism, project, {**setting, f"p:{valve.parameter}": 0.0})
    opened = _run(organism, project, {**setting, f"p:{valve.parameter}": 1.0})
    if not shared:
        return not _same_run(closed, opened)
    name = valve.feedback.partition(":")[2]
    return not np.array_equal(closed[name], opened[name], equal_nan=True)


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_a_valve_is_locked_exactly_where_its_flag_cannot_act(organism, project):
    """Every mode of every controller, for every valve: lock and model agree.

    The two tests above catch a lock that is too strict. This one also catches
    a lock that is missing a mode — a valve offered where the model ignores it.
    Incomplete locks (decision, not fact) are skipped where they lock.
    """
    spec = _spec_for(organism)
    flags = [valve.parameter for valve in spec.valves]
    for valve in spec.valves:
        shared = flags.count(valve.parameter) > 1
        for mode, values in _mode_values().items():
            for value in values:
                setting = {**_owned(valve), f"p:{mode}": value}
                p = {**_probe_parameters(project)}
                a = {}
                for name, number in setting.items():
                    container, _, key = name.partition(":")
                    (p if container == "p" else a)[key] = number
                owner = valve.locked_by(p, a)
                if owner is not None:
                    lock = next(lock for lock in valve.locks if lock.owner == owner)
                    if not lock.complete:
                        continue
                acts = _flag_acts(organism, project, valve, setting, shared)
                assert acts == (owner is None), f"{valve.element} at {mode} = {value}"


@pytest.mark.parametrize(("organism", "project"), ORGANISMS)
def test_the_aeration_lock_is_a_decision_not_a_fact(organism, project):
    """In Aeration and Gasmix the main valve still changes the run.

    That is why its lock is marked incomplete: the tab takes the valve away
    there (decision 7), but the model would read it. If this ever fails, the
    model changed and the lock can become complete.
    """
    for mode in (2, 3):
        setting = {"p:Mode_pO2": mode}
        closed = _run(organism, project, {**setting, "p:f_aeration": 0.0})
        opened = _run(organism, project, {**setting, "p:f_aeration": 1.0})
        assert not _same_run(closed, opened), mode


def test_the_panel_switches_carry_the_same_conditions():
    """Control Options and the sheet lock the same flags in the same modes."""
    pytest.importorskip("PySide6")
    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    spec = pcs_spec(2)
    for panel in CONTROL_PANELS:
        for switch in panel.switches:
            valves = [valve for valve in spec.valves if valve.parameter == switch.parameter]
            assert valves, switch.parameter
            for valve in valves:
                own = [lock for lock in valve.locks if lock.source == f"p:{panel.mode_parameter}"]
                if not switch.modes:
                    assert own == [], valve.element
                    continue
                assert len(own) == 1, valve.element
                assert own[0].values == tuple(switch.modes), valve.element
                assert own[0].owner == panel.title, valve.element


# ------------------------------------------------------- the layout --


@pytest.mark.parametrize("n", [1, 2])
def test_the_bundled_pcs_layout_places_every_element(n):
    spec = pcs_spec(n)
    layout, problem = load_pcs_layout(spec, BUNDLED_PCS_LAYOUT)
    assert problem == ""
    assert set(layout.positions) == set(spec.elements())
    for pipe in spec.pipes:
        route = layout.route(spec, pipe.element)
        assert route[0] == layout.positions[pipe.source]
        assert route[-1] == layout.positions[pipe.target]


BROKEN = {
    "syntax": "elements: [0.5, 0.5\n",
    "not a mapping": "- reactor\n",
    "missing element": "elements:\n  reactor: [0.5, 0.5]\n",
    "outside the sheet": None,  # filled in below from the bundled file
    "unknown element": None,
    "unknown pipe": None,
}


def _bundled_with_reactor_at(x: float, y: float) -> str:
    """The bundled layout with the reactor moved — whatever the file says now."""
    document = yaml.safe_load(BUNDLED_PCS_LAYOUT.read_text(encoding="utf-8"))
    document["elements"][REACTOR] = [x, y]
    return yaml.safe_dump(document)


def _bundled_with(old: str, new: str) -> str:
    text = BUNDLED_PCS_LAYOUT.read_text(encoding="utf-8")
    assert old in text
    return text.replace(old, new, 1)


@pytest.mark.parametrize("case", list(BROKEN))
def test_a_broken_pcs_layout_falls_back_and_says_why(case, tmp_path):
    text = BROKEN[case]
    if case == "outside the sheet":
        text = _bundled_with_reactor_at(1.55, 0.50)
    if case == "unknown element":
        text = _bundled_with("acid_pump:", "acid_pmup:")
    if case == "unknown pipe":
        text = _bundled_with("acid_line:", "acid_lien:")

    path = tmp_path / "pcs.yaml"
    path.write_text(text, encoding="utf-8")
    spec = pcs_spec(1)
    layout, problem = load_pcs_layout(spec, path)

    assert problem.startswith("pcs.yaml: ")
    assert layout == fallback(spec)


def test_the_fallback_keeps_every_element_on_the_sheet():
    spec = pcs_spec(2)
    layout = fallback(spec)
    assert set(layout.positions) == set(spec.elements())
    assert layout.positions[REACTOR] == (0.5, 0.5)
    for x, y in layout.positions.values():
        assert 0 <= x <= 1
        assert 0 <= y <= 1


def test_a_missing_file_falls_back_and_says_so(tmp_path):
    spec = pcs_spec(1)
    layout, problem = load_pcs_layout(spec, tmp_path / "nowhere.yaml")
    assert problem == "no PCS layout file found"
    assert layout == fallback(spec)


def test_the_user_copy_replaces_the_bundled_layout(tmp_path, monkeypatch):
    user = tmp_path / "pcs.yaml"
    user.write_text(_bundled_with_reactor_at(0.61, 0.50), encoding="utf-8")
    monkeypatch.setattr(pcs_layout, "user_pcs_layout_path", lambda: user)

    layout, problem = load_pcs_layout(pcs_spec(1))
    assert problem == ""
    assert layout.positions[REACTOR] == (0.61, 0.50)


def test_a_broken_user_copy_falls_back_to_the_bundled_layout(tmp_path, monkeypatch):
    user = tmp_path / "pcs.yaml"
    user.write_text("elements: {}\n", encoding="utf-8")
    monkeypatch.setattr(pcs_layout, "user_pcs_layout_path", lambda: user)

    spec = pcs_spec(1)
    layout, problem = load_pcs_layout(spec)
    assert problem.startswith("pcs.yaml: not placed anywhere")
    assert layout == load_pcs_layout(spec, BUNDLED_PCS_LAYOUT)[0]


def test_writing_the_user_copy_leaves_an_existing_file_alone(tmp_path, monkeypatch):
    user = tmp_path / "pcs.yaml"
    monkeypatch.setattr(pcs_layout, "user_pcs_layout_path", lambda: user)

    assert write_user_pcs_layout() == user
    assert user.read_text(encoding="utf-8") == BUNDLED_PCS_LAYOUT.read_text(encoding="utf-8")

    user.write_text("mine\n", encoding="utf-8")
    write_user_pcs_layout()
    assert user.read_text(encoding="utf-8") == "mine\n"


def test_the_vessel_readings_are_the_panel_readings():
    """Beside the reactor stands what the panels show, with their decimals."""
    pytest.importorskip("PySide6")
    from biofermentation.gui.pcs_specs import VESSEL_READINGS
    from biofermentation.gui.widgets.panel_specs import CONTROL_PANELS

    actuals = {
        f"v:{spec_field.actual}": spec_field.decimals
        for panel in CONTROL_PANELS
        for spec_field in panel.fields
        if spec_field.actual
    }
    for reading in VESSEL_READINGS:
        assert reading.source in actuals, reading.source
        assert reading.decimals == actuals[reading.source], reading.source
