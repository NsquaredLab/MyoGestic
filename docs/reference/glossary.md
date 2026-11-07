---
title: "Glossary"
---
Terms that mean different things in different parts of the codebase. The "common mistakes" callouts in concept pages link back here where a term is ambiguous.

### Filter

Three meanings, kept separate by convention:

1. Acquisition conditioning via `Stream(notch_hz=50)` or `60` (`0` is off). Filters the samples before they reach the ring buffer and recording, so training and live prediction see the conditioned signal. The setting is saved in the take metadata.
2. Display transform in `SignalViewer`. Applies an optional 50/60 Hz mains-hum notch, then rectification, DC removal or RMS envelope to the displayed signal. Recording and `extract()` retain the acquired samples. See the widget tooltip.
3. Post-prediction smoother like `OneEuroFilter` or `GaussianFilter` from `myogestic.outputs.filters`. Smooths the prediction output vector, such as a pose or control command, before it leaves the app. UI panel via `PostProcessor`.

### Source

A Protocol with `connect()` / `read()` / `disconnect()`. Wraps a device, file, or transport behind a uniform interface. See [Add a custom source](../how-to/add-a-source.md).

### Target

A Protocol with `bind()` / `send()` / `stop()`, optionally a `capabilities()` list of what it can
drive, such as a prosthesis on a serial port, a motor controller, a cursor or the Virtual Hand. It receives *named* values from a control map, can refuse a
configuration at `bind`, and gets range, clamping, dead zone, debounce and rest-on-teardown
from the [bus](#dof). Implement `send` for your device's transport. See
[Drive your own device](../how-to/add-a-target.md).

### Outlet { #output }

A class with `.push(data)` and a daemon thread that sends the latest pushed value to its destination at `hz`. It takes an array, paces one wire, and has no aliases, no declared range and no rest on shutdown. User code owns it. Drive a device through a [Target](#target), which can send values through an outlet, and `RemoteTarget` owns one `LSLOutlet` per address it drives. See [Publish a data stream](../how-to/add-an-output.md).

### Stream

A named ring buffer in `ctx.streams`, fed by one Source. Many widgets and the predict thread read from it concurrently; the buffer's `threading.Lock` keeps reads/writes coherent.

### Window

A slice of a Stream's ring buffer at the current time. Length set by `Stream(window_ms=...)`. Returned channels-first by `Stream.get_window()` to match what feature extractors expect.

### Trial

One labelled segment of a recorded take, containing the data between two consecutive label timestamps in `LabelEvent`, or between the last label and the end of the recording. The training window iterators slice trials into overlapping windows.

### Recording / Session

One `app.start_recording()` → `app.stop_recording()` cycle. Persisted as a folder during capture, packed to a `.mg.zip` archive on stop. Both layouts loadable via `myogestic.session.open_session_store(path)`. Takes go under `data/<ID>/recordings/`, or `predictions/` when started during prediction, as `<ID>_<YYYYMMDD-HHMM>_<what>.mg.zip`. Saved models use `data/<ID>/models/`. Without an ID, these folders sit directly under `data/`.

### DOF

A degree of freedom in the controlled output, such as one finger joint or one robot axis. A multi-DOF model predicts several at once and composes them into a single output vector.

### Pose

A 9-float vector understood by the Virtual Hand Interface (VHI). Indices 0–5 carry six controls in order, thumb flexion, thumb abduction, then index, middle, ring and little flexion. Indices 6, 7 and 8 carry wrist flexion, abduction and rotation on bone 0, which parents every digit and turns the whole hand. Rotation spans `±179°`; at `±180°` the Euler read-back wraps and reports the opposite sign. Values clipped to `[-1, 1]`.

### Bridge

A subprocess pattern for webcam and ultrasound sources that would otherwise saturate a Python thread. The bridge writes frames to a Zarr array and publishes a clock stream over LSL; the main app reads timestamps, not pixels.

### Predict thread / acquisition thread / output thread

Three recurring daemon-thread roles alongside the GUI:

- Acquisition (one per Stream): `Source.read` → ring buffer → optional Zarr append. Display snapshots are built on demand by the GUI.
- Predict (one, only when `Pipeline` is attached): while predicting, wakes every `1/predict_hz`, runs `extract` → `predict`, writes to `pipeline.predictions`.
- Output (one per `Outlet`): drains the latest pushed value to its destination at the output's own `hz`.

The main thread stays on the GUI. See [Threading](../concepts/threading.md).
