"""Loading a process template into a project — Projektplan_Prozessvorlagen.md, phase 2.

No window and no database here: lists of phases in, a list of phases out.
What is removed and what stays is the part of the feature that can lose
somebody's process, and it is tested here on its own.

Two modes (decision of the plan, section 1):

- **append** — the template follows every phase the project has.
- **replace** — the phases that have not started are removed and the
  template follows the last one that has. Started phases (active or
  completed, `is_started`) are never touched: they are the record of what
  was done.

After either, the automaton's `current` is found again with
`adopt_active_phase`, never cleared. Clearing it restarted a running phase
(Phase 0 finding P0-1).
"""

import copy
from collections.abc import Iterable
from dataclasses import dataclass

from ..db.models import Condition, Phase, ProcessTemplate
from .phases import EndCondition, PhaseAutomaton, PhaseStatus, PhaseType, is_started

APPEND = "append"
REPLACE = "replace"
MODES = (APPEND, REPLACE)


@dataclass
class Placement:
    """The result of placing a template: the new list and what it cost."""

    phases: list[Phase]
    added: list[Phase]
    removed: list[Phase]


def phases_from_template(
    template: ProcessTemplate, next_process_id: int, project_id: int
) -> list[Phase]:
    """The template's phases as new phases of a project, ready to run.

    Copies, so that the template object stays as it was loaded. Each gets a
    fresh processID counting up from `next_process_id` (collisions with other
    projects are healed on save by `_claim_free_process_ids`), the status
    upcoming and no start or end time — a timer is stamped when its phase
    starts.
    """
    phases = []
    for offset, source in enumerate(template.phases):
        phases.append(
            Phase(
                processID=next_process_id + offset,
                projectID=project_id,
                statusID=PhaseStatus.UPCOMING,
                typeID=source.typeID,
                name=source.name,
                reservoirID=source.reservoirID,
                start=_without_time(source.start),
                end=_without_time(source.end),
                parameters=dict(source.parameters),
            )
        )
    return phases


def _without_time(condition: Condition) -> Condition:
    fresh = copy.copy(condition)
    fresh.time = None
    return fresh


def removable(phases: Iterable[Phase]) -> list[Phase]:
    """What replacing would remove: every phase that has not started."""
    return [phase for phase in phases if not is_started(phase)]


def place_template(phases: list[Phase], new: list[Phase], mode: str) -> Placement:
    """The project's phases with the template's placed according to `mode`.

    Returns a new list; the caller hands it to the window and the automaton.
    Started phases keep their order and their objects, so the automaton's
    record of them — times, parameters written by a feed — is untouched.
    """
    if mode not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}, not {mode!r}")
    if mode == APPEND:
        return Placement(phases=[*phases, *new], added=list(new), removed=[])
    kept = [phase for phase in phases if is_started(phase)]
    removed = [phase for phase in phases if not is_started(phase)]
    return Placement(phases=[*kept, *new], added=list(new), removed=removed)


def hand_over(automaton: PhaseAutomaton | None, phases: list[Phase]) -> None:
    """Give the automaton its new list and let it find its active phase again.

    `current` is an index into the list. Placing a template never moves a
    started phase, but the index is looked up rather than trusted — the same
    search a reopened project uses.
    """
    if automaton is None:
        return
    automaton.phases = phases
    automaton.adopt_active_phase()


# ------------------------------------------------------------ checking --


def check_template(
    template: ProcessTemplate,
    *,
    model_id: int | None,
    parameters: Iterable[str],
    variables: Iterable[int],
    reservoirs: int,
) -> list[str]:
    """Why this template cannot be loaded here, one sentence per reason.

    Empty means it fits. Nothing is adapted silently: a parameter the
    automaton does not find in p is skipped without a word (P0-7), a variable
    the organism does not offer makes a condition that can never be
    evaluated, and a reservoir beyond the organism's is quietly clamped to
    the last one. Each of those would make the loaded process differ from
    the saved one without anybody seeing it.
    """
    problems = []
    if model_id is not None and template.modelID != model_id:
        problems.append("The template belongs to another model.")
    known_parameters = set(parameters)
    known_variables = set(variables)
    for number, phase in enumerate(template.phases, start=1):
        label = f"Phase {number} ({phase.name or 'unnamed'})"
        if phase.typeID not in {int(kind) for kind in PhaseType}:
            problems.append(f"{label}: unknown phase type {phase.typeID}.")
        unknown = sorted(name for name in phase.parameters if name not in known_parameters)
        if unknown:
            problems.append(f"{label}: this model has no parameter {', '.join(unknown)}.")
        for which, condition in (("start", phase.start), ("end", phase.end)):
            if condition.variableID is not None and condition.variableID not in known_variables:
                problems.append(
                    f"{label}: the {which} condition watches variable "
                    f"{condition.variableID}, which this organism does not offer."
                )
        if phase.reservoirID is not None and not 1 <= int(phase.reservoirID) <= reservoirs:
            problems.append(
                f"{label}: reservoir {phase.reservoirID}, but this organism has {reservoirs}."
            )
    return problems


def check_template_for(template: ProcessTemplate, setup, reservoirs: int) -> list[str]:
    """check_template against what a loaded project knows (load_phases)."""
    return check_template(
        template,
        model_id=setup.info.modelID,
        parameters=setup.p.keys(),
        variables=[row["variableID"] for row in setup.lookups.process_variable],
        reservoirs=reservoirs,
    )


def end_moves_with_replacement(phases: list[Phase], mode: str) -> Phase | None:
    """The running phase whose end replacing would move, if there is one.

    A phase that ends with "Next phase condition" ends when the *next* phase
    may start (condition_check recurses there). Replacing exchanges that next
    phase, and with it the moment the running one ends (Phase 0, P0-4).
    Appending leaves the next phase as it is.
    """
    if mode != REPLACE:
        return None
    for index, phase in enumerate(phases):
        if phase.statusID != PhaseStatus.ACTIVE:
            continue
        if phase.end.typeID != EndCondition.NEXT_PHASE_STARTS:
            return None
        following = phases[index + 1] if index + 1 < len(phases) else None
        return phase if following is None or not is_started(following) else None
    return None


__all__ = [
    "APPEND",
    "MODES",
    "REPLACE",
    "Placement",
    "check_template",
    "check_template_for",
    "end_moves_with_replacement",
    "hand_over",
    "phases_from_template",
    "place_template",
    "removable",
]
