---
title: "Post-process predictions"
---
`myogestic.outputs.filters` smooths prediction vectors, including a 9-float pose or proportional actuator command. These are not DSP filters for raw EMG. Filter raw EMG upstream of `extract()` with a domain library such as scipy.

## Use the [`PostProcessor`][myogestic.widgets.PostProcessor] widget

Drop it in `@app.ui` and you get a compact Smoothing row with the One Euro / Gaussian / Identity options. Here `bus` has a continuous `grip` alias:

```python
from myogestic.widgets import PostProcessor
import time

pose_filter = PostProcessor(hz=20.0)


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    pose_smooth = pose_filter(pose, timestamp=time.monotonic())
    bus.push({"grip": float(pose_smooth[0])})
    return {"pose": pose_smooth}


@app.ui
def ui(ctx):
    with grid[6, 0]:
        pose_filter.ui()  # compact row; Settings opens the parameters
```

The default compact row shows the filter combo, estimated latency in mono and an
icon-only settings button. In narrow cells, the combo takes its own row so Settings
stays reachable. The settings popover contains:

- A muted description of the selected filter
- Captions above each parameter slider, with right-aligned mono values
- An icon-only Reset action that clears smoothing history. Use it after Train to prevent blending predictions from different models.

Use `PostProcessor(hz=20.0, compact=False)` for the full panel. It keeps the filter
combo, Reset action and mono delay visible, with parameter controls in two columns
when space permits and one column in narrow cells. `FilterProcessor` uses the same
full-panel controls for a custom filter palette.

One Euro's parameters update in place, preserving smoothing history during tuning. Gaussian rebuilds its kernel when you change its window.

## Choosing a filter

| Filter | When to use it |
|--------|----------------|
| One Euro | Hand tracking, pose vectors, anything where you want fast moves to cut through and slow moves to smooth. Default for pose output. |
| Gaussian | Steady, predictable lag. Good when you want the same smoothing regardless of motion speed. |
| Identity | Comparison baseline; passthrough. |

### OneEuro tuning

[`OneEuroFilter(hz, min_cutoff_hz, beta, derivative_cutoff_hz)`][myogestic.outputs.filters.OneEuroFilter]:

- `hz` - your tick rate (`predict_hz`). Used as fallback dt when `timestamp` isn't passed.
- `min_cutoff_hz` - cutoff (Hz) at zero velocity. Lower = smoother at rest. Default 1.0.
- `beta` - velocity-to-cutoff gain. Higher = more responsive on fast moves. Default 0.02. Increase it if fast movements lag; decrease it if the output varies at rest.
- `derivative_cutoff_hz` - cutoff for the velocity smoother. Rarely needs tuning. Default 1.0.

The cutoff is `min_cutoff_hz + beta * |velocity|`. Fast motion raises the cutoff for responsiveness; slow motion lowers it for smoothing.

### Gaussian tuning

[`GaussianFilter(n_vectors, sigma)`][myogestic.outputs.filters.GaussianFilter]:

- `n_vectors` - number of past samples to weight. Default 5.
- `sigma` - Gaussian width. Default 1.0 (≈ standard deviation of the kernel).

Higher `n_vectors` and `sigma` mean more lag and more smoothing. Linear, no adaptation.

## Use a bare filter

If you don't need the UI panel:

```python
from myogestic.outputs.filters import OneEuroFilter

pose_filter = OneEuroFilter(hz=20.0, min_cutoff_hz=1.0, beta=0.02)


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    pose_smooth = pose_filter(pose, timestamp=time.monotonic())
    bus.push({"grip": float(pose_smooth[0])})
    return {"pose": pose_smooth}
```

Pass a monotonic `timestamp` to compute elapsed dt when tick intervals vary. Otherwise the filter assumes `1/hz`.

[`make_filter(name, hz, **kwargs)`][myogestic.outputs.filters.make_filter] is the dispatch helper used by `PostProcessor`:

```python
from myogestic.outputs.filters import make_filter

pose_filter = make_filter("one_euro", hz=20.0, min_cutoff_hz=1.0, beta=0.05)
# or
pose_filter = make_filter("gaussian", n_vectors=5, sigma=1.0)
```

## Reset timing

Whenever the upstream signal *resumes* after being stopped or rebuilt:

- After `pipeline.start_training()` finishes - call `pose_filter.reset()` (or the PostProcessor version) before the new model starts predicting. Otherwise the first few frames of the new model blend with the previous model's tail.
- After `pipeline.start_predicting()` *and* the previous filter state is stale.
- On model swap (`pipeline.load_model`).

The example pattern:

```python
@pipeline.train
def train(data):
    pose_filter.reset()  # call from inside train
    return MyModel().fit(...)
```

`PostProcessor` exposes `.reset()` too.

## Filter placement

Inside `predict()`, before the bus `.push()`. The filter runs on the predict thread, smooths the freshly computed pose, and pushes the smoothed command. Both the target (`bus.push`) and the widgets (`pipeline.predictions`) receive smoothed values.

Keep filtering outside the model. The model should produce raw predictions;
separate smoothing lets the user tune it live.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for errors by symptom.

- Filter raw EMG upstream of `extract()`, for example with scipy.signal. `SignalViewer`'s 50/60 Hz mains notch, rectify, dc removal and rms-envelope affect the display only. They do not change what `extract()` receives.
- Filtering classification output (integer class indices). The filter expects a float vector. For classification, hold a smoothed soft-output (probabilities) and argmax that, or use a model with its own temporal smoothing built-in.
- Forgetting `pose_filter.reset()` after training. The first predictions blend with the previous model's tail.
- Per-channel filter parameters. `OneEuroFilter` applies the same parameters to every dimension. If you want different smoothing per joint (e.g. fingertips smoother than wrist), run multiple filters and concatenate.
