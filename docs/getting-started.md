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
| `zarrs` | the Rust-accelerated Zarr codec pipeline |

## Run a protocol

The examples live in the repository. Clone it, sync it with uv and start Myocontrol:

```bash
git clone https://github.com/NsquaredLab/MyoGestic.git
cd MyoGestic
uv sync --extra examples --extra grpc
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
```

!!! info "No amplifier?"
    In the **Connect** step, use the device picker to choose **Synthetic (no hardware)**, then press **Connect**. Set a participant ID before recording. The synthetic source uses sine waves by default; stochastic EMG is opt-in with `SyntheticSource(waveform="emg")`.

The [browser playground](playground/) follows **Connect → Record → Train → Predict** with a synthetic EMG source and an LDA classifier. Takes stay in the tab's temporary filesystem; reloading clears them.

## Where your takes go

Each saved take is one `.mg.zip`, named by participant, start time and the gestures recorded or the run name. Takes started while a model predicts go to `predictions/`.

```text
data/
└── P-001/
    ├── recordings/   P-001_20261106-1412_R+F.mg.zip
    ├── predictions/  P-001_20261106-1430_guided.mg.zip
    └── models/       P-001_20261106-1425_tuple.joblib
```

## Write your own

This is the whole loop: a stream, a signal viewer and recording controls. Start an LSL outlet named `EMG`, then press **Connect** in the viewer to attach it.

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
