"""``app_logo`` in isolation — the MyoGestic wordmark, fit-to-cell.

Renders the shipped wordmark as the largest aspect-preserving rectangle
that fits the body panel (minus padding), centred beneath the shared header's
inline logo.

Run with:
    uv run python examples/panels/app_logo.py
"""

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, AppLogo
from myogestic.widgets.common import ui_px

app = App("panel: app_logo")
header = AppHeader("AppLogo", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        # Scale the margin with the centring spacer so the full logo stays visible.
        AppLogo(padding=ui_px(20)).ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
