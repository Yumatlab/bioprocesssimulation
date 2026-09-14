"""Organism models. A new one is a subpackage with a @register-ed class."""

from .base import OrganismMetadata, OrganismModel
from .registry import available_organisms, discover_organisms, get_organism, register

__all__ = [
    "OrganismMetadata",
    "OrganismModel",
    "available_organisms",
    "discover_organisms",
    "get_organism",
    "register",
]
