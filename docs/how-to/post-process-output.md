# Post-process predictions

`myogestic.filters` smooths the **prediction output vector** before it leaves the app - the 9-float pose, the proportional control, the actuator command. It is *not* a DSP filter for raw EMG (that belongs upstream of `extract()` and the user's domain library, e.g. scipy).

## The fastest path: [`FilterControl`][myogestic.widgets.FilterControl] widget

Drop it in `@app.ui` and you get a tunable panel with the OneEuro / Gaussian / Identity options:

```python
from myogestic.widgets import FilterControl
import time

pose_filter = FilterControl(hz=20.0, default="one_euro")


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    pose_smooth = pose_filter(pose, t=time.monotonic())
    vhi_outlet.push(pose_smooth)
    return {"pose": pose_smooth}


@app.ui
def ui(ctx):
    with grid[6, 0]:
        pose_filter.ui()  # full panel
```

The panel:

- A button selector (Identity / Gaussian / One Euro)
- Sliders for the active filter's parameters
- A **Reset** button that clears smoothing history (use after Train so the new model's first frames don't get blended with the old one's tail)

Parameters update *in place* - no rebuild - so smoothing history survives live tuning.

## Choosing a filter

| Filter | When to use it |
|--------|----------------|
| **OneEuro** | Hand tracking, pose vectors, anything where you want fast moves to cut through and slow moves to smooth. Default for pose output. |
| **Gaussian** | Steady, predictable lag. Good when you want the same smoothing regardless of motion speed. |
| **Identity** | Comparison baseline; passthrough. |

### OneEuro tuning

[`OneEuroFilter(freq, min_cutoff, beta, d_cutoff)`][myogestic.filters.OneEuroFilter]:

- `freq` - your tick rate (`predict_hz`). Used as fallback dt when `t` isn't passed.
- `min_cutoff` - cutoff (Hz) at zero velocity. Lower = smoother at rest. Default 1.0.
- `beta` - velocity-to-cutoff gain. Higher = more responsive on fast moves. Default 0.02. **Bump this if the hand feels laggy on fast clenches; lower if it twitches at rest.**
- `d_cutoff` - cutoff for the velocity smoother. Rarely needs tuning. Default 1.0.

The filter's secret is that it adapts: cutoff = `min_cutoff + beta * |velocity|`. Fast motion → high cutoff (responsive); slow motion → low cutoff (smooth).

### Gaussian tuning

[`GaussianFilter(window, sigma)`][myogestic.filters.GaussianFilter]:

- `window` - number of past samples to weight. Default 5.
- `sigma` - Gaussian width. Default 1.0 (≈ standard deviation of the kernel).

Higher `window` and `sigma` mean more lag and more smoothing. Linear, no adaptation.

## Without the widget: bare filter

If you don't need the UI panel:

```python
from myogestic.filters import OneEuroFilter

pose_filter = OneEuroFilter(freq=20.0, min_cutoff=1.0, beta=0.02)


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    pose_smooth = pose_filter(pose, t=time.monotonic())
    vhi_outlet.push(pose_smooth)
    return {"pose": pose_smooth}
```

Pass `t` (a monotonic clock value) so the filter computes real-elapsed dt instead of assuming `1/freq`. If your tick rate is jittery, this matters; if it's stable, it doesn't.

[`make_filter(name, hz, **kwargs)`][myogestic.filters.make_filter] is the dispatch helper used by `FilterControl`:

```python
from myogestic.filters import make_filter

pose_filter = make_filter("one_euro", hz=20.0, min_cutoff=1.0, beta=0.05)
# or
pose_filter = make_filter("gaussian", window=5, sigma=1.0)
```

## When to reset

Whenever the upstream signal *resumes* after being stopped or rebuilt:

- After `pipeline.start_training()` finishes - call `pose_filter.reset()` (or the FilterControl version) before the new model starts predicting. Otherwise the first few frames of the new model blend with the previous model's tail.
- After `pipeline.start_predicting()` *and* the previous filter state is stale.
- On model swap (`pipeline.load_model`).

The example pattern:

```python
@pipeline.train
def train(data):
    pose_filter.reset()  # call from inside train
    return MyModel().fit(...)
```

`FilterControl` exposes `.reset()` too.

## Where to put the filter

**Inside `predict()`, before the output `.push()`.** That's the only place. The filter runs on the predict thread, smooths the freshly-computed pose, and pushes the smoothed value. Both the actuator (`vhi_outlet.push`) and the widgets (`pipeline.predictions`) see the smoothed version.

Don't filter inside the model - the model should produce raw predictions; smoothing is a separate concern that the user can tune live.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Filtering raw EMG.** Wrong layer. EMG filtering belongs upstream of `extract()` (scipy.signal, etc.) and is the user's domain. The on-screen filters in `signal_viewer` (rectify, dc removal, rms-envelope) are *display* transforms - they don't affect what `extract()` sees.
- **Filtering classification output (integer class indices).** The filter expects a float vector. For classification, hold a smoothed soft-output (probabilities) and argmax that, or use a model with its own temporal smoothing built-in.
- **Forgetting `pose_filter.reset()` after training.** First few predictions look weird because they're blending with the previous model's tail.
- **Per-channel filter parameters.** `OneEuroFilter` applies the same parameters to every dimension. If you want different smoothing per joint (e.g. fingertips smoother than wrist), run multiple filters and concatenate.
