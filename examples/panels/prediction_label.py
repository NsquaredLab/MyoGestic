"""``prediction_label`` in isolation — the current predicted class + confidence.

A big read-out of the pipeline's latest prediction (class name + optional
probability bar). It only reads ``pipeline.predictions``, so a tiny
duck-typed stub stands in for a full trained Pipeline here.

Run with:
    uv run python examples/panels/prediction_label.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, PredictionLabel

CLASSES = ("Rest", "Fist")


class _FakePipeline:
    # prediction_label reads only `.predictions`.
    predictions = {"class": 1, "proba": np.array([0.18, 0.82], dtype=np.float32)}


pipeline = _FakePipeline()

app = App("panel: prediction_label")
header = AppHeader("PredictionLabel", show_state=True)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))

label = PredictionLabel(pipeline, CLASSES, show_probability=True)


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        label.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
