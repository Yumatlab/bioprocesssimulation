"""What the five controller panels contain (plan section 5.1).

Read off the Control App screenshot of the thesis, page 54, and checked
against the parameter names the organism models actually read. Keeping it as
data rather than as five constructors makes that check possible at all.

The mode numbers are the ones parameter_controlmodesTab stores.
"""

from .control_panel import FieldSpec, PanelSpec, SwitchSpec

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
)

PO2_PANEL = PanelSpec(
    title="pO2-Control",
    mode_parameter="Mode_pO2",
    modes={
        0: "Manual",
        1: "pO2-agitation",
        2: "pO2-aeration",
        3: "pO2-gasmix",
        4: "pO2-feed",
    },
    fields=[
        FieldSpec("pO2w", "pO_{2w} [%]", actual="pO2", actual_label="pO_{2} [%]", decimals=1),
        # Live only where the mode does not drive them itself.
        FieldSpec("NStw", "N_{Stw} [rpm]", decimals=1, modes=(0, 2, 3, 4)),
        FieldSpec("FnGw", "F_{nGw} [l/min]", decimals=1, modes=(0, 1, 3, 4)),
        FieldSpec("FnAIRw", "F_{nAIRw} [l/min]", decimals=1, modes=(0, 1, 4)),
        FieldSpec("FnO2w", "F_{nO2w} [l/min]", decimals=1, modes=(0, 1, 4)),
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
)

FEED_PANEL = PanelSpec(
    title="Feed Control",
    mode_parameter="Mode_feed",
    modes={0: "Manual", 1: "Closed loop"},
    fields=[
        FieldSpec("FR1w", "F_{R1w} [l/h]", decimals=4),
        FieldSpec("FR1max", "F_{R1max} [l/h]", decimals=4),
    ],
    switches=[SwitchSpec("f_feed", "Feed", lamp=True)],
)

CONTROL_PANELS = (
    PH_PANEL,
    TEMPERATURE_PANEL,
    PO2_PANEL,
    LIQUID_WEIGHT_PANEL,
    FEED_PANEL,
)
