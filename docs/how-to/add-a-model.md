# Add a custom model

[`Pipeline`][myogestic.ml.Pipeline] doesn't care what your model is. Sklearn, CatBoost, PyTorch, a state machine, a lookup table - anything pickleable works, and even unpickleable models work if you provide your own `save_model` / `load_model`.

The protocol is three decorators on plain functions:

```python
from myogestic.ml import Pipeline, save_pickle, load_pickle
from myogestic.session import iter_labeled_windows

pipeline = Pipeline(app, predict_hz=20)
pipeline.save_model = save_pickle  # or your own
pipeline.load_model = load_pickle


@pipeline.extract
def extract(windows):
    return windows["emg"]  # whatever shape downstream wants


@pipeline.train
def train(data):
    X, y = [], []
    for window, ts, cls in iter_labeled_windows(data.paths, "emg", window_ms=200, hop_ms=100):
        X.append(rms_features(window))
        y.append(cls)
    model = MyClassifier().fit(np.array(X), np.array(y))
    return model


@pipeline.predict
def predict(model, features):
    pred = model.predict(features.reshape(1, -1))[0]
    return {"class": int(pred)}
```

That's the entire surface. Three decorators, no inheritance.

## Case 1: scikit-learn / CatBoost / XGBoost

The straightforward case. Train returns a fitted estimator, predict calls it. See [`examples/synthetic/emg_classification.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_classification.py) for the canonical pattern. Key beats:

```python
@pipeline.train
def train(data):
    if data.is_empty:
        raise ValueError("Tick at least one session.")
    X, y = build_dataset(data.paths)
    model = CatBoostClassifier(iterations=500, depth=6, verbose=False)
    model.fit(X, y)
    return model  # whatever you return goes to predict() unchanged


@pipeline.predict
def predict(model, features):
    cls = int(model.predict(features.reshape(1, -1))[0])
    return {"class": cls, "name": CLASSES[cls]}
```

`save_pickle` round-trips CatBoost / sklearn / XGBoost models without surprises.

## Case 2: PyTorch model

PyTorch models pickle fine for the weights, but you need to handle CUDA-vs-CPU on load:

```python
import torch


@pipeline.train
def train(data):
    X, y = build_dataset(data.paths)
    X_t = torch.tensor(X, dtype=torch.float32, device="cuda")
    y_t = torch.tensor(y, dtype=torch.long, device="cuda")
    net = MyNet(n_in=X.shape[1], n_classes=N).cuda()
    optim = torch.optim.Adam(net.parameters(), lr=1e-3)
    for _ in range(100):
        ...  # standard training loop
    net.eval()
    return net


@pipeline.predict
def predict(model, features):
    x = torch.tensor(features, dtype=torch.float32, device="cuda")
    with torch.no_grad():
        logits = model(x.unsqueeze(0))
        cls = int(logits.argmax(-1).cpu().item())
    return {"class": cls}
```

Custom save/load to handle device:

```python
def save_torch(model, path):
    torch.save(
        {
            "state_dict": model.state_dict(),
            "config": {"n_in": model.n_in, "n_classes": model.n_classes},
        },
        path,
    )


def load_torch(path):
    blob = torch.load(path, map_location="cuda")
    net = MyNet(**blob["config"]).cuda()
    net.load_state_dict(blob["state_dict"])
    net.eval()
    return net


pipeline.save_model = save_torch
pipeline.load_model = load_torch
```

## Case 3: regression (continuous targets)

Use [`iter_aligned_windows`][myogestic.session.iter_aligned_windows] instead of [`iter_labeled_windows`][myogestic.session.iter_labeled_windows] - it pairs each EMG window with a synchronised target vector:

```python
from myogestic.session import iter_aligned_windows


@pipeline.train
def train(data):
    X, Y = [], []
    for sw, targets in iter_aligned_windows(
        data.paths,
        primary="emg",
        aligned=["vhi_guide"],
        window_ms=200,
        hop_ms=50,
    ):
        X.append(rms_features(sw.data))
        Y.append(targets["vhi_guide"])
    return MultiOutputRegressor().fit(np.array(X), np.array(Y))
```

See [`examples/synthetic/emg_regression.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/emg_regression.py) for the full thing - it includes a fallback to `iter_labeled_windows` when no aligned target stream was recorded.

## Pushing predictions to outputs

Predictions go two places: into `pipeline.predictions` (read by widgets) and into your outputs (read by actuators / VHI / downstream apps). Push from inside `predict()`:

```python
@pipeline.predict
def predict(model, features):
    pose = model.predict(features.reshape(1, -1))[0]
    pose_smooth = pose_filter(pose, timestamp=time.monotonic())
    vhi_outlet.push(pose_smooth)  # to the actuator
    return {"pose": pose_smooth}  # to widgets / pipeline.predictions
```

Both happen on the same predict thread; no synchronisation needed.

## Stale-tick guard

If your model is stateful, accept timestamps and ignore stale ticks:

```python
@pipeline.extract
def extract(windows):
    emg, ts = emg_stream.get_window()
    last_ts = float(ts[-1]) if ts.size > 0 else None
    return (emg, last_ts)


@pipeline.predict
def predict(model, features):
    emg, last_ts = features
    return {"state": model.step(emg, last_ts=last_ts)}
```

The model's `step` should return the previous state if `last_ts <= self._last_ts`.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Returning a non-dict from `predict()`.** Silently dropped. Always `return {...}`.
- **Forgetting to set `pipeline.save_model`.** The Save Model button does nothing; user clicks it expecting persistence.
- **Putting feature extraction in `train()`.** Then `predict()` re-runs different code on the same window shape. Keep one `extract()` for both, or factor a shared `featurize(window) -> features` helper.
- **Heavy training in the predict thread.** Don't call `model.fit()` from `predict()` - training has its own thread and its own state. The framework already separates them.
- **Assuming the predict thread is paced.** It is, but `predict_hz` is a *target*, not a guarantee. If the model takes 100 ms but `predict_hz=50` (20 ms target), you fall behind. Profile your `predict()` and either lower `predict_hz` or speed up the model.
