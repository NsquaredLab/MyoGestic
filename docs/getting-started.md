---
title: "Getting started"
---

Install the package, run a complete protocol against the synthetic amplifier, then write your own app.

## Install

```bash
pip install myogestic
```

Extras add optional parts. Install one with `pip install "myogestic[grpc]"`.

| Extra | What it adds |
| --- | --- |
| `examples` | CatBoost, MyoVerse, PyTorch and scikit-learn for the demos |
| `grpc` | the Virtual Hand control plane |
| `brainflow` | BrainFlow devices |
| `serial` | serial sources and outputs |
| `zarrs` | the Rust-accelerated Zarr codec |

## Run a protocol

The examples live in the repository. Clone it, sync it with uv and start Myocontrol:

```bash
git clone https://github.com/NsquaredLab/MyoGestic.git
cd MyoGestic
uv sync --extra examples --extra grpc
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
```

!!! info "No amplifier?"
    Each protocol picks its hardware from a dropdown, so the same file runs against the synthetic one when you have none.

## Where your takes go

Each take is one `.mg.zip`, named by participant, start time and the gestures recorded. Takes started while a model predicts go to `predictions/`.

```text
data/
└── P-001/
    ├── recordings/   P-001_20261106-1412_R+F.mg.zip
    ├── predictions/  P-001_20261106-1430_guided.mg.zip
    └── models/       P-001_20261106-1425_catboost.joblib
```

## Write your own

This is the whole loop: a stream, a signal viewer and recording controls.

<!--docs:skip-->
```python
from myogestic import App, Stream
from myogestic.sources import LSLSource
from myogestic.widgets import RecordingControls, SignalViewer

app = App("Hello EMG")
app.streams(Stream("emg", source=LSLSource("EMG"), window_ms=1000))

viewer = SignalViewer("emg")
recording = RecordingControls(
    ["Rest", "Fist"], on_record=app.start_recording, on_stop=app.stop_recording
)


@app.ui
def ui(ctx):
    viewer.ui(ctx)
    recording.ui(ctx)


app.run()
```

<div class="grid cards" markdown>

- Next

    [**Anatomy of an app**](anatomy.md)

- Browse

    [**Widget gallery**](widget-gallery.md)

- Try

    [**Playground**](playground/)

</div>
