"""``heatmap`` in isolation — a labelled 2-D heatmap.

For confusion matrices, channel correlation, feature-importance grids —
any 2-D array. Cells are annotated with ``label_fmt``. Here: a mock 4×4
confusion matrix, row-normalised.

Run with:
    uv run python examples/panels/heatmap.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, Heatmap

CLASSES = ["Rest", "Fist", "Open", "Pinch"]
_counts = np.array([[42, 3, 1, 0], [4, 38, 2, 1], [0, 5, 40, 2], [1, 0, 3, 44]], dtype=np.float64)
CONFUSION = _counts / _counts.sum(axis=1, keepdims=True)

app = App("panel: heatmap")
header = AppHeader("Heatmap", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

hm = Heatmap("Confusion (row-normalised)", label_fmt="%.2f")


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        # One tick per cell, labelled with the class names (rows = true,
        # cols = predicted) instead of a continuous 0–1 axis.
        hm.ui(CONFUSION, x_tick_labels=CLASSES, y_tick_labels=CLASSES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
