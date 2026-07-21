"""``scatter2d`` in isolation — 2-D scatter with per-class colouring.

For low-dimensional embeddings (UMAP / t-SNE / PCA of feature windows).
Pass ``points`` plus optional integer ``labels`` + ``class_names`` and each
class gets its own colour + legend entry. Here: three Gaussian blobs.

Run with:
    uv run python examples/panels/scatter2d.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import Scatter2D

rng = np.random.default_rng(0)
CENTERS = np.array([[-2.0, 0.0], [2.0, 1.0], [0.0, -2.5]])
POINTS = np.vstack([c + 0.6 * rng.standard_normal((60, 2)) for c in CENTERS]).astype(np.float64)
LABELS = np.repeat([0, 1, 2], 60)
CLASS_NAMES = ["Rest", "Fist", "Open"]

app = App("panel: scatter2d")

sc = Scatter2D("Feature embedding")


@app.ui
def ui(ctx):
    sc.ui(POINTS, labels=LABELS, class_names=CLASS_NAMES)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
