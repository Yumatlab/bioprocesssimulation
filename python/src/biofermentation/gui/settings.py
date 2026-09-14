"""What an installation shows, and to whom.

The third file next to the database, after `style.qss` and
`control_options.yaml`: `settings.yaml`. It holds the choices a lecturer makes
once for a room full of machines — which tabs a student sees, and whether the
run controls can be touched.

Written by the settings dialog and readable by hand; a broken file is reported
and ignored rather than obeyed, because a settings file nobody can parse must
not be able to hide the whole application.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..resources import default_database

USER_SETTINGS_NAME = "settings.yaml"

#: The tabs of the control window that may be switched off, in the order they
#: stand in. "Control Options" is not among them: a window without it is not a
#: control window, and "Information" is where a project says what it is.
HIDEABLE_TABS = ("Controllers", "Variable Pool", "Process Manager", "Log")


@dataclass
class Settings:
    """What the windows ask before they build themselves."""

    #: Tabs to leave out of the control window, by their title.
    hidden_tabs: set[str] = field(default_factory=set)
    #: Student view: the step width is shown but not editable and the speed
    #: factor is not shown at all. A run everybody starts with the same Δt is
    #: comparable; one where each machine ran at its own factor is not.
    student_view: bool = False

    def shows(self, tab: str) -> bool:
        return tab not in self.hidden_tabs

    def as_document(self) -> dict:
        return {
            "hidden_tabs": sorted(self.hidden_tabs),
            "student_view": bool(self.student_view),
        }


def settings_path() -> Path:
    """Where the settings live: next to the database, like the other two."""
    return default_database(create=False).parent / USER_SETTINGS_NAME


def load_settings(path: Path | None = None) -> tuple[Settings, str]:
    """The settings, and what went wrong on the way to them.

    Never raises. A file that cannot be read gives the defaults — everything
    visible, nothing locked — plus the reason, which the window puts in its
    log. Settings that hide things must not be able to fail *towards* hiding
    things.
    """
    path = settings_path() if path is None else path
    if not path.is_file():
        return Settings(), ""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            raise ValueError("the file has to be a mapping")
        hidden = document.get("hidden_tabs") or []
        if isinstance(hidden, str):
            hidden = [hidden]
        unknown = sorted(set(hidden) - set(HIDEABLE_TABS))
        if unknown:
            raise ValueError(
                f"unknown tab(s) {', '.join(unknown)} — the choices are: "
                f"{', '.join(HIDEABLE_TABS)}"
            )
        return Settings(
            hidden_tabs=set(hidden), student_view=bool(document.get("student_view", False))
        ), ""
    except (ValueError, yaml.YAMLError, OSError) as error:
        return Settings(), f"{path.name}: {error}"


def save_settings(settings: Settings, path: Path | None = None) -> Path:
    """Write the settings out. The dialog is the usual author, not a person."""
    path = settings_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# What this installation shows. Written by Settings on the starting\n"
        "# screen; editing it by hand works too.\n"
        "#\n"
        f"# hidden_tabs: any of {', '.join(HIDEABLE_TABS)}\n"
        "# student_view: the step width is shown but locked, the speed factor\n"
        "#               is not shown at all.\n"
        + yaml.safe_dump(settings.as_document(), sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    return path
