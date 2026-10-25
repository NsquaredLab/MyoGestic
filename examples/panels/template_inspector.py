"""``template_inspector`` in isolation — accept/reject a table of rows.

A reusable "extract → review → train" table: one row per candidate
(template / trial / segment) with an acceptance chip, a class badge, an
optional info line, and an energy bar. Clicking a row selects it; the call
returns the selected row's ``key`` so a caller can render a detail view.

The caller owns the rows (this example hands it five mock
``TemplateInspectorRow``s); the widget only toggles ``accepted`` in place
and reports the selection.

Run with:
    uv run python examples/panels/template_inspector.py
"""

from imgui_bundle import imgui

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, TemplateInspector, TemplateInspectorRow
from myogestic.widgets.common import mono_text, muted

ROWS = [
    TemplateInspectorRow("s1#0", "OPEN", accepted=True, info_text="2026-05-01", energy=0.82),
    TemplateInspectorRow("s1#1", "CLOSED", accepted=True, info_text="2026-05-01", energy=0.64),
    TemplateInspectorRow("s1#2", "OPEN", accepted=False, info_text="2026-05-01", energy=0.31),
    TemplateInspectorRow("s2#0", "CLOSED", accepted=True, info_text="2026-05-02", energy=0.90),
    TemplateInspectorRow("s2#1", "OPEN", accepted=True, info_text="2026-05-02", energy=0.47),
]

app = App("panel: template_inspector")
header = AppHeader("TemplateInspector", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

inspector = TemplateInspector("templates", title="Extracted templates")


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        selected = inspector.ui(ROWS)
        if selected is not None:
            imgui.text_colored(muted(), "Selected row")
            mono_text(selected)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
