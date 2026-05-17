# Tutorials

Learning-oriented walkthroughs of complete, runnable experiments. Each tutorial walks through a real file under `examples/` line by line - open the file in your editor and read alongside.

- [EMG classification](emg-classification.md) - `examples/synthetic/emg_classification.py`. Two-class Rest/Fist with CatBoost on RMS+MAV features. Good first read - establishes the App + Stream + Pipeline pattern.
- [EMG regression with VHI](emg-regression-with-vhi.md) - `examples/synthetic/emg_regression.py`. Continuous 5-DOF target with a CatBoost multi-output regressor, recorded via VHI's gRPC control plane and pushed back via the LSL data plane.
- [Examples directory](examples-index.md) - one-paragraph summary of each runnable example under `examples/synthetic/`, with the run command and what's tweakable.

If you're hunting for "how do I do X" rather than "build me an experiment from scratch," try the [how-to guides](../how-to/index.md) instead.
