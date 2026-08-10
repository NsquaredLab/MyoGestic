"""Signal conditioning applied to acquisition — what the model and the recording see.

Distinct from `myogestic.widgets.signals.transforms`, which conditions what is *drawn*.
A display filter can be anything; these run on the samples themselves, so they are in
the core rather than under `widgets` and `Stream` can reach them without importing UI.

`apply_mains_notch` and `NotchFilter` are the offline and streaming halves of the same
filter, and their equality is the property everything else here relies on: the live path
filters chunk by chunk while an analysis script filters a whole recording at once, and a
model must not be able to tell which produced its input.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import iirnotch, lfilter, lfilter_zi

#: -3 dB width of each notch, in Hz. `Q = f0 / _NOTCH_BW_HZ`.
_NOTCH_BW_HZ = 3.0

#: Fundamental + this many harmonics are notched; each is one biquad, so this
#: bounds per-frame cost.
_NOTCH_MAX_LINES = 5


def apply_mains_notch(data: np.ndarray, fs: float, freq: int) -> np.ndarray:
    """Remove mains-line interference at ``freq`` Hz (and its harmonics).

    A visual-only notch for the signal viewer, meant to run *before* the display
    filter. Implemented as a **causal** IIR notch — one 2nd-order
    [`scipy.signal.iirnotch`][] biquad per harmonic below Nyquist, cascaded
    and applied with [`scipy.signal.lfilter`][] along axis 0.

    Causal matters here: the scope scrolls, so a given sample is re-filtered on
    many frames as the visible window slides over it. A causal filter's output at
    sample ``i`` depends only on samples ``<= i``, so the already-drawn trace stays
    put, where a zero-phase/FFT notch would rewrite past samples every frame. The
    caller must feed a warm-up slice *before* the region it displays and drop it,
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
    identical (within one SciPy build) to :func:`apply_mains_notch` over their concatenation
    — for concatenations of **≥ 8 samples**, below which ``apply_mains_notch`` no-ops as a
    too-short guard while :meth:`step` always filters.

    A non-finite sample would poison the IIR state indefinitely, so a chunk containing any
    non-finite value **resets the state after processing**: the poisoned output scrolls off
    and the next clean chunk re-seeds, matching :func:`compute_rms_trace`'s
    recover-next-window policy.
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
