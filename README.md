<img src="https://raw.githubusercontent.com/NsquaredLab/MyoGestic/main/docs/images/myogestic_logo.png" height="200">

# MyoGestic

[![Python](https://img.shields.io/badge/python-%3E=3.12-blue)](https://www.python.org/downloads/)
[![License: GPL v3](https://img.shields.io/badge/license-GPL%20v3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Docs](https://img.shields.io/badge/docs-nsquaredlab.github.io%2FMyoGestic-blue)](https://nsquaredlab.github.io/MyoGestic/)

Real-time biosignal experiment GUI builder. A compact Python framework that
turns a short script into a live experiment - signal viewers, recording,
training, prediction - without classes, registries, or config files.

Built at the [n-squared lab](https://www.nsquared.tf.fau.de/) at
Friedrich-Alexander-Universität Erlangen-Nürnberg (FAU) for the myocontrol
research community. v2 is a ground-up rewrite of [MyoGestic v1](https://github.com/NsquaredLab/MyoGestic/tree/v1) focused on small,
composable API surfaces and live extensibility.

**Provides**: live LSL ingest, on-disk recording (Zarr → `.session.zip`),
ML pipeline lifecycle (train/predict on their own threads), Dear ImGui
widgets, output filters, gRPC + LSL dual-plane integration with the
[Virtual Hand Interface](https://github.com/NsquaredLab/MyoGestic-VHI).

**Does not provide**: DSP, ML models, feature extraction. You bring scipy,
MyoVerse, CatBoost, PyTorch - whatever fits.

## Try it in your browser

A live MyoGestic app runs entirely in your browser via Pyodide at
**<https://nsquaredlab.github.io/MyoGestic/playground/>**. Synthetic EMG,
in-memory recording, sklearn LDA training, live prediction. No install.

## Install

```bash
uv sync                      # core dependencies only
uv sync --extra examples     # + catboost, myoverse, torch, scikit-learn (to run the demos)
uv sync --extra dev          # + pytest, ruff, the examples extras above
```

Optional extras: `[brainflow]` `[bdi]` `[serial]` `[grpc]` `[zarrs]` `[docs]`.
`[grpc]` pulls in `grpcio` + `grpcio-tools` + `protobuf` for the VHI control
plane.

## Quick start

```python
from myogestic import App, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import recording_controls, signal_viewer

app = App("Hello EMG")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))

@app.ui
def ui(ctx):
    signal_viewer(ctx, "emg")
    recording_controls(ctx, ["Rest", "Fist"],
                       on_record=app.start_recording,
                       on_stop=app.stop_recording)

app.run()
```

That's the whole loop. Add a `Pipeline`, decorate `extract` / `train` /
`predict`, and you have a closed-loop experiment.

Six runnable end-to-end demos live in
[`examples/synthetic/`](https://github.com/NsquaredLab/MyoGestic/tree/main/examples/synthetic):

- `emg_classification.py` - the canonical first read (CatBoost binary)
- `emg_classification_grpc.py` - adds the VHI gRPC control plane
- `emg_regression.py` - continuous 5-DoF regression
- `emg_regression_raulnet.py` - same flow with a PyTorch Lightning CNN
- `emg_32ch_multi_model.py` - selectable classifier + Save/Load
- `emg_popout_layout.py` - the same flow in a dockable tear-off layout

## Documentation

The full docs live as a [ProperDocs](https://properdocs.org/) site under
[`docs/`](https://github.com/NsquaredLab/MyoGestic/tree/main/docs) - tutorials, how-to guides, concept explanations, an
auto-generated API reference, and the in-browser playground.

Build and serve locally:

```bash
uv sync --extra docs --extra grpc --extra serial
uv run properdocs serve
```

Then open `http://127.0.0.1:8000/MyoGestic/`.

Quick links into the source:

- **[Getting Started](https://github.com/NsquaredLab/MyoGestic/blob/main/docs/getting-started.md)** - install + run the synthetic-EMG demo.
- **[Tutorials](https://github.com/NsquaredLab/MyoGestic/tree/main/docs/tutorials)** - `emg-classification`, `emg-regression-with-vhi`.
- **[How-to guides](https://github.com/NsquaredLab/MyoGestic/tree/main/docs/how-to)** - recipes (custom source, custom widget, custom model, integrate the Virtual Hand, install VHI, the recipe feature set, ...).
- **[Concepts](https://github.com/NsquaredLab/MyoGestic/tree/main/docs/concepts)** - architecture, streams, pipeline, threading, recording, the `Px`/`Fr` grid, the `EdgeTrigger` pattern.
- **[API reference](https://github.com/NsquaredLab/MyoGestic/tree/main/docs/api)** - auto-generated from docstrings.
- **[API cheatsheet](https://github.com/NsquaredLab/MyoGestic/blob/main/docs/reference/api-cheatsheet.md)** - the most-used public symbols on one page.
- **[Playground](https://nsquaredlab.github.io/MyoGestic/playground/)** - the in-browser demo (no install).

The docs are deployed to GitHub Pages via [`.github/workflows/docs.yml`](https://github.com/NsquaredLab/MyoGestic/blob/main/.github/workflows/docs.yml) on every push to `main`.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run ruff check .
```

Some integration tests need a live LSL outlet (port-bind sensitive in
sandboxed CI). A handful of test files lag recent refactors and are
scheduled for cleanup.

## How to cite

If you use MyoGestic in your research, please cite our
[Science Advances paper](https://www.science.org/doi/abs/10.1126/sciadv.ads9150):

```bibtex
@article{Simpetru2025,
    author  = {Raul C. S{\^i}mpetru and Dominik I. Braun and Arndt U. Simon
               and Michael M{\"a}rz and Vlad Cnejevici
               and Daniela Souza de Oliveira and Nico Weber and Jonas Walter
               and J{\"o}rg Franke and Daniel H{\"o}glinger and Cosima Prahm
               and Matthias Ponfick and Alessandro Del Vecchio},
    title   = {MyoGestic: EMG interfacing framework for decoding multiple
               spared motor dimensions in individuals with neural lesions},
    journal = {Science Advances},
    volume  = {11},
    number  = {15},
    pages   = {eads9150},
    year    = {2025},
    doi     = {10.1126/sciadv.ads9150},
    url     = {https://www.science.org/doi/abs/10.1126/sciadv.ads9150},
}
```

## License

MyoGestic is licensed under the
[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html)
(GPL-3.0), matching the v1 release. Derivative work must remain open under
the same license.
