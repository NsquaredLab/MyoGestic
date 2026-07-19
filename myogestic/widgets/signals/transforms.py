"""Visual-only signal transforms used by the signal viewer and previews."""

from __future__ import annotations

import numpy as np


def apply_display_filter(data: np.ndarray, mode: str, fs: float) -> np.ndarray:
    """Apply visual-only transforms. Recording/model input is unaffected."""
    if mode == "rectify":
        return np.abs(data)
    if mode == "dc_removal":
        return data - data.mean(axis=0, keepdims=True)
    if mode != "rms_env" or len(data) < 4:
        return data

    k = max(4, int(0.01 * fs))
    if k >= len(data):
        return data
    sq = (data.astype(np.float32)) ** 2
    csum = np.cumsum(sq, axis=0)
    denom = np.arange(1, k + 1, dtype=np.float32)[:, None]
    rms_warm = np.sqrt(np.maximum(csum[:k] / denom, 0.0))
    rms_tail = np.sqrt(np.maximum((csum[k:] - csum[:-k]) / k, 0.0))
    return np.concatenate([rms_warm, rms_tail])


def compute_rms_trace(
    ts: np.ndarray,
    data: np.ndarray,
    fs: float,
    window_ms: float,
    hop_ms: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Sparse trailing-RMS envelope on an absolute-time hop grid.

    Returns ``(rms_ts, rms_data)``: one RMS value per hop endpoint (``rms_ts``
    shape ``(m,)``, ``rms_data`` shape ``(m, n_channels)``), each computed over
    the ``window_ms`` of samples *preceding and including* that endpoint
    (trailing / causal — the value is timestamped at the window's END, so it
    never implies future data at the live edge).

    Design notes that make it correct for a scrolling live view:

    - **Absolute hop grid.** Endpoints sit at integer multiples of the hop
      period, keyed off the absolute timestamps ``ts``, *not* off this slice's
      own start. A given sample therefore lands in the same hop window no
      matter where the visible window currently begins, so the envelope does
      not jitter as it scrolls (the same absolute-grid trick the MinMax
      decimator uses). The caller must pass a slice that includes one full
      ``window_ms`` of **pre-roll** before the visible left edge, otherwise
      the leftmost visible endpoints are dropped for lack of history rather
      than drawn as a scroll-dependent partial-window transient.
    - **Only complete windows are emitted** (``start >= ts[0]``), so a short
      buffer yields fewer points (or none) rather than a partial-window RMS
      masquerading as raw signal.
    - **NaN policy:** a window containing any non-finite sample yields NaN for
      that channel *for that window only* — the running sums zero out the bad
      samples (counted separately), so the trace recovers on the next clean
      window instead of one dropout poisoning everything after it.
    - **float64 accumulation** for the sum of squares: a float32 cumulative
      sum drifts badly on a DC-offset signal over a long window.

    Windowing is timestamp-based (``searchsorted``), so it tolerates the
    non-uniform per-sample timestamps real sources produce under jitter.
    """
    data = np.asarray(data)
    ts = np.asarray(ts)
    if len(ts) == 0:
        # Guard before the reshape below: `reshape(0, -1)` cannot infer the
        # column count from a size-0 array and would raise.
        return np.empty(0, dtype=np.float64), np.empty((0, 0), dtype=np.float64)
    if data.ndim != 2:
        data = data.reshape(len(ts), -1)
    n, n_ch = data.shape
    empty = (np.empty(0, dtype=np.float64), np.empty((0, n_ch), dtype=np.float64))
    if n == 0 or n_ch == 0 or not np.isfinite(fs) or fs <= 0:
        return empty
    window_s = max(float(window_ms), 0.0) / 1000.0
    if window_s <= 0:
        return empty
    hop_s = max(float(hop_ms), 0.0) / 1000.0
    if hop_s <= 0:
        hop_s = 1.0 / fs  # a sub-sample hop degenerates to per-sample RMS

    t0, t1 = float(ts[0]), float(ts[-1])
    # Endpoints on the absolute grid that both have a full window of history
    # (``end - window_s >= t0``) and fall within the data (``end <= t1``).
    j0 = int(np.ceil((t0 + window_s) / hop_s))
    j1 = int(np.floor(t1 / hop_s))
    if j1 < j0:
        return empty
    ends = np.arange(j0, j1 + 1, dtype=np.float64) * hop_s
    starts = ends - window_s

    # Only pay the NaN bookkeeping when the slice actually has a non-finite
    # sample (the common live case is clean, so this skips a full pass and an
    # int64 cumulative sum). Prefix sums are built into a `(n+1, n_ch)` buffer
    # with a leading zero row via `out=`, avoiding a concatenate allocation.
    finite = np.isfinite(data)
    has_bad = not finite.all()
    sq = np.where(finite, data, 0.0).astype(np.float64) if has_bad else data.astype(np.float64)
    sq *= sq
    csum = np.empty((n + 1, n_ch), dtype=np.float64)
    csum[0] = 0.0
    np.cumsum(sq, axis=0, out=csum[1:])

    # Half-open window (start, end]: ``right`` on both bounds counts ts <= bound.
    hi = np.searchsorted(ts, ends, side="right")
    lo = np.searchsorted(ts, starts, side="right")
    counts = (hi - lo).astype(np.float64)
    sums = csum[hi] - csum[lo]
    with np.errstate(invalid="ignore", divide="ignore"):
        rms = np.sqrt(sums / counts[:, None])

    if has_bad:
        nan_csum = np.empty((n + 1, n_ch), dtype=np.int64)
        nan_csum[0] = 0
        np.cumsum(~finite, axis=0, out=nan_csum[1:])
        rms[(nan_csum[hi] - nan_csum[lo]) > 0] = np.nan

    valid = counts > 0
    if not valid.all():
        ends, rms = ends[valid], rms[valid]
    return ends, rms
