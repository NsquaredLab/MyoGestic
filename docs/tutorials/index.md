# Start here

Complete, runnable experiments. Each walks through a real file under `examples/` line by line — open the file in your editor and read alongside, since the code blocks are pulled from it and cannot drift.

- [EMG classification](emg-classification.md) - `examples/synthetic/emg_classification.py`. Two-class Rest/Fist with CatBoost on RMS+MAV features. The best first read: it establishes the App + Stream + Pipeline pattern every other page assumes.
- [EMG regression with VHI](emg-regression-with-vhi.md) - `examples/synthetic/emg_regression.py`. Continuous 5-DOF target with a CatBoost multi-output regressor, recorded via VHI's gRPC control plane and pushed back via the LSL data plane.
- [Examples directory](examples-index.md) - one-paragraph summary of each runnable example under `examples/synthetic/`, with the run command and what's tweakable.

Once these make sense, the rest of the [guides](../how-to/index.md) are task recipes, grouped by job: driving a device, recording, models and features, extending the framework.
