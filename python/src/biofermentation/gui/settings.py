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
    #: Whether the timer follows the step width. True is what the application
    #: has always done: one tick per step, so a speed factor of 1 runs at real
    #: time whatever Δt says.
    #:
    #: Uncoupling it is what makes a large Δt usable. Δt = 10 s keeps a tenth
    #: of the measured values and makes the screen move once every ten
    #: seconds; with the refresh held at 2 s the display stays readable — and
    #: the run goes five times faster than the real process, because the pace
    #: against the wall clock is exactly this ratio.
    couple_refresh_to_dt: bool = True
    #: The refresh in seconds, used only when the two are uncoupled.
    refresh_seconds: float = 2.0
    #: Store only every n-th computed step. 1 is everything, which is what
    #: the application has always done.
    #:
    #: This is about file size, not about accuracy. Δt is the step the
    #: controllers are tuned for and must not be raised to save room — pO2
    #: control measured RMS 9 at Δt = 2 s and 121 at 60 s. How often a step is
    #: *written down* is a separate question, and 14 hours at Δt = 2 s came to
    #: 1 443 624 values. Every fifth step is a fifth of the file and the same
    #: simulation.
    storage_interval: int = 1

    def shows(self, tab: str) -> bool:
        return tab not in self.hidden_tabs

    def storage_seconds(self, dt_seconds: float) -> float:
        """What the interval means in process time, for a label to say."""
        return max(1, int(self.storage_interval)) * float(dt_seconds or 0)

    def interval_ms(self, dt_seconds: float) -> int:
        """How long the timer waits between ticks, in milliseconds.

        The one place that answers it, so the window and the settings dialog
        cannot disagree about what the setting means.
        """
        seconds = dt_seconds if self.couple_refresh_to_dt else self.refresh_seconds
        return max(1, round(float(seconds or 0) * 1000)) if seconds else 2000

    def as_document(self) -> dict:
        return {
            "hidden_tabs": sorted(self.hidden_tabs),
            "student_view": bool(self.student_view),
            "couple_refresh_to_dt": bool(self.couple_refresh_to_dt),
            "refresh_seconds": float(self.refresh_seconds),
            "storage_interval": int(self.storage_interval),
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
        refresh = float(document.get("refresh_seconds", 2.0))
        if not 0.05 <= refresh <= 600:
            raise ValueError(
                f"refresh_seconds is {refresh} — it has to lie between 0.05 and 600"
            )
        interval = int(document.get("storage_interval", 1))
        if not 1 <= interval <= 10_000:
            raise ValueError(
                f"storage_interval is {interval} — it has to lie between 1 and 10000"
            )
        return Settings(
            hidden_tabs=set(hidden),
            student_view=bool(document.get("student_view", False)),
            couple_refresh_to_dt=bool(document.get("couple_refresh_to_dt", True)),
            refresh_seconds=refresh,
            storage_interval=interval,
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
        "# couple_refresh_to_dt: true lets the timer follow Δt — one tick per\n"
        "#               step, so speed factor 1 is real time.\n"
        "# refresh_seconds: the timer when the two are uncoupled. A run then\n"
        "#               goes Δt/refresh times faster than the real process.\n"
        "# storage_interval: write only every n-th step. 1 is everything.\n"
        "#               Δt stays what it is — this is file size, not accuracy.\n"
        + yaml.safe_dump(settings.as_document(), sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    return path
