# Use the contrib feature set

`myogestic.recipes.features` ships five classic time-domain EMG features
that every starter example used to copy-paste:

| Name  | Function                | What it captures                                       |
|-------|-------------------------|--------------------------------------------------------|
| `rms` | Root-mean-square        | Channel envelope amplitude.                            |
| `mav` | Mean absolute value     | Same neighbourhood as RMS, cheaper to compute.         |
| `wl`  | Waveform length         | Sum of `|Δx|` - sensitive to high-frequency content.   |
| `var` | Variance                | Energy around the per-window mean.                     |
| `zc`  | Zero-crossing count     | Per-channel oscillation rate.                          |

These are **baselines** - they get a new project running in five
minutes. They are deliberately not the framework's recommended feature
set; for anything beyond a smoke test, mix them with your own.

## The shape contract

Every function takes one argument - an EMG window of shape
`(n_channels, n_samples)` - and returns one per-channel scalar vector of
shape `(n_channels,)` with dtype `float32`.

```python
import numpy as np
from myogestic.recipes.features import rms

emg = np.random.randn(8, 256).astype(np.float32)   # 8 channels, 256 samples
rms(emg).shape                                     # (8,)
rms(emg).dtype                                     # dtype('float32')
```

The shape and dtype are part of the contract. Stick to them when writing
your own feature so it plugs into `FeatureSelector` (and the typed
pipeline) without surprises.

## Wiring into a pipeline

`FeatureSelector` takes a `{name: fn}` dict and exposes a GUI toggle for
each feature:

```python
from myogestic.recipes.features import rms, mav, wl, var, zc
from myogestic.widgets import FeatureSelector

feats = FeatureSelector(
    {"RMS": rms, "MAV": mav, "WL": wl, "VAR": var, "ZC": zc},
    default=["RMS", "MAV"],          # start with these checked
)

@pipeline.extract
def extract(window):
    return feats(window)            # → (n_features * n_channels,)

@app.ui
def ui(ctx):
    with grid[2, 0]:
        feats.ui()
```

`feats(window)` evaluates every selected feature on `window` and
concatenates the results. **The output dimensionality changes** when
the user toggles a feature, but `FeatureSelector` does NOT invalidate
the trained model - it just mutates its own active-feature set. If you
predict against a feature shape the model wasn't trained on, the
predict call will throw (sklearn / CatBoost both raise a clear
shape-mismatch error). Two reasonable patterns:

- **Lock the selector after training** - render the feature toggles
  greyed out once `pipeline.state == "predicting"` so the user can't
  silently break the live loop.
- **Treat a toggle as "retrain me"** - keep your own snapshot of
  `feats.active_names` between frames and, when it changes, prompt the
  user to retrain (or kick off training automatically).

The first is the safer default for a demo; the second is what you want
when feature selection is part of the user's iteration loop.

## Mixing in your own

A "feature" is just a `Callable[[np.ndarray], np.ndarray]` matching the
shape contract. Drop yours in next to the contrib ones:

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

## When to replace, not extend

These five features assume **time-domain windowed sEMG**. If your
pipeline already extracts richer representations - spectral features,
learned embeddings from a frozen network, MyoVerse decomposition output
 - `contrib.features` is the wrong toolbox.

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
  for windowing, normalisation, and spectral features.
* [`myogestic.recipes.features`](../api/core.md) - full module reference.
* [`myogestic.widgets.FeatureSelector`](../api/widgets.md) - the
  GUI-toggleable feature dispatcher.
