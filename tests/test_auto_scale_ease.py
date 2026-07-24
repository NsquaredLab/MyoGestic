"""Tests for the eased auto y-scale (`_plot.update_auto_scale`).

The signal viewer's auto mode used to hand the y-axis to ImPlot's per-frame `auto_fit`, so a
variable signal zoomed in/out constantly. Now `update_auto_scale` eases `y_min/y_max` toward the
drawn data's padded range over ~5 s. These pin the pure state update: it eases gradually and
settles, snaps on a context change / first frame / huge dt, and is a no-op in manual / per-channel
modes — all without a live plot.
"""

from __future__ import annotations

import numpy as np

from myogestic.widgets.signals._plot import (
    _SCALE_EASE_S,
    robust_channel_ranges,
    update_auto_scale,
    update_per_channel_ranges,
)
from myogestic.widgets.signals._state import ViewerState


def _data(lo, hi, n=200, n_ch=2):
    """Trace whose every column spans exactly ``[lo, hi]`` → target range ``[lo-pad, hi+pad]``."""
    col = np.linspace(lo, hi, n, dtype=np.float32)
    return np.stack([col] * n_ch, axis=1)


def _target(lo, hi):
    span = hi - lo
    pad = span * 0.1 if span > 0 else 1.0
    return lo - pad, hi + pad


def _data_cols(spans, n=200):
    """Trace with a given ``(lo, hi)`` per column → per-channel ranges keyed by column index."""
    cols = [np.linspace(lo, hi, n, dtype=np.float32) for lo, hi in spans]
    return np.stack(cols, axis=1)


def _v(**kw):
    """ViewerState with transient rejection OFF, so the ease-logic tests use exact min/max."""
    v = ViewerState(**kw)
    v.transient_ms = 0.0
    return v


def test_first_frame_snaps():
    v = _v()  # scale_mode defaults to "auto"
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)
    lo0, hi0 = _target(-0.1, 0.1)
    assert np.isclose(v.y_min, lo0) and np.isclose(v.y_max, hi0)  # first frame snaps to the range


def test_expands_instantly_so_a_new_peak_is_never_clipped():
    v = _v()
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)  # snap small
    lo, hi = _target(-2.0, 2.0)  # a contraction appears
    update_auto_scale(v, _data(-2.0, 2.0), [0, 1], "emg", now=100.016)  # ONE frame
    assert v.y_max >= hi - 1e-9 and v.y_min <= lo + 1e-9  # bound snapped OUT to contain it, no clip


def test_contracts_slowly_then_settles():
    v = _v()
    update_auto_scale(v, _data(-2.0, 2.0), [0, 1], "emg", now=100.0)  # snap large
    big = v.y_max
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.016)  # signal quietens, 1 frame
    assert v.y_max > 0.9 * big  # barely moved down after one frame — shrink-slow, no jitter

    t = 100.016
    for _ in range(int(round(_SCALE_EASE_S / 0.016)) + 5):  # ~5 s
        t += 0.016
        update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=t)
    assert abs(v.y_max - _target(-0.1, 0.1)[1]) < 0.15  # settled near the small target


def test_context_change_snaps_immediately():
    v = _v()
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=105.0)  # settled small

    # A different channel set is a new context → snap to the new (large) range, no ease.
    update_auto_scale(v, _data(-3.0, 3.0), [0, 2], "emg", now=105.016)
    lo, hi = _target(-3.0, 3.0)
    assert np.isclose(v.y_min, lo) and np.isclose(v.y_max, hi)


def test_manual_and_per_channel_leave_limits_untouched():
    v = _v()
    v.y_min, v.y_max = -1.0, 1.0
    v.scale_mode = "manual"
    update_auto_scale(v, _data(-5.0, 5.0), [0, 1], "emg", now=100.0)
    assert (v.y_min, v.y_max) == (-1.0, 1.0)  # manual: held

    v.scale_mode = "auto"
    v.per_channel_scale = True
    update_auto_scale(v, _data(-5.0, 5.0), [0, 1], "emg", now=100.0)
    assert (v.y_min, v.y_max) == (-1.0, 1.0)  # per-channel: unit lanes, not this axis


def test_expansion_ignores_dt_but_contraction_backward_clock_is_a_noop():
    v = _v()
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)  # snap small (first frame)
    # Expansion is instant regardless of dt (snap out) — even a tiny/huge dt fully contains it.
    update_auto_scale(v, _data(-2.0, 2.0), [0, 1], "emg", now=100.001)
    assert abs(v.y_max - _target(-2.0, 2.0)[1]) < 1e-9  # ±2.4, snapped

    # A CONTRACTING target with a backwards clock must not move (contraction dt clamps to 0).
    before = (v.y_min, v.y_max)
    update_auto_scale(v, _data(-0.5, 0.5), [0, 1], "emg", now=99.0)  # smaller + clock backwards
    assert (v.y_min, v.y_max) == before


def test_gain_scales_the_target():
    # plot_channel draws data*gain, so the eased range must be gain-scaled too, else it clips.
    v = _v()
    v.gain = 10.0
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)  # first frame snaps
    lo, hi = _target(-1.0, 1.0)  # gained range ±1.0 → padded ±1.2
    assert np.isclose(v.y_max, hi) and np.isclose(v.y_min, lo)


def test_reentering_auto_after_manual_snaps():
    v = _v()
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=100.0)  # auto snap small
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=105.0)  # settled

    v.scale_mode = "manual"
    update_auto_scale(v, _data(-2.0, 2.0), [0, 1], "emg", now=105.1)  # manual: no-op, reset ease
    assert v.scale_ease_t == 0.0

    v.scale_mode = "auto"
    update_auto_scale(v, _data(-2.0, 2.0), [0, 1], "emg", now=110.0)  # re-enter auto → snap
    lo, hi = _target(-2.0, 2.0)
    assert np.isclose(v.y_max, hi) and np.isclose(v.y_min, lo)  # snapped, not eased from stale


def test_rms_window_change_snaps():
    # Changing the RMS window rebuilds a materially different envelope → snap, don't slow-contract
    # across it. rms_env ranges are one-sided/robust, so assert the SNAP happened, not exact values.
    v = _v()
    v.display_filter = "rms_env"
    update_auto_scale(v, _data(-3.0, 3.0), [0, 1], "emg", now=100.0)  # snap large
    update_auto_scale(v, _data(-3.0, 3.0), [0, 1], "emg", now=105.0)  # settled large
    assert v.y_max > 2.0
    v.rms_window_ms = 250.0
    update_auto_scale(v, _data(-0.1, 0.1), [0, 1], "emg", now=105.016)  # much smaller data
    assert v.y_max < 0.5  # snapped down in one frame (a slow contract would still be ~3)


# --- per-channel mode: each lane's normalisation range is eased the same way ----------------


def _pc(per_channel=True):
    v = _v()
    v.per_channel_scale = per_channel
    return v


def test_per_channel_first_frame_snaps_to_raw_ranges():
    v = _pc()
    r = update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-0.2, 0.5)]), [0, 1], "emg", now=100.0)
    assert np.allclose(r[0], (-1.0, 1.0)) and np.allclose(r[1], (-0.2, 0.5))  # raw min/max, snapped


def test_per_channel_expands_instantly_so_a_louder_channel_never_overflows():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-0.1, 0.1)]), [0], "emg", now=100.0)  # snap small
    r = update_per_channel_ranges(v, _data_cols([(-2.0, 2.0)]), [0], "emg", now=100.016)  # ONE frame
    assert r[0][1] >= 2.0 - 1e-9 and r[0][0] <= -2.0 + 1e-9  # range snapped OUT in one frame


def test_per_channel_contracts_slowly_then_settles():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-2.0, 2.0)]), [0], "emg", now=100.0)  # snap large
    r = update_per_channel_ranges(v, _data_cols([(-0.1, 0.1)]), [0], "emg", now=100.016)
    assert r[0][1] > 0.9 * 2.0  # barely contracted after one frame (shrink-slow, no jitter)
    t = 100.016
    for _ in range(int(round(_SCALE_EASE_S / 0.016)) + 5):  # ~5 s
        t += 0.016
        r = update_per_channel_ranges(v, _data_cols([(-0.1, 0.1)]), [0], "emg", now=t)
    assert abs(r[0][1] - 0.1) < 0.1 and abs(r[0][0] + 0.1) < 0.1  # settled near the small target


def test_per_channel_channel_set_change_snaps_the_new_channel():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=100.0)
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=105.0)  # settled
    r = update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-3.0, 3.0)]), [0, 1], "emg", now=105.016)
    assert np.allclose(r[1], (-3.0, 3.0))  # newly-enabled ch1 snaps to its raw range


def test_per_channel_display_filter_change_snaps():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-0.1, 0.1)]), [0], "emg", now=100.0)
    update_per_channel_ranges(v, _data_cols([(-0.1, 0.1)]), [0], "emg", now=105.0)  # settled small
    v.display_filter = "dc_removal"  # a scale-changing filter → snap, don't ease across it
    r = update_per_channel_ranges(v, _data_cols([(-3.0, 3.0)]), [0], "emg", now=105.016)
    assert np.allclose(r[0], (-3.0, 3.0))


def test_per_channel_drops_disabled_channels():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-2.0, 2.0)]), [0, 1], "emg", now=100.0)
    assert set(v.pc_ranges) == {0, 1}
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=100.016)  # ch1 disabled
    assert set(v.pc_ranges) == {0}  # dropped, no stale accumulation


# --- per-channel MANUAL: freeze the lane ranges (Codex model: basis × adaptation) -----------


def test_per_channel_manual_holds_frozen_ranges():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-2.0, 2.0)]), [0, 1], "emg", now=100.0)
    frozen = dict(v.pc_ranges)
    v.scale_mode = "manual"
    # Even as the signal changes wildly, Manual holds the captured ranges (no re-fit).
    r = update_per_channel_ranges(v, _data_cols([(-9.0, 9.0), (-0.01, 0.01)]), [0, 1], "emg", now=101.0)
    assert r == frozen and v.pc_ranges == frozen


def test_per_channel_manual_initialises_only_a_newly_enabled_channel():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=100.0)  # ch0 (auto)
    v.scale_mode = "manual"
    ch0_frozen = v.pc_ranges[0]
    # Enable ch1 while Manual: it initialises from its own current data; ch0 stays frozen.
    r = update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-3.0, 3.0)]), [0, 1], "emg", now=101.0)
    assert r[0] == ch0_frozen
    assert np.allclose(r[1], (-3.0, 3.0))


def test_per_channel_manual_resets_ease_clock_for_auto_re_entry():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=100.0)
    v.scale_mode = "manual"
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=101.0)
    assert v.pc_ease_t == 0.0  # so switching back to Auto snaps rather than easing from stale


def test_per_channel_manual_drops_disabled_channels():
    v = _pc()
    update_per_channel_ranges(v, _data_cols([(-1.0, 1.0), (-2.0, 2.0)]), [0, 1], "emg", now=100.0)
    v.scale_mode = "manual"
    r = update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=101.0)  # ch1 off
    assert set(r) == {0} and set(v.pc_ranges) == {0}


def test_per_channel_ranges_are_stored_gained():
    # Ranges are stored gained so Manual gain magnifies against the frozen reference.
    v = _pc()
    v.gain = 5.0
    r = update_per_channel_ranges(v, _data_cols([(-1.0, 1.0)]), [0], "emg", now=100.0)  # auto snap
    assert np.allclose(r[0], (-5.0, 5.0))  # (-1,1) × gain 5


# --- artifact-robust range (duration-based rejection) ---------------------------------------


def _artifact_window(n=50000, contraction=1.0, artifact=10.0, fs=10240.0):
    """Window: noise floor + a sustained ~200 ms contraction + a brief ~10 ms artifact spike."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.05, n)
    x[10000:12000] += rng.normal(0, contraction, 2000)  # 4% of samples: the real contraction
    x[30000:30100] += rng.normal(0, artifact, 100)  # 0.2%: a movement-artifact spike
    return x[:, None].astype(np.float32), n / fs


def test_robust_rejects_sparse_artifact_keeps_contraction():
    data, window = _artifact_window()
    raw = robust_channel_ranges(data, [0], 0.0, window, "none", 100.0, 20.0)[0]  # min/max
    rob = robust_channel_ranges(data, [0], 20.0, window, "none", 100.0, 20.0)[0]  # reject <20 ms
    assert raw[1] > 15  # plain min/max is artifact-driven (~+30)
    assert 2.0 < rob[1] < 6.0 and -6.0 < rob[0] < -2.0  # robust keeps the ±3 contraction, drops it


def test_robust_transient_zero_is_plain_minmax():
    data, window = _artifact_window()
    r = robust_channel_ranges(data, [0], 0.0, window, "none", 100.0, 20.0)[0]
    assert r[1] > 15 and r[0] < -15  # no rejection → equals raw min/max


def test_robust_rms_env_is_one_sided():
    env = np.abs(np.linspace(0.0, 2.0, 300))[:, None].astype(np.float32)
    r = robust_channel_ranges(env, [0], 20.0, 5.0, "rms_env", 100.0, 20.0)[0]
    assert r[0] == 0.0 and r[1] > 0.0  # lower bound pinned to zero, only the top trimmed


def test_robust_auto_scale_ignores_an_artifact_by_default():
    data, window = _artifact_window()
    v = ViewerState()  # default transient_ms = 20
    v.window = window
    update_auto_scale(v, data, [0], "emg", now=100.0)  # first frame snaps to the ROBUST range
    assert v.y_max < 6.0  # not blown out to the ±30 artifact
