"""What the five controller panels contain (plan section 5.1).

Read off the Control App screenshot of the thesis, page 54, and checked
against the parameter names the organism models actually read. Keeping it as
data rather than as five constructors makes that check possible at all.

The mode numbers are the ones parameter_controlmodesTab stores.
"""

from .control_panel import FieldSpec, PanelSpec, ParameterGroup, SwitchSpec


def _pid(prefix: str, suffix: str) -> ParameterGroup:
    """The K_P / K_I / K_D triple of one PID loop."""
    return ParameterGroup(
        prefix,
        [
            (f"KP_{suffix}", "K_{P}"),
            (f"KI_{suffix}", "K_{I}"),
            (f"KD_{suffix}", "K_{D}"),
        ],
    )


PH_PANEL = PanelSpec(
    title="pH-Control",
    mode_parameter="Mode_pH",
    modes={0: "Manual", 1: "Auto"},
    fields=[
        FieldSpec("pHw", "pH_{w}", actual="pHL", actual_label="pH_{L}", decimals=2),
    ],
    switches=[
        SwitchSpec("f_alkali", "Alkali", modes=(0,)),
        SwitchSpec("f_acid", "Acid", modes=(0,)),
    ],
    parameter_groups=[
        ParameterGroup("Master Controller", [("KP_pH", "K_{P,Master}")]),
        ParameterGroup(
            "Slave Controller",
            [("KP_pH2a", "K_{P,Slave acid}"), ("KP_pH2b", "K_{P,Slave base}")],
        ),
        ParameterGroup("Sensor", [("taupHL", "\\tau_{pH_{L}} [s]")]),
    ],
)

TEMPERATURE_PANEL = PanelSpec(
    title="Temperature-Control",
    mode_parameter="Mode_temp",
    modes={0: "Manual", 1: "Auto"},
    fields=[
        FieldSpec(
            "thetaLw",
            "\\vartheta_{Lw} [°C]",
            actual="thetaL",
            actual_label="\\vartheta_{L} [°C]",
        ),
    ],
    switches=[
        SwitchSpec("f_cooling", "Cooling", modes=(0,)),
        SwitchSpec("f_heating", "Heating", modes=(0,)),
    ],
    parameter_groups=[
        ParameterGroup(
            "Master Controller",
            [("KP_temp1", "K_{P,Master}"), ("KI_temp1", "K_{I,Master}")],
        ),
        ParameterGroup(
            "Slave Controller",
            [
                ("KP_temp2h", "K_{P,Slave heating}"),
                ("KP_temp2c", "K_{P,Slave cooling}"),
            ],
        ),
        ParameterGroup("Sensor", [("tauthetaL", "\\tau_{\\vartheta_{L}} [s]")]),
    ],
)

PO2_PANEL = PanelSpec(
    title="pO2-Control",
    mode_parameter="Mode_pO2",
    # Written without the "pO2-" of the original: the keys sit inside a panel
    # titled pO2-Control, and the prefix cost 170 px on a row that has to show
    # all five at once. The stored mode numbers are unchanged.
    modes={
        0: "Manual",
        1: "Agitation",
        2: "Aeration",
        3: "Gasmix",
        4: "Feed",
    },
    # Two sections wide, so three field slots across: setpoint, measurement
    # and the stirrer on the first row, the three gas flows on the second.
    field_columns=3,
    fields=[
        FieldSpec("pO2w", "pO_{2w} [%]", actual="pO2", actual_label="pO_{2} [%]", decimals=1),
        # Live only where the mode does not drive them itself.
        FieldSpec("NStw", "N_{Stw} [rpm]", decimals=1, modes=(0, 2, 3, 4)),
        FieldSpec("FnGw", "F_{nGw} [l/min]", decimals=1, modes=(0, 1, 3, 4)),
        FieldSpec("FnAIRw", "F_{nAIRw} [l/min]", decimals=1, modes=(0, 1, 4)),
        FieldSpec("FnO2w", "F_{nO2w} [l/min]", decimals=1, modes=(0, 1, 4)),
    ],
    parameter_groups=[
        _pid("Agitation", "agi"),
        _pid("Gasmix", "gasmix"),
        _pid("Aeration", "aeration"),
        _pid("Feed", "feedpO2"),
        ParameterGroup("Sensor", [("taupO2", "\\tau_{pO_{2}} [s]")]),
    ],
)

LIQUID_WEIGHT_PANEL = PanelSpec(
    title="Liquid Weight",
    mode_parameter="Mode_harvest",
    modes={0: "Manual", 1: "Auto"},
    fields=[
        FieldSpec("LWw", "m_{Lw} [kg]", decimals=2),
        FieldSpec("FHrelw", "F_{Hw} [%]", decimals=1, modes=(0,)),
    ],
    switches=[SwitchSpec("f_harvest", "Harvest", modes=(0,))],
    parameter_groups=[_pid("Liquid Weight Controller", "LW")],
)

FEED_PANEL = PanelSpec(
    title="Feed Control",
    mode_parameter="Mode_feed",
    modes={0: "Manual", 1: "Closed loop"},
    # Every field of this panel belongs to one reservoir; R_feed says which,
    # and a phase can change it under the panel.
    reservoir_parameter="R_feed",
    fields=[
        # Closed loop holds the substrate concentration at this setpoint. It
        # is the whole point of the mode and it was missing here: the loop ran
        # against a cS{n}Lw that could only be reached through the database.
        FieldSpec(
            "cS{n}Lw",
            "c_{S{n}Lw} [g/l]",
            actual="cS{n}L",
            actual_label="c_{S{n}L} [g/l]",
            decimals=4,
            modes=(1,),
        ),
        FieldSpec("FR{n}w", "F_{R{n}w} [l/h]", decimals=4, modes=(0,)),
        # Read-only, as in the original: the maximum belongs to the reservoir,
        # not to the moment. It is set in Parameters or by a phase.
        FieldSpec("FR{n}max", "F_{R{n}max} [l/h]", decimals=4, read_only=True),
    ],
    switches=[SwitchSpec("f_feed", "Feed")],
    # One block per reservoir; the project says how many there are.
    parameter_groups_per_reservoir=[_pid("Reservoir {n}", "feedR{n}")],
)

CONTROL_PANELS = (
    PH_PANEL,
    TEMPERATURE_PANEL,
    PO2_PANEL,
    LIQUID_WEIGHT_PANEL,
    FEED_PANEL,
)
