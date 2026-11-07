---
title: "Use the recipe feature set"
---
`myogestic.recipes.features` provides five time-domain EMG features:

| Name  | Function                | What it captures                                       |
|-------|-------------------------|--------------------------------------------------------|
| `rms` | Root-mean-square        | Channel envelope amplitude.                            |
| `mav` | Mean absolute value     | Same neighbourhood as RMS, cheaper to compute.         |
| `wl`  | Waveform length         | Sum of `|Δx|` - sensitive to high-frequency content.   |
| `var` | Variance                | Energy around the per-window mean.                     |
| `zc`  | Zero-crossing count     | Per-channel oscillation rate.                          |

Use these baselines for a five-minute setup check. Choose and add
features suited to your experiment for further work.

## The shape contract

Every function takes an EMG window of shape `(n_channels, n_samples)`
and returns a per-channel scalar vector of
shape `(n_channels,)` with dtype `float32`.

```python
import numpy as np
from myogestic.recipes.features import rms

emg = np.random.randn(8, 256).astype(np.float32)  # 8 channels, 256 samples
rms(emg).shape  # (8,)
rms(emg).dtype  # dtype('float32')
```

The shape and dtype are part of the contract. Stick to them when writing
your own feature for `FeatureSelector` and the typed pipeline.

## Wiring into a pipeline

`FeatureSelector` takes a `{name: fn}` dict and exposes a wrapping mono toggle chip for
each feature under a Features caption. Active chips are tinted; all chips can be
deselected, but extraction then raises until at least one is selected:

```python
from myogestic.recipes.features import rms, mav, wl, var, zc
from myogestic.widgets import FeatureSelector

feats = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"],  # start with these active
)


@pipeline.extract
def extract(windows):
    return feats(windows["emg"])  # → (n_features * n_channels,)


@app.ui
def ui(ctx):
    with grid[2, 0]:
        feats.ui()
```

`feats(window)` concatenates the selected features. Toggling a feature changes
output dimensionality without invalidating the trained model. Sklearn and
CatBoost raise shape-mismatch errors if prediction uses a different shape.
Choose one of these patterns:

- Lock the selector after training - render the feature toggles
  greyed out once `pipeline.app.ctx.state == "predicting"` so the user can't
  silently break the live loop.
- Treat a toggle as "retrain me" - keep your own snapshot of
  `feats.active_names` between frames and, when it changes, prompt the
  user to retrain (or kick off training automatically).

The first is the safer default for a demo; the second is what you want
when feature selection is part of the user's iteration loop.

## Mixing in your own

A feature is a `Callable[[np.ndarray], np.ndarray]` matching the
shape contract. Drop yours in next to the recipe ones:

```python
import numpy as np
from myogestic.recipes.features import rms, mav


def slope_sign_changes(emg: np.ndarray) -> np.ndarray:
    """Count slope-sign changes per channel - classic Hudgins SSC feature."""
    d1 = np.diff(emg, axis=1)
    flips = (d1[:, :-1] * d1[:, 1:]) < 0
    return np.sum(flips, axis=1).astype(np.float32)


feats = FeatureSelector(
    {"RMS": rms, "MAV": mav, "SSC": slope_sign_changes},
    default=["RMS", "MAV", "SSC"],
)
```

## Choose a feature pipeline

These five features operate on time-domain sEMG windows. Use a dedicated
pipeline for spectral features, frozen-network embeddings or MyoVerse
decomposition output.

Use it for:

* A *first cut* at a new dataset, to confirm wiring before tuning.
* A *baseline* to beat when adding model-side complexity.
* A *demo* that needs to be five lines, not fifty.

Replace it for:

* HD-sEMG with established spectral or NMF pipelines - use the existing
  feature stack from your prior work; `FeatureSelector` accepts any
  shape-conforming callable.
* End-to-end deep models where features *are* the raw window - skip
  feature extraction entirely and feed the window to the model.

## See also

* [Feature extraction cookbook](feature-extraction-cookbook.md) - recipes
  for windowing, normalization, and spectral features.
* [`myogestic.recipes.features`](../api/core.md) - full module reference.
* [`myogestic.widgets.FeatureSelector`](../api/widgets.md) - the
  GUI-toggleable feature dispatcher.
