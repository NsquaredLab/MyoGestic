"""``StatusBar`` in its bare bottom row, with a synthetic acquisition stream.

Run with:
    uv run python examples/panels/status_bar.py
"""

from myogestic import App, Context, Fr, Grid, Px, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import AppHeader, SignalViewer, StatusBar

app = App("panel: StatusBar")
app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=2000))
app.ctx.participant = "P-014"
header = AppHeader("StatusBar", show_state=False)
layout = Grid.areas(
    "header\nbody\nstatus", row_height=[Px(52), Fr(1), Px(26)],
    bare=("header", "status"),
)
viewer = SignalViewer("emg")
status = StatusBar("emg")


@app.ui
def ui(ctx: Context) -> None:
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        viewer.ui(ctx)
    with layout.area("status"):
        status.ui(ctx)


def main() -> None:
    """Run the standalone footer demonstration."""
    app.run()


if __name__ == "__main__":
    main()
