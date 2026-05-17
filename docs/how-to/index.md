# How-to guides

Recipes for specific tasks. Each guide assumes you've worked through [Getting Started](../getting-started.md) and at least skimmed [Concepts](../concepts/index.md).

## Extending the framework

- [Add a custom source](add-a-source.md) - implement the `Source` protocol for a new device, file format, or transport.
- [Add a custom output](add-an-output.md) - push predictions to actuators, robots, or other processes.
- [Add a custom widget](add-a-widget.md) - write a stateless function that draws ImGui commands from `ctx`.
- [Add a custom model](add-a-model.md) - wire `extract` / `train` / `predict` for any ML library.

## Recording and post-processing

- [Record and replay](record-and-replay.md) - capture sessions, read them back programmatically.
- [Record good training data](record-good-training-data.md) - cycle-style recording, how many cycles you actually need, verifying templates before training.
- [Feature extraction cookbook](feature-extraction-cookbook.md) - copy-paste `@pipeline.extract` snippets (RMS+MAV, bandpass+envelope, spectral, sliding RMS, onset detection, multi-stream fusion).
- [Post-process predictions](post-process-output.md) - `FilterControl` and `myogestic.filters` for output smoothing.
- [Integrate the Virtual Hand](integrate-vhi.md) - `myogestic.interfaces.virtual_hand` and the launcher pattern.

## Operations

- [Run headless (no GUI)](headless-mode.md) - unattended recording and prediction; signal handling; protocol-driven scripts.
