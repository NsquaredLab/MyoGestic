"""Tests for the visual-only mains-hum notch `apply_mains_notch`.

The signal viewer can strip 50/60 Hz line interference (and its harmonics)
from the *display* before the View transform. It is a **causal** IIR notch:
the scope scrolls, so a sample is re-filtered on many frames, and a causal
filter guarantees its value never changes as newer samples arrive — the
already-drawn trace stays put (the old FFT notch failed this and jittered).

These pin: it attenuates the targeted hum in steady state, leaves off-target
signal's magnitude intact, no-ops on bad input, and — the regression guard —
does not revise past samples as the window slides.
"""

from __future__ import annotations

import numpy as np

from myogestic.widgets.signals.transforms import apply_mains_notch

FS = 2000.0


def _rms(x):
    return float(np.sqrt(np.mean(np.square(x))))


def _tone(freq, n, amp=1.0):
    t = np.arange(n, dtype=np.float64) / FS
    return amp * np.sin(2.0 * np.pi * freq * t)


def _settled(x):
    """Drop the first half as filter warm-up; measure the steady-state tail."""
    return x[len(x) // 2 :]


def test_attenuates_fundamental():
    hum = _tone(50.0, 6000, amp=5.0)
    out = apply_mains_notch(hum, FS, 50)
    # 50 Hz sine is essentially gone once the notch has settled.
    assert _rms(_settled(out)) < 0.05 * _rms(hum)


def test_attenuates_harmonics():
    hum = _tone(50.0, 6000) + _tone(150.0, 6000) + _tone(250.0, 6000)
    out = apply_mains_notch(hum, FS, 50)
    assert _rms(_settled(out)) < 0.1 * _rms(_settled(hum))


def test_preserves_off_target_magnitude():
    # A tone far from any notched band keeps its amplitude (a causal notch
    # shifts phase, so compare RMS magnitude, not sample-wise difference).
    sig = _tone(23.0, 6000)
    out = apply_mains_notch(sig, FS, 50)
    assert abs(_rms(_settled(out)) - _rms(_settled(sig))) < 0.03 * _rms(sig)


def test_removes_only_the_hum_from_a_mix():
    clean = _tone(23.0, 6000, amp=2.0)
    out = apply_mains_notch(clean + _tone(50.0, 6000, amp=5.0), FS, 50)
    # The off-target 23 Hz content survives at full amplitude; the hum does not.
    assert abs(_rms(_settled(out)) - _rms(_settled(clean))) < 0.05 * _rms(clean)


def test_multichannel_shape_and_independence():
    n = 6000
    ch0 = _tone(50.0, n, amp=4.0)
    ch1 = _tone(23.0, n, amp=2.0)
    data = np.stack([ch0, ch1], axis=1)
    out = apply_mains_notch(data, FS, 50)
    assert out.shape == data.shape
    assert _rms(_settled(out[:, 0])) < 0.05 * _rms(ch0)  # hum channel scrubbed
    assert abs(_rms(_settled(out[:, 1])) - _rms(_settled(ch1))) < 0.03 * _rms(ch1)


def test_no_historical_revision_as_window_slides():
    # THE regression guard for the jitter bug: a causal notch must produce the
    # same settled value for a given sample regardless of where the analysis
    # window starts. Filtering from far back and filtering from a warm-up
    # before the region must agree over that region.
    x = _tone(23.0, 9000) + _tone(50.0, 9000, amp=4.0)
    full = apply_mains_notch(x, FS, 50)
    warm, a, span = 2200, 5000, 2000  # ~1.1 s warm-up >= notch settle time
    sub = apply_mains_notch(x[a - warm :], FS, 50)
    region_from_sub = sub[warm : warm + span]
    region_from_full = full[a : a + span]
    assert np.max(np.abs(region_from_sub - region_from_full)) < 1e-3


def test_noop_guards():
    sig = _tone(50.0, 512)
    # freq=0 (off), invalid fs, and too-short windows return the input as-is.
    assert apply_mains_notch(sig, FS, 0) is sig
    assert apply_mains_notch(sig, 0.0, 50) is sig
    assert apply_mains_notch(sig, float("nan"), 50) is sig
    short = sig[:4]
    assert apply_mains_notch(short, FS, 50) is short


def test_60hz_leaves_50hz_alone():
    sig = _tone(50.0, 6000)
    out = apply_mains_notch(sig, FS, 60)  # notching 60 Hz shouldn't touch 50 Hz
    assert abs(_rms(_settled(out)) - _rms(_settled(sig))) < 0.05 * _rms(sig)
