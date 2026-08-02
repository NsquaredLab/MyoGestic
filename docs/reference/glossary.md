# Glossary

Terms that mean different things in different parts of the codebase. The "common mistakes" callouts in concept pages reference back here when ambiguity bites.

### Filter

Three meanings, kept separate by convention:

1. **Display transform** in `SignalViewer` (an optional 50/60 Hz mains-hum notch, then rectify, DC removal, or RMS envelope). Affects only what's drawn on screen - never recording, never `extract()`, never the model. See the widget tooltip.
2. **Post-prediction smoother** like `OneEuroFilter` or `GaussianFilter` from `myogestic.outputs.filters`. Smooths the *prediction output vector* (pose, control command) before it leaves the app. UI panel via `PostProcessor`.

### Source

A Protocol with `connect()` / `read()` / `disconnect()`. Wraps a device, file, or transport behind a uniform interface. See [Add a custom source](../how-to/add-a-source.md).

### Output

A class with `.push(data)` and a daemon thread that sends the latest pushed value to its destination at `hz`. User-owned - not registered with the app. A paced sender, not a way to drive a device: anything that moves is a **Target**, and an output is what a target may write *through*. See [Publish a data stream](../how-to/add-an-output.md).

### Stream

A named ring buffer in `ctx.streams`, fed by one Source. Many widgets and the predict thread read from it concurrently; the buffer's `threading.Lock` keeps reads/writes coherent.

### Window

A slice of a Stream's ring buffer at the current time. Length set by `Stream(window_ms=...)`. Returned **channels-first** by `Stream.get_window()` to match what feature extractors expect.

### Trial

One labelled segment of a recorded session - the data between two consecutive label timestamps in `LabelEvent`. The training window iterators slice trials into overlapping windows.

### Recording / Session

One `app.start_recording()` → `app.stop_recording()` cycle. Persisted as a folder during capture, packed to a `.session.zip` archive on stop. Both layouts loadable via `myogestic.session.open_session_store(path)`.

### DOF

A "degree of freedom" in the controlled output - e.g. one finger joint, or one axis of a robot. A multi-DOF model predicts several at once and composes them into a single output vector.

### Pose

A 9-float vector understood by the Virtual Hand Interface (VHI). Indices 0–5 carry the six controls it drives — thumb flexion, thumb abduction, then index, middle, ring and little flexion. Indices 6, 7 and 8 carry wrist flexion, abduction and rotation — bone 0, which parents every digit, so the whole hand turns. Rotation spans `±179°` rather than `±180°`: at exactly half a turn the Euler read-back wraps and reports the opposite sign. Values clipped to `[-1, 1]`.

### Bridge

A subprocess pattern for heavy-data sources (webcam, ultrasound) that would otherwise saturate a Python thread. The bridge writes frames to a Zarr array and publishes a clock stream over LSL; the main app reads timestamps, not pixels.

### Predict thread / acquisition thread / output thread

The three daemon-thread categories that run alongside the GUI:

- **Acquisition** (one per Stream): `Source.read` → ring buffer → display snapshot → optional Zarr append.
- **Predict** (one, only when `Pipeline` is attached): wakes every `1/predict_hz`, runs `extract` → `predict`, writes to `pipeline.predictions`.
- **Output** (one per Output): drains the latest pushed value to its destination at the output's own `hz`.

The main thread stays on the GUI. See [Threading](../concepts/threading.md).
