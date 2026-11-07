---
title: "Start here"
---
Complete experiments and a remote-target walkthrough. The classification and regression pages follow files under `examples/`; their snippet blocks are included from those files. Open the example in your editor and read alongside.

- [EMG classification](emg-classification.md) - `examples/synthetic/emg_classification.py`. Two-class Rest/Fist with CatBoost on RMS+MAV features. Start here for the App + Stream + Pipeline pattern.
- [EMG regression with VHI](emg-regression-with-vhi.md) - `examples/synthetic/emg_regression.py`. Continuous 5-DOF target with a CatBoost multi-output regressor, recorded via VHI's gRPC control plane and pushed back via the LSL data plane.
- [Your first remote target](your-first-remote-target.md) - build a separate gRPC/LSL target and drive two axes through a control map.
- [Examples directory](examples-index.md) - one-paragraph summary of each runnable example under `examples/synthetic/`, with the run command and what's tweakable.

The [guides](../how-to/index.md) cover driving devices, recording, models and features, and framework extensions.
