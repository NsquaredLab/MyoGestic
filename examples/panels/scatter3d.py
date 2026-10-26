"""``scatter3d`` in isolation — 3-D scatter with an orbit camera.

The three-dimensional sibling of ``scatter2d`` (drag to orbit). Same
per-class colouring; pass ``axis_names`` to label the axes. Here: three
Gaussian blobs in 3-D.

Run with:
    uv run python examples/panels/scatter3d.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, Scatter3D

rng = np.random.default_rng(1)
CENTERS = np.array([[-2.0, 0.0, 0.0], [2.0, 1.0, -1.0], [0.0, -2.0, 2.0]])
POINTS = np.vstack([c + 0.6 * rng.standard_normal((60, 3)) for c in CENTERS]).astype(np.float64)
LABELS = np.repeat([0, 1, 2], 60)
CLASS_NAMES = ["Rest", "Fist", "Open"]

app = App("panel: scatter3d")
header = AppHeader("Scatter3D", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

sc = Scatter3D("Feature embedding (3-D)", axis_names=("PC1", "PC2", "PC3"))


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
