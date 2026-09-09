"""Database access layer — phase 1. All access via get_connection()."""

from .connection import get_connection
from .migrate import apply_migration
from .models import (
    Condition,
    Lookups,
    Phase,
    ProjectInfo,
    ProjectSetup,
    VariableSeries,
)
from .project import (
    create_project,
    delete_project,
    list_models,
    list_projects,
    load_phases,
    load_project_info,
    load_project_variables,
    save_project,
    save_project_with_backup,
    unique_project_name,
)
from .seed import export_defaults, load_defaults

__all__ = [
    "Condition",
    "Lookups",
    "Phase",
    "ProjectInfo",
    "ProjectSetup",
    "VariableSeries",
    "apply_migration",
    "create_project",
    "delete_project",
    "export_defaults",
    "get_connection",
    "list_models",
    "list_projects",
    "load_defaults",
    "load_phases",
    "load_project_info",
    "load_project_variables",
    "save_project",
    "save_project_with_backup",
    "unique_project_name",
]
