"""Declarative organism definitions (plan section 2.3).

Parameters, categories and variables of an organism as YAML instead of as
database rows or Python code. The cut is deliberate: parameter management is
configuration, the ODE is a program. Someone who wants to add a substrate or
retune a default should not have to open a .py file, and someone who writes
new kinetics has to.

This module is the data model and the YAML round trip only — it never touches
the database. Reading and writing definitions against SQLite lives in
db/definitions.py, so organisms/ stays free of a database dependency and a
model plugin can be tested without one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

DEFINITION_FILENAME = "definition.yaml"


@dataclass
class CategoryDefinition:
    """A row of categoryTab. Groups parameters in the editors."""

    name: str
    section: str | None = None
    reading_rate: str | None = None


@dataclass
class ParameterDefinition:
    """A row of parameterTab plus this organism's default value.

    category refers to a CategoryDefinition by name rather than by id: ids are
    a database detail and differ between installations.
    """

    name: str
    category: str
    default: float
    tex: str | None = None
    unit: str | None = None
    tex_unit: str | None = None
    type: str = "editfield"
    internal_order: int | None = None
    external_order: int | None = None
    description: str | None = None


@dataclass
class VariableDefinition:
    """A row of variableTab together with its variable_handlingTab row.

    initial_assignment is the expression the initialisation evaluates at
    t = 0. It is carried through as text; nothing in this layer executes it.
    """

    name: str
    shorttex: str | None = None
    longtex: str | None = None
    unit: str | None = None
    tex_unit: str | None = None
    description: str | None = None
    visible: bool = True
    upload_rate: str = "cyclic"
    initial_assignment: str | None = None
    process_variable: bool = False


@dataclass
class OrganismDefinition:
    """Everything about an organism that is data rather than kinetics."""

    name: str
    display_name: str
    n_reservoirs: int
    texname: str | None = None
    description: str | None = None
    function_file: str | None = None
    initialization_file: str | None = None
    categories: list[CategoryDefinition] = field(default_factory=list)
    parameters: list[ParameterDefinition] = field(default_factory=list)
    variables: list[VariableDefinition] = field(default_factory=list)

    def validate(self) -> list[str]:
        """Problems that would make an import fail or silently lose data."""
        problems = []

        known_categories = {c.name for c in self.categories}
        for parameter in self.parameters:
            if parameter.category not in known_categories:
                problems.append(
                    f"parameter {parameter.name!r} names category "
                    f"{parameter.category!r}, which is not defined"
                )

        for label, names in (
            ("categories", [c.name for c in self.categories]),
            ("parameters", [p.name for p in self.parameters]),
            ("variables", [v.name for v in self.variables]),
        ):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            if duplicates:
                problems.append(f"duplicate {label}: {', '.join(duplicates)}")

        if self.n_reservoirs < 1:
            problems.append(f"n_reservoirs is {self.n_reservoirs}, must be at least 1")

        return problems


def _drop_empty(value):
    """Leave None out of the YAML so a definition stays readable by hand."""
    if isinstance(value, dict):
        return {k: _drop_empty(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value


def write_definition(definition: OrganismDefinition, path: Path | str) -> Path:
    """Write a definition to YAML, keys in declaration order."""
    path = Path(path)
    payload = _drop_empty(asdict(definition))
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    return path


def load_definition(path: Path | str) -> OrganismDefinition:
    """Read a definition from YAML and check it before handing it back."""
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    definition = OrganismDefinition(
        name=raw["name"],
        display_name=raw["display_name"],
        n_reservoirs=int(raw["n_reservoirs"]),
        texname=raw.get("texname"),
        description=raw.get("description"),
        function_file=raw.get("function_file"),
        initialization_file=raw.get("initialization_file"),
        categories=[CategoryDefinition(**c) for c in raw.get("categories", [])],
        parameters=[ParameterDefinition(**p) for p in raw.get("parameters", [])],
        variables=[VariableDefinition(**v) for v in raw.get("variables", [])],
    )

    problems = definition.validate()
    if problems:
        listing = "\n  ".join(problems)
        raise ValueError(f"{path.name} is not a usable organism definition:\n  {listing}")
    return definition


def definition_path(organism_name: str) -> Path:
    """Where the definition of a registered organism lives."""
    return Path(__file__).parent / organism_name / DEFINITION_FILENAME
