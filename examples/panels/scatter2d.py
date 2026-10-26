"""``scatter2d`` in isolation — 2-D scatter with per-class colouring.

For low-dimensional embeddings (UMAP / t-SNE / PCA of feature windows).
Pass ``points`` plus optional integer ``labels`` + ``class_names`` and each
class gets its own colour + legend entry. Here: three Gaussian blobs.

Run with:
    uv run python examples/panels/scatter2d.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, Scatter2D

rng = np.random.default_rng(0)
CENTERS = np.array([[-2.0, 0.0], [2.0, 1.0], [0.0, -2.5]])
POINTS = np.vstack([c + 0.6 * rng.standard_normal((60, 2)) for c in CENTERS]).astype(np.float64)
LABELS = np.repeat([0, 1, 2], 60)
CLASS_NAMES = ["Rest", "Fist", "Open"]

app = App("panel: scatter2d")
header = AppHeader("Scatter2D", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

sc = Scatter2D("Feature embedding")


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        sc.ui(POINTS, labels=LABELS, class_names=CLASS_NAMES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
