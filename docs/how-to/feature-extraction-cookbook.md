# Feature-extraction cookbook

The framework deliberately ships nothing inside [`@pipeline.extract`][myogestic.ml.Pipeline.extract] - DSP and feature engineering belong to user code. Bringing your own scipy / MyoVerse / numpy is the design intent.

That said, almost every EMG project starts with the same five or six features. This page is a copy-paste cookbook so you can drop them in and iterate.

Each snippet wraps in `@pipeline.extract`. Drop into your script, swap one for another, and re-train.

## 1. RMS + MAV (the shipped baseline)

`examples/synthetic/emg_classification.py` registers a menu of reference features via [`FeatureSelector`][myogestic.widgets.FeatureSelector] and lets the user toggle them live in the GUI:

```python
--8<-- "examples/synthetic/emg_classification.py:features"
```

`extract` just calls it — the active features are stacked into one flat vector, identical for training and live predict:

```python
--8<-- "examples/synthetic/emg_classification.py:extract"
```

The reference `rms`/`mav`/`wl`/`var`/`zc` live in [`myogestic.recipes.features`][myogestic.recipes.features] — plain numpy, channels-first `(n_channels, n_samples)` in, one scalar per channel out. Mix your own callables into the same dict; feature engineering is user code.

### …or bring your own (MyoVerse)

Prefer a library's windowed transforms? Swap the dict for them — `@pipeline.extract` can return any feature vector:

```python
import numpy as np
import torch
from myoverse.transforms import RMS, MAV

rms_transform = RMS(window_size=32)
mav_transform = MAV(window_size=32)


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_channels, n_samples)
    t = torch.from_numpy(emg).float()
    rms = rms_transform(t).numpy().flatten()
    mav = mav_transform(t).numpy().flatten()
    return np.concatenate([rms, mav])
```

`window_size=32` is a per-channel MyoVerse parameter (samples per sub-window inside the EMG window). Tune to match your fs. Install: `uv sync --extra examples`.

## 2. scipy bandpass + envelope

Classic EMG pipeline: notch out mains hum, bandpass to the EMG band, rectify, low-pass envelope.

```python
import numpy as np
from scipy.signal import butter, sosfilt

FS = 2000.0
sos_bandpass = butter(4, [20, 450], "bandpass", fs=FS, output="sos")
sos_lowpass = butter(4, 6, "lowpass", fs=FS, output="sos")


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_channels, n_samples)
    bp = sosfilt(sos_bandpass, emg, axis=1)  # bandpass
    env = sosfilt(sos_lowpass, np.abs(bp), axis=1)  # rectify + lowpass
    # Reduce to one number per channel (mean envelope amplitude):
    return env[:, -32:].mean(axis=1)
```

The 20-450 Hz band is the standard EMG range; 6 Hz is the standard envelope cutoff for slow gesture control. Add a `iirnotch` at 50/60 Hz if you have mains hum.

`scipy.signal` is already a transitive dep through other libraries; if not, `uv pip install scipy`.

## 3. Spectral features (numpy.fft)

For frequency-content classification - mean / median frequency and the energy in specific bands.

```python
import numpy as np

FS = 2000.0


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_channels, n_samples)
    n = emg.shape[1]
    spec = np.abs(np.fft.rfft(emg, axis=1))  # (n_channels, n_bins)
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    p = spec**2  # power
    total = p.sum(axis=1) + 1e-12
    mean_freq = (p * freqs).sum(axis=1) / total
    cumulative = np.cumsum(p, axis=1)
    median_freq = freqs[np.argmin(np.abs(cumulative - 0.5 * total[:, None]), axis=1)]
    band_20_60 = p[:, (freqs >= 20) & (freqs < 60)].sum(axis=1)
    band_60_150 = p[:, (freqs >= 60) & (freqs < 150)].sum(axis=1)
    return np.concatenate([mean_freq, median_freq, band_20_60, band_60_150])
```

Median frequency is a fatigue signature; mean frequency tracks motor-unit recruitment.

## 4. Sliding RMS (stride tricks)

When you want every per-window RMS estimate, not just one. Useful for time-frequency analysis or feeding a sequence model.

```python
import numpy as np

WIN = 64  # samples per sub-window
HOP = 16  # samples per hop


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_channels, n_samples)
    n_ch, n_samples = emg.shape
    n_win = (n_samples - WIN) // HOP + 1
    if n_win < 1:
        return np.zeros(n_ch, dtype=np.float32)
    # Stride tricks: build a (n_ch, n_win, WIN) view without copying.
    s_ch, s_t = emg.strides
    sliding = np.lib.stride_tricks.as_strided(
        emg,
        shape=(n_ch, n_win, WIN),
        strides=(s_ch, HOP * s_t, s_t),
        writeable=False,
    )
    return np.sqrt(np.mean(sliding**2, axis=2)).flatten()
```

Output shape is `n_ch * n_win`. With `WIN=64, HOP=16` and a 0.2 s @ 2 kHz window (400 samples), that's `n_ch * 22` features.

## 5. Simple onset detection

A cheap "is the user trying" gate - use it to bypass prediction during quiet periods.

```python
import numpy as np

THRESHOLD_K = 4.0  # std multiplier above baseline


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_channels, n_samples)
    half = emg.shape[1] // 2
    baseline_std = np.std(emg[:, :half], axis=1)  # first half = "rest" reference
    live_rms = np.sqrt(np.mean(emg[:, half:] ** 2, axis=1))
    threshold = baseline_std * THRESHOLD_K
    n_active = int((live_rms > threshold).sum())
    return np.array([n_active], dtype=np.float32)
```

Returns a single int per tick (number of channels above onset threshold). Combine with another feature set or use as a gate.

## 6. Multi-stream concatenation

When you have EMG + IMU and want to fuse them.

```python
import numpy as np


@pipeline.extract
def extract(windows):
    emg = windows["emg"]  # (n_emg_ch, n_samples_emg)
    imu = windows["imu"]  # (6, n_samples_imu)
    emg_rms = np.sqrt(np.mean(emg**2, axis=1))
    imu_mean = imu.mean(axis=1)
    return np.concatenate([emg_rms, imu_mean])
```

The `windows` dict is keyed by stream name. Add a second `app.streams(Stream("imu", source=...))` and `windows["imu"]` appears.

## Choosing a feature set

| Goal | Start with |
|------|-----------|
| Quick prototype, classification | RMS + MAV (#1) |
| Real prosthetic / robot control | Bandpass + envelope (#2) |
| Fatigue / motor-unit analysis | Spectral (#3) |
| Sequence model (LSTM, Transformer) | Sliding RMS (#4) |
| Cheap on/off gate before prediction | Onset detection (#5) |
| Sensor fusion | Multi-stream (#6) |

`extract()` is called twice per project: once from inside `train()` over recorded windows, and once per tick on the predict thread. Whichever feature set you pick, **the return shape must be stable** - same dimensionality every call - or your model will see a shape mismatch live.

See also: [Add a custom model](add-a-model.md), [Pipeline concept page](../concepts/pipeline.md), [EMG classification tutorial](../tutorials/emg-classification.md).
