"""``prediction_label`` in isolation — the current predicted class + confidence.

A big read-out of the pipeline's latest prediction (class name + optional
probability bar). It only reads ``pipeline.predictions``, so a tiny
duck-typed stub stands in for a full trained Pipeline here.

Run with:
    uv run python examples/panels/prediction_label.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import PredictionLabel

CLASSES = ("Rest", "Fist")


class _FakePipeline:
    # prediction_label reads only `.predictions`.
    predictions = {"class": 1, "proba": np.array([0.18, 0.82], dtype=np.float32)}


pipeline = _FakePipeline()

app = App("panel: prediction_label")

label = PredictionLabel(pipeline, CLASSES, show_probability=True)


@app.ui
def ui(ctx):
    label.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
