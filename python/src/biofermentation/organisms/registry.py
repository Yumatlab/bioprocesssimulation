"""Plugin registry for organism models (plan section 2.2).

A new organism is a folder with a class and an @register above it. Nothing in
the core has to change, and organismTab/modelTab no longer need a hand-written
entry — the registry is the source of truth for what the application can
simulate.
"""

import importlib
import pkgutil

from .base import OrganismModel

_REGISTRY: dict[str, type[OrganismModel]] = {}


def register(cls: type[OrganismModel]) -> type[OrganismModel]:
    """Class decorator that makes a model discoverable by its metadata name."""
    name = cls.metadata.name
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"two organism models claim the name {name!r}: "
            f"{existing.__module__} and {cls.__module__}"
        )
    _REGISTRY[name] = cls
    return cls


def discover_organisms() -> dict[str, type[OrganismModel]]:
    """Import every subpackage of organisms/ so its @register runs.

    Called once at application start. Importing is the whole mechanism: a
    subpackage registers itself as a side effect of being imported.
    """
    package = importlib.import_module(__package__)
    for _, name, is_package in pkgutil.iter_modules(package.__path__):
        if is_package:
            importlib.import_module(f"{__package__}.{name}")
    return dict(_REGISTRY)


def available_organisms() -> dict[str, type[OrganismModel]]:
    """What is registered right now, without triggering a discovery pass."""
    return dict(_REGISTRY)


def get_organism(name: str) -> OrganismModel:
    """A fresh instance of the model registered under name."""
    try:
        cls = _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise LookupError(f"no organism model named {name!r}; registered: {known}") from None
    return cls()
