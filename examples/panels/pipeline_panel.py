"""``pipeline_panel`` in isolation — Train / Predict / log as one panel.

The ML control surface: a Train button, a Predict/Stop toggle, a state
pill, and the training log — buttons grey out based on ``pipeline.state``.
This example wires a **complete, working** pipeline (extract → train →
predict) around a live synthetic stream, using a tiny NumPy
nearest-centroid "model" so it needs no ML dependencies:

    * Click **Train** — fits centroids (state pill → TRAINING → idle, log
      fills in).
    * Click **Predict** — the predict loop classifies live windows.

It also shows the ``SaveModelButton`` / ``LoadModelButton`` helpers
wired to a throwaway temp file, so every ``myogestic.ml.widgets`` widget is
exercised in one place.

Run with:
    uv run python examples/panels/pipeline_panel.py
"""

import tempfile
from pathlib import Path

import numpy as np
from _fixtures import SyntheticSource

from myogestic import App, Stream, TrainingData
from myogestic.ml import Pipeline, load_pickle, save_pickle
from myogestic.ml.widgets import LoadModelButton, PipelinePanel, SaveModelButton

CLASSES = ["Rest", "Fist", "Open", "Pinch"]
MODEL_PATH = str(Path(tempfile.mkdtemp(prefix="panel_pipeline_")) / "model.pkl")

app = App("panel: pipeline_panel")
app.streams(Stream("emg", source=SyntheticSource(n_channels=8), window_ms=200))

pipeline = Pipeline(app)
pipeline.save_model = save_pickle
pipeline.load_model = load_pickle
# Non-empty training data so Train isn't a no-op. The train fn below ignores
# the paths (it fits on synthetic features), but it must be non-empty.
pipeline.training_data = TrainingData(
    paths=["<synthetic>"], class_names=CLASSES, classes=set(range(len(CLASSES)))
)


def _rms(window: np.ndarray) -> np.ndarray:
    """Per-channel RMS — the feature vector (channels-first window)."""
    return np.sqrt(np.mean(window.astype(np.float64) ** 2, axis=1))


@pipeline.extract
def extract(windows) -> np.ndarray:
    return _rms(windows["emg"])


@pipeline.train
def train(data: TrainingData):
    # Fit one centroid per class on synthetic labelled features. Stands in
    # for a real sklearn/torch fit without the optional dependency.
    rng = np.random.default_rng(0)
    n_feat = 8
    centroids = np.stack([rng.normal(loc=i, scale=0.3, size=n_feat) for i in range(len(CLASSES))])
    pipeline.train_log.append(f"Fitted {len(CLASSES)} centroids · {n_feat} features")
    return {"centroids": centroids}


@pipeline.predict
def predict(model, features):
    dist = np.linalg.norm(model["centroids"] - features, axis=1)
    proba = np.exp(-dist)
    proba /= proba.sum()
    return {"class": int(np.argmin(dist)), "proba": proba.astype(np.float32)}


panel = PipelinePanel(pipeline)
save_btn = SaveModelButton(pipeline, MODEL_PATH)
load_btn = LoadModelButton(pipeline, MODEL_PATH)


@app.ui
def ui(ctx):
    from imgui_bundle import imgui

    panel.ui()
    save_btn.ui()
    imgui.same_line()
    load_btn.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
