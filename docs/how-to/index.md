# How-to guides

Recipes for specific tasks. Each guide assumes you've worked through [Getting Started](../getting-started.md) and at least skimmed [Concepts](../concepts/index.md).

## Extending the framework

- [Add a custom source](add-a-source.md) - implement the `Source` protocol for a new device, file format, or transport.
- [Drive your own device](add-a-target.md) - implement the `Target` protocol so a control map drives your prosthesis on a serial port, your motors, your cursor. Three methods and a write to a port. **Everything MyoGestic moves goes through one of these.**
    - [Drive a remote target](drive-a-remote-target.md) - only if your device is *already its own program*, like the Virtual Hand. MyoGestic's side is written for you (`RemoteTarget`); this page is the contract yours has to serve.
- [Add a custom widget](add-a-widget.md) - write a stateless function that draws ImGui commands from `ctx`.
- [Add a custom model](add-a-model.md) - wire `extract` / `train` / `predict` for any ML library.

## Recording and post-processing

- [Record and replay](record-and-replay.md) - capture sessions, read them back programmatically.
- [Record good training data](record-good-training-data.md) - cycle-style recording, how many cycles you actually need, verifying templates before training.
- [Feature extraction cookbook](feature-extraction-cookbook.md) - copy-paste `@pipeline.extract` snippets (RMS+MAV, bandpass+envelope, spectral, sliding RMS, onset detection, multi-stream fusion).
- [Post-process predictions](post-process-output.md) - `PostProcessor` and `myogestic.outputs.filters` for output smoothing.
- [Publish a data stream](add-an-output.md) - an `Output` is a paced sender for telemetry: predictions to a recorder, an LSL stream another application reads. If something *moves*, you want a target, not this.

## The Virtual Hand

The one remote target this project ships. The contract it serves is generic — see [Drive a remote target](drive-a-remote-target.md) — so a device that is not a hand needs neither of these pages.

- [Install the Virtual Hand](install-vhi.md) - the installer CLI, and where a build is looked for.
- [Integrate the Virtual Hand](integrate-vhi.md) - `myogestic.vhi.virtual_hand`, the launcher pattern, and what VHI calls its own controls.

## Operations

- [Run headless (no GUI)](headless-mode.md) - unattended recording and prediction; signal handling; protocol-driven scripts.
