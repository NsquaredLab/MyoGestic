---
title: "Guides"
---
Start with [EMG classification](../tutorials/emg-classification.md). It runs in one command
and introduces the App + Stream + Pipeline pattern.

## Start here

Complete runnable experiments, walked through line by line against a real file in `examples/`.

- [EMG classification](../tutorials/emg-classification.md) - two-class Rest/Fist with CatBoost on RMS+MAV features. Start here.
- [EMG regression with VHI](../tutorials/emg-regression-with-vhi.md) - continuous 5-DOF control, recorded through the Virtual Hand and pushed back to it.
- [Examples directory](../tutorials/examples-index.md) - one paragraph on each runnable example, with its command and what is worth changing.

## Connecting hardware

Getting samples out of an amplifier and into a `Stream`.

- [Pick a device from the UI](pick-a-device.md) - `DevicePicker`: choose the amplifier from a dropdown at runtime instead of hardcoding it. Start here if you are new to the hardware.
- [Connect OTB devices](connect-otb-devices.md) - the OT Bioelettronica sources in detail: wiring, modes, channel geometry, dropout counters.

## Driving a device

Drive a device through a target with three methods and a TOML control map
that connects model outputs to controls. [Concepts › Controls](../concepts/controls.md) explains the
system itself.

- [Drive your own device](add-a-target.md) - your prosthesis, motors or cursor, from Python. Start here: the copyable example runs without hardware.
- [Drive a remote target](drive-a-remote-target.md) - the contract to serve if your device is already its own program.
- [Build a remote target, stage by stage](../tutorials/your-first-remote-target.md) - that same contract, built in seven stages with a checkpoint at each.
- [Integrate the Virtual Hand](integrate-vhi.md) - the one remote target this project ships.
- [Install the Virtual Hand](install-vhi.md) - the installer CLI, and where a build is looked for.

## Recording

- [Enable on-disk recording](enable-recording.md) - the four lines that start writing sessions.
- [Record and replay](record-and-replay.md) - capture sessions, read them back programmatically.
- [Record good training data](record-good-training-data.md) - cycle-style recording, how many cycles you actually need, verifying templates before training.
- [Record for proportional control](record-for-proportional-control.md) - graded target levels and a followed-cursor block for proportional control.
- [Track a force target](track-a-force-target.md) - isometric force tracking against a trapezoid, on an amplifier AUX channel, with the target recorded as its own stream.

## Models and features

- [Add a custom model](add-a-model.md) - wire `extract` / `train` / `predict` for any ML library.
- [Record for proportional control](record-for-proportional-control.md) - check the recording protocol if a regressor stays at rest below 30 % effort or reverses as the participant contracts harder.
- [Feature extraction cookbook](feature-extraction-cookbook.md) - copy-paste `@pipeline.extract` snippets (RMS+MAV, bandpass+envelope, spectral, sliding RMS, onset detection, multi-stream fusion).
- [Use the recipe feature set](use-recipe-features.md) - the shipped feature recipes.
- [Keep state between pipeline stages](inter-stage-state.md) - rolling windows, stateful models, gating side effects on change.
- [Post-process predictions](post-process-output.md) - `PostProcessor` and `myogestic.outputs.filters` for output smoothing.

## Extending the framework

- [Add a custom source](add-a-source.md) - implement the `Source` protocol for a new device, file format or transport.
- [Add a custom widget](add-a-widget.md) - a class with a `.ui(ctx)` method that draws ImGui commands.
- [Publish a data stream](add-an-output.md) - use an `Outlet` for paced telemetry to another application. Use a target to drive a device.

## Operations

- [Run headless (no GUI)](headless-mode.md) - unattended recording and prediction; signal handling; protocol-driven scripts.
