# Guides

Every task guide, grouped by what you are trying to do. If you are new, start with
[EMG classification](../tutorials/emg-classification.md): it runs in one command and
establishes the App + Stream + Pipeline pattern everything else assumes.

## Start here

Complete runnable experiments, walked through line by line against a real file in `examples/`.

- [EMG classification](../tutorials/emg-classification.md) - two-class Rest/Fist with CatBoost on RMS+MAV features. The best first read.
- [EMG regression with VHI](../tutorials/emg-regression-with-vhi.md) - continuous 5-DOF control, recorded through the Virtual Hand and pushed back to it.
- [Examples directory](../tutorials/examples-index.md) - one paragraph on each runnable example, with its command and what is worth changing.

## Driving a device

Anything that *moves* is a **target**: three methods, and a TOML control map naming which
model output drives which control. [Concepts › Controls](../concepts/controls.md) explains the
system itself.

- [Drive your own device](add-a-target.md) - your prosthesis, motors or cursor, from Python. **Start here**: the copyable example runs without hardware.
- [Drive a remote target](drive-a-remote-target.md) - the contract to serve if your device is already its own program.
- [Build a remote target, stage by stage](../tutorials/your-first-remote-target.md) - that same contract, built in seven stages with a checkpoint at each.
- [Integrate the Virtual Hand](integrate-vhi.md) - the one remote target this project ships.
- [Install the Virtual Hand](install-vhi.md) - the installer CLI, and where a build is looked for.

## Recording

- [Enable on-disk recording](enable-recording.md) - the four lines that start writing sessions.
- [Record and replay](record-and-replay.md) - capture sessions, read them back programmatically.
- [Record good training data](record-good-training-data.md) - cycle-style recording, how many cycles you actually need, verifying templates before training.

## Models and features

- [Add a custom model](add-a-model.md) - wire `extract` / `train` / `predict` for any ML library.
- [Feature extraction cookbook](feature-extraction-cookbook.md) - copy-paste `@pipeline.extract` snippets (RMS+MAV, bandpass+envelope, spectral, sliding RMS, onset detection, multi-stream fusion).
- [Use the recipe feature set](use-recipe-features.md) - the shipped feature recipes.
- [Keep state between pipeline stages](inter-stage-state.md) - rolling windows, stateful models, gating side effects on change.
- [Post-process predictions](post-process-output.md) - `PostProcessor` and `myogestic.outputs.filters` for output smoothing.

## Extending the framework

- [Add a custom source](add-a-source.md) - implement the `Source` protocol for a new device, file format or transport.
- [Add a custom widget](add-a-widget.md) - a class with a `.ui(ctx)` method that draws ImGui commands.
- [Publish a data stream](add-an-output.md) - an `Output` is a paced sender for telemetry: predictions to a recorder, a stream another application reads. If something *moves*, you want a target, not this.

## Operations

- [Run headless (no GUI)](headless-mode.md) - unattended recording and prediction; signal handling; protocol-driven scripts.
