"""``line_plot`` in isolation — a static multi-channel line plot.

A thin ImPlot wrapper for plotting ``(n_samples, n_channels)`` data with a
legend. Unlike ``signal_viewer`` it draws whatever array you hand it — a
recorded trial, a filter response, a feature trace — with no streaming.

Run with:
    uv run python examples/panels/line_plot.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import LinePlot

t = np.linspace(0, 2, 400)
DATA = np.column_stack(
    [np.sin(2 * np.pi * f * t) + 0.05 * np.random.randn(t.size) for f in (2, 3, 5, 8)]
).astype(np.float32)
NAMES = ["2 Hz", "3 Hz", "5 Hz", "8 Hz"]

app = App("panel: line_plot")

plot = LinePlot("EMG channels")


@app.ui
def ui(ctx):
    plot.ui(DATA, channel_names=NAMES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
