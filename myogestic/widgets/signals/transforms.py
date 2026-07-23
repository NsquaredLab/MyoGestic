"""Visual-only signal transforms used by the signal viewer and previews."""

from __future__ import annotations

import numpy as np
from scipy.signal import iirnotch, lfilter, lfilter_zi

#: -3 dB width of each notch, in Hz. `Q = f0 / _NOTCH_BW_HZ`.
_NOTCH_BW_HZ = 3.0

#: Fundamental + this many harmonics are notched (each is one biquad, so this
#: bounds per-frame cost). The fundamental and low harmonics carry essentially
#: all the visible mains energy; higher ones are lost in the trace anyway.
_NOTCH_MAX_LINES = 5


def apply_mains_notch(data: np.ndarray, fs: float, freq: int) -> np.ndarray:
    """Remove mains-line interference at ``freq`` Hz (and its harmonics).

    A visual-only notch for the signal viewer, meant to run *before* the display
    filter. Implemented as a **causal** IIR notch — one 2nd-order
    [`scipy.signal.iirnotch`][] biquad per harmonic below Nyquist, cascaded
    and applied with [`scipy.signal.lfilter`][] along axis 0.

    Causal is the whole point: the scope scrolls, so a given sample is
    re-filtered on many frames as the visible window slides over it. A causal
    filter's output at sample ``i`` depends only on samples ``<= i``, so that
    output never changes as newer samples arrive — the already-drawn trace
    stays put. (A zero-phase/FFT notch couples the whole window and rewrites
    past samples every frame, which reads as jitter.) The caller is responsible
    for feeding a warm-up slice *before* the region it displays and dropping it,
    so the shown region is the filter's settled steady state.

    Each biquad is initialised to the steady state for the first sample
    ([`scipy.signal.lfilter_zi`][]) to suppress the DC start-up step. Returns
    ``data`` unchanged when ``freq`` is 0/None, ``fs`` is invalid, or the window
    is too short to filter.

    Parameters
    ----------
    data
        Samples ``(n,)`` or ``(n, n_channels)``.
    fs
        Sample rate in Hz.
    freq
        Mains frequency to reject (``50`` or ``60``); ``0`` disables the notch.
    """
    n = len(data)
    if not freq or not np.isfinite(fs) or fs <= 0.0 or n < 8:
        return data
    x = np.ascontiguousarray(data, dtype=np.float64)
    was_1d = x.ndim == 1
    y = x[:, None] if was_1d else x
    nyquist = fs / 2.0
    f = float(freq)
    lines = 0
    while f < nyquist and lines < _NOTCH_MAX_LINES:  # fundamental + harmonics
        lines += 1
        b, a = iirnotch(f / nyquist, f / _NOTCH_BW_HZ)
        # Per-channel initial state = steady state for each channel's first
        # sample, so a DC offset doesn't ring in as a startup transient.
        zi = lfilter_zi(b, a)[:, None] * y[0][None, :]
        y, _ = lfilter(b, a, y, axis=0, zi=zi)
        f += freq
    return y[:, 0] if was_1d else y


class NotchFilter:
    """Stateful causal mains-notch — the incremental counterpart of :func:`apply_mains_notch`.

    Builds the same [`scipy.signal.iirnotch`][] biquad cascade for ``(fs, freq)`` once and
    carries each biquad's [`scipy.signal.lfilter`][] state, so successive :meth:`step` calls
    filter only the *new* samples as if one uninterrupted ``lfilter`` ran over the whole
    stream. Feeding the same samples through :meth:`step` in *any* chunking yields output
    identical (within one SciPy build) to :func:`apply_mains_notch` over their concatenation.
    That equivalence is what lets the signal viewer filter only the newly-arrived samples each
    frame instead of re-filtering the whole visible window — the notch analog of the M4
    display-decimation perf fix.

    A non-finite sample would poison the IIR state indefinitely, so a chunk containing any
    non-finite value **resets the state after processing**: the poisoned output scrolls off and
    the next clean chunk re-seeds, matching :func:`compute_rms_trace`'s recover-next-window
    policy rather than corrupting everything downstream.
    """

    def __init__(self, fs: float, freq: int):
        self._biquads: list[tuple[np.ndarray, np.ndarray]] = []
        if freq and np.isfinite(fs) and fs > 0.0:
            nyquist = fs / 2.0
            f = float(freq)
            lines = 0
            while f < nyquist and lines < _NOTCH_MAX_LINES:  # fundamental + harmonics
                lines += 1
                self._biquads.append(iirnotch(f / nyquist, f / _NOTCH_BW_HZ))
                f += freq
        self._zf: list[np.ndarray | None] = [None] * len(self._biquads)

    def reset(self) -> None:
        """Drop the filter state so the next :meth:`step` re-seeds from its first sample."""
        self._zf = [None] * len(self._biquads)

    def step(self, x: np.ndarray) -> np.ndarray:
        """Filter new samples through the cascade, carrying state across calls.

        ``x`` is ``(n,)`` or ``(n, n_channels)``; the return has the same shape. The first call
        (or the first after :meth:`reset`) seeds each biquad from its own first sample, exactly
        as :func:`apply_mains_notch` does; later calls continue from the retained state.
        """
        y = np.ascontiguousarray(x, dtype=np.float64)
        was_1d = y.ndim == 1
        if was_1d:
            y = y[:, None]
        if not self._biquads or len(y) == 0:
            return y[:, 0] if was_1d else y
        clean = bool(np.isfinite(y).all())
        for i, (b, a) in enumerate(self._biquads):
            zi = self._zf[i]
            if zi is None:
                # Cold: steady-state seed from this stage's first sample (matches
                # apply_mains_notch's per-channel `lfilter_zi * y[0]` initialization).
                zi = lfilter_zi(b, a)[:, None] * y[0][None, :]
            y, self._zf[i] = lfilter(b, a, y, axis=0, zi=zi)
        if not clean:
            self.reset()  # a NaN poisoned the state; re-seed on the next clean chunk
        return y[:, 0] if was_1d else y


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
