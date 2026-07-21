"""``heatmap`` in isolation — a labelled 2-D heatmap.

For confusion matrices, channel correlation, feature-importance grids —
any 2-D array. Cells are annotated with ``label_fmt``. Here: a mock 4×4
confusion matrix, row-normalised.

Run with:
    uv run python examples/panels/heatmap.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import Heatmap

_counts = np.array([[42, 3, 1, 0], [4, 38, 2, 1], [0, 5, 40, 2], [1, 0, 3, 44]], dtype=np.float64)
CONFUSION = _counts / _counts.sum(axis=1, keepdims=True)

app = App("panel: heatmap")

hm = Heatmap("Confusion (row-normalised)", label_fmt="%.2f")


@app.ui
def ui(ctx):
    hm.ui(CONFUSION)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
