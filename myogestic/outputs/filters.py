"""Output-side smoothing filters for *prediction-output control vectors*.

This module is for post-processing the final 1-D vector being pushed to an
actuator or visualization (hand pose, prosthetic command, cursor position).
It is NOT a DSP filter for raw EMG / sensor features — for that, use
scipy.signal or a domain library upstream of `extract()`.

All filters expect floating-point 1-D ``np.ndarray`` inputs. Integer inputs
are accepted but the output is cast back to the input dtype, which will
quantize the smoothed values — pass float32/float64 if you want smooth
output.

Pattern:

    from myogestic.outputs.filters import make_filter
    output_filter = make_filter("one_euro", hz=32)

    @pipeline.predict
    def predict(model, features):
        pred = model.predict(features.reshape(1, -1))[0]
        pred = output_filter(pred)        # smooth before pushing
        vhi_outlet.push(pred)
        return {"pred": pred}

To swap filters in an experiment, change one string.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np


class VectorFilter(Protocol):
    """Stateful per-vector filter. Call once per output tick."""

    def reset(self) -> None: ...
    def __call__(self, x: np.ndarray, t: float | None = None) -> np.ndarray: ...


class IdentityFilter:
    """Passthrough — useful as a baseline or "off" toggle."""

    def reset(self) -> None:
        pass

    def __call__(self, x: np.ndarray, t: float | None = None) -> np.ndarray:
        return x


class GaussianFilter:
    """Rolling temporal smoothing for 1-D vectors.

    Keeps the last ``window`` vectors and returns their Gaussian-weighted
    mean (weights peak at the most recent sample). During warmup (buffer
    not yet full), weights are renormalized over the available history —
    no zero-padding bias.

    Inputs must be 1-D arrays of consistent length (raises on first
    dimension mismatch).
    """

    def __init__(self, window: int = 5, sigma: float = 1.0):
        if window < 1:
            raise ValueError(f"window must be >= 1 (got {window})")
        if sigma <= 0:
            raise ValueError(f"sigma must be > 0 (got {sigma})")
        self.window = window
        self.sigma = sigma
        # Gaussian kernel centered on the most recent sample (last position).
        idx = np.arange(window, dtype=np.float64)
        weights = np.exp(-((idx - (window - 1)) ** 2) / (2.0 * sigma * sigma))
        self._weights = weights / weights.sum()
        self._buf: list[np.ndarray] = []

    def reset(self) -> None:
        self._buf.clear()

    def __call__(self, x: np.ndarray, t: float | None = None) -> np.ndarray:
        x_arr = np.asarray(x, dtype=np.float64)
        if x_arr.ndim != 1:
            raise ValueError(f"GaussianFilter expects a 1-D vector, got ndim={x_arr.ndim}")
        self._buf.append(x_arr)
        if len(self._buf) > self.window:
            self._buf.pop(0)
        n = len(self._buf)
        w = self._weights[-n:]
        w = w / w.sum()
        stacked = np.stack(self._buf)
        out = (stacked * w[:, None]).sum(axis=0)
        return out.astype(x.dtype, copy=False)


class OneEuroFilter:
    """1€ Filter — adaptive low-pass for noisy interactive signals.

    Trades latency for smoothness based on instantaneous velocity:
    fast motion → high cutoff (responsive), slow motion → low cutoff
    (smooth). Standard for hand tracking, controllers, gesture cursors.

    Reference: https://gery.casiez.net/1euro/

    Parameters
    ----------
    hz
        Expected sample rate (Hz). Used as a fallback dt when no
        timestamp is passed to ``__call__``. Filter accuracy depends
        on this matching the *actual* call rate; pass ``t`` from your
        predict loop if the rate is jittery.
    min_cutoff_hz
        Cutoff (Hz) at zero velocity — controls baseline smoothing.
    beta
        Velocity-to-cutoff gain. Larger → more responsive on fast moves.
    derivative_cutoff_hz
        Cutoff (Hz) for the velocity smoother.
    """

    def __init__(
        self,
        hz: float = 50.0,
        min_cutoff_hz: float = 1.0,
        beta: float = 0.02,
        derivative_cutoff_hz: float = 1.0,
    ):
        if hz <= 0:
            raise ValueError(f"hz must be > 0 (got {hz})")
        if min_cutoff_hz <= 0:
            raise ValueError(f"min_cutoff_hz must be > 0 (got {min_cutoff_hz})")
        if derivative_cutoff_hz <= 0:
            raise ValueError(f"derivative_cutoff_hz must be > 0 (got {derivative_cutoff_hz})")
        self.hz = hz
        self.min_cutoff_hz = min_cutoff_hz
        self.beta = beta
        self.derivative_cutoff_hz = derivative_cutoff_hz
        self._x_prev: np.ndarray | None = None
        self._dx_prev: np.ndarray | None = None
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff: np.ndarray | float, dt: float) -> np.ndarray | float:
        tau = 1.0 / (2.0 * np.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def reset(self) -> None:
        self._x_prev = None
        self._dx_prev = None
        self._t_prev = None

    def __call__(self, x: np.ndarray, t: float | None = None) -> np.ndarray:
        x_arr = np.asarray(x, dtype=np.float64)
        if t is not None and self._t_prev is not None:
            dt = max(1e-6, t - self._t_prev)
        else:
            dt = 1.0 / self.hz
        self._t_prev = t

        # Bind to locals so the checker can narrow both Optionals together —
        # _x_prev and _dx_prev are always set (and cleared) as a pair.
        x_prev = self._x_prev
        dx_prev = self._dx_prev
        if x_prev is None or dx_prev is None:
            self._x_prev = x_arr.copy()
            self._dx_prev = np.zeros_like(x_arr)
            return x_arr.astype(x.dtype, copy=False)

        dx = (x_arr - x_prev) / dt
        a_d = self._alpha(self.derivative_cutoff_hz, dt)
        dx_smooth = a_d * dx + (1 - a_d) * dx_prev
        self._dx_prev = dx_smooth

        cutoff = self.min_cutoff_hz + self.beta * np.abs(dx_smooth)
        a = self._alpha(cutoff, dt)
        x_smooth = a * x_arr + (1 - a) * x_prev
        self._x_prev = x_smooth
        return x_smooth.astype(x.dtype, copy=False)


def make_filter(name: str, hz: float = 50.0, **kwargs: Any) -> VectorFilter:
    """Construct a filter by name. Swap filters in an experiment by
    changing one string; pass extra kwargs to tune without instantiating
    the class directly.

    Parameters
    ----------
    name
        ``"identity"`` | ``"gaussian"`` | ``"one_euro"``.
    hz
        Expected sample rate. Forwarded as ``hz`` to ``one_euro``;
        ignored by the others.
    **kwargs
        Forwarded to the filter constructor — e.g.
        ``make_filter("gaussian", window=10, sigma=2.0)``,
        ``make_filter("one_euro", hz=32, beta=0.05)``.

    Raises
    ------
    ValueError
        if the name isn't recognized.
    TypeError
        if a kwarg is unknown for the chosen filter.
    """
    n = name.lower()
    if n == "identity":
        if kwargs:
            raise TypeError(f"identity takes no kwargs (got {list(kwargs)})")
        return IdentityFilter()
    if n == "gaussian":
        # GaussianFilter's own defaults are window=5, sigma=1.0 — no need to
        # restate them; kwargs overrides as needed.
        return GaussianFilter(**kwargs)
    if n == "one_euro":
        return OneEuroFilter(
            **{
                "hz": hz,
                "min_cutoff_hz": 1.0,
                "beta": 0.02,
                "derivative_cutoff_hz": 1.0,
                **kwargs,
            }
        )
    raise ValueError(f"Unknown filter {name!r}. Choose: 'identity', 'gaussian', 'one_euro'.")
