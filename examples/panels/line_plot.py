"""``line_plot`` in isolation — a static multi-channel line plot.

A thin ImPlot wrapper for plotting ``(n_samples, n_channels)`` data with a
legend. Unlike ``signal_viewer`` it draws whatever array you hand it — a
recorded trial, a filter response, a feature trace — with no streaming.
The explicit amplitude range opens the widget in Shared mode; choose Auto
to fit the data instead. Reuse the same range when comparing other plots.

Run with:
    uv run python examples/panels/line_plot.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, LinePlot

t = np.linspace(0, 2, 400)
DATA = np.column_stack(
    [np.sin(2 * np.pi * f * t) + 0.05 * np.random.randn(t.size) for f in (2, 3, 5, 8)]
).astype(np.float32)
NAMES = ["2 Hz", "3 Hz", "5 Hz", "8 Hz"]

app = App("panel: line_plot")
header = AppHeader("LinePlot", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

plot = LinePlot("EMG channels", y_range=(-1.2, 1.2))


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        plot.ui(DATA, channel_names=NAMES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
