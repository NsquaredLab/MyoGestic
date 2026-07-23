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

from myogestic.widgets.signals.transforms import NotchFilter, apply_mains_notch

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


# --- NotchFilter: the incremental (stateful) counterpart --------------------------------


def test_incremental_notchfilter_matches_apply_mains_notch():
    # The equivalence the viewer relies on: NotchFilter.step fed in ARBITRARY sliding chunks
    # (including a single sample) reproduces apply_mains_notch over the whole signal, so
    # filtering only the newly-arrived samples per frame never diverges from a full refilter.
    rng = np.random.default_rng(0)
    n, n_ch = 12000, 4
    hum = _tone(50.0, n, amp=4.0)[:, None]
    x = (rng.standard_normal((n, n_ch)) + hum).astype(np.float64)  # per-channel noise + shared hum
    ref = apply_mains_notch(x, FS, 50)

    nf = NotchFilter(FS, 50)
    sizes, out, i, s = [2000, 137, 1, 500, 61, 3000], [], 0, 0
    while i < n:
        k = sizes[s % len(sizes)]
        out.append(nf.step(x[i : i + k]))
        i, s = i + k, s + 1
    out = np.concatenate(out)
    assert out.shape == ref.shape
    assert np.max(np.abs(out - ref)) < 1e-9  # bit-identical within one SciPy build


def test_nan_chunk_does_not_poison_later_output():
    # A non-finite sample would freeze into the IIR state and corrupt every later frame; the
    # filter resets after a bad chunk, so the next clean chunk re-seeds exactly like a cold
    # filter (finite output, hum still scrubbed) instead of staying poisoned.
    clean = (_tone(50.0, 6000, amp=4.0) + _tone(23.0, 6000, amp=2.0)).astype(np.float64)
    nf = NotchFilter(FS, 50)
    nf.step(clean[:2000])  # seed on clean data
    bad = clean[2000:2500].copy()
    bad[100] = np.nan
    nf.step(bad)  # NaN poisons, then step() resets the state
    out = nf.step(clean[2500:])
    assert np.all(np.isfinite(out))
    # After the reset, step() re-seeds on clean[2500:][0] — identical to a fresh cold filter.
    fresh = apply_mains_notch(clean[2500:], FS, 50)
    assert np.max(np.abs(out - fresh)) < 1e-9


def test_incremental_step_is_far_cheaper_than_a_full_refilter(capsys):
    # Motivation for the whole change: at 10240 Hz x 16 ch the notch re-filters a ~56 k-sample
    # window every frame today; the incremental step touches only the ~200 new samples. Print
    # the per-frame cost (M4-style) and assert the step is at least an order of magnitude cheaper.
    import time

    fs, n_ch = 10240.0, 16
    win = int(5.5 * fs)  # ~5.5 s visible + warm-up window (56320 samples)
    hop = int(fs / 50)  # new samples per frame at ~50 FPS
    rng = np.random.default_rng(0)
    window = rng.standard_normal((win, n_ch)).astype(np.float64)
    delta = window[-hop:]

    t0 = time.perf_counter()
    apply_mains_notch(window, fs, 50)  # today: whole window, every frame
    cold_ms = (time.perf_counter() - t0) * 1e3

    nf = NotchFilter(fs, 50)
    nf.step(window)  # prime the state once (the cold path)
    t0 = time.perf_counter()
    for _ in range(50):
        nf.step(delta)  # hot path: only the new samples
    hot_ms = (time.perf_counter() - t0) / 50 * 1e3

    with capsys.disabled():
        print(
            f"\n[notch@10240Hz x 16ch] full-window={cold_ms:.2f} ms/frame  "
            f"incremental={hot_ms:.3f} ms/frame  ({cold_ms / hot_ms:.0f}x less notch compute)"
        )
    assert hot_ms < cold_ms / 20  # the incremental step is >=20x cheaper than a refilter


# --- NotchCache: the viewer-side incremental cache (seq bookkeeping) ---------------------


def test_notchcache_matches_fixed_history_reference_while_scrolling():
    # The guarantee the viewer relies on: as the window scrolls (growing buffer, many frames),
    # the cache's per-frame region equals a SINGLE causal notch seeded once at the first frame's
    # warm-up start and run forward — i.e. persistent state never revises already-drawn samples.
    from myogestic.widgets.signals._state import _NOTCH_WARMUP_S, NotchCache

    fs, freq = FS, 50
    n = 12000
    ts = np.arange(n, dtype=np.float64) / fs
    hum = _tone(50.0, n, amp=4.0)
    sig = np.stack([hum + _tone(23.0, n, amp=2.0), hum + _tone(31.0, n, amp=1.5)], axis=1)

    win = 1000  # visible-window samples
    t0 = 3000  # first frame: buffer holds sig[:t0]
    warm0 = int(np.searchsorted(ts[:t0], ts[t0 - win] - _NOTCH_WARMUP_S, side="left"))

    cache = NotchCache()
    frames = 0
    for t in range(t0, n + 1, 137):  # ~137 new samples per frame
        region_idx = t - win
        got = cache.notched(1, 1, t, sig[:t], ts[:t], region_idx, ts[region_idx], fs, freq, [0, 1])
        # Fixed-history reference: one notch seeded at warm0 (the first cold start), run to t.
        expected = apply_mains_notch(sig[warm0:t], fs, freq)[region_idx - warm0 :]
        assert got.shape == expected.shape == (win, 2)
        assert np.max(np.abs(got - expected)) < 1e-9  # persistent state == fixed-history notch
        frames += 1
    assert frames > 50  # actually exercised the hot path across many frames


def test_notchcache_reprocesses_new_columns_on_a_channel_selection_change():
    # Switching which channels are drawn must cold-rebuild: the cache must return the NEW
    # column's notch, not the previously-cached one (a stale tail would be a silent wrong trace).
    from myogestic.widgets.signals._state import _NOTCH_WARMUP_S, NotchCache

    fs, freq, n = FS, 50, 5000
    ts = np.arange(n, dtype=np.float64) / fs
    hum = _tone(50.0, n, amp=4.0)
    sig = np.stack([hum + _tone(23.0, n, amp=2.0), hum + _tone(31.0, n, amp=1.5)], axis=1)
    region_idx = n - 1000
    warm_idx = int(np.searchsorted(ts, ts[region_idx] - _NOTCH_WARMUP_S, side="left"))

    cache = NotchCache()
    cache.notched(1, 1, n, sig, ts, region_idx, ts[region_idx], fs, freq, [0])  # draw ch0
    got = cache.notched(1, 1, n, sig, ts, region_idx, ts[region_idx], fs, freq, [1])  # switch to ch1
    expected = apply_mains_notch(sig[warm_idx:, [1]], fs, freq)[region_idx - warm_idx :]
    assert np.max(np.abs(got - expected)) < 1e-9
