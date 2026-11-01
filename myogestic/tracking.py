"""Subject-facing task trajectories — the target a participant is asked to track.

Pure geometry and arithmetic. Nothing here imports imgui or talks to a device, so the
same trajectory can be evaluated in a test, in an offline script, and by whatever draws
it on screen — one definition, no second implementation to drift.

Task time is seconds since the block started. Levels carry the unit of the thing being
tracked, and there are three:

- `Trapezoid` is **percent of MVC**, which is what `Calibration.normalise` turns a raw
  force sample into, so a target and a live reading are directly comparable without
  either knowing the load cell's units.
- `Pursuit` is **signed, normalised control units in [-1, +1]** — the scale a decoder's
  output already lives on. It moves a cursor rather than naming a force, so there is no
  physical maximum to express it as a fraction of.

- `Sinusoid` is a **fraction in [0, 1]** of an app-defined gesture for following runs.

`Trajectory` is what the shapes have in common and all that anything streaming one needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike

_SEGMENTS = ("rest_s", "ramp_up_s", "hold_s", "ramp_down_s", "recover_s")


class Trajectory(Protocol):
    """What a trajectory has to offer to be streamed and recorded.

    Structural, so `Trapezoid`, `Pursuit` and any shape added later satisfy it by
    having these three members rather than by inheriting anything. It is deliberately
    narrower than either concrete class: `TargetSource` reads exactly this much, so a
    shape is free to differ in everything else — segments, levels, units.

    The unit of `value_at` is the trajectory's own, and is not part of this contract —
    percent of MVC for `Trapezoid`, signed control units for `Pursuit`. What *is* part
    of it is that `phase_at` returns a name from the recorded phase table, so a
    recording can be sliced by phase whatever shape produced it.
    """

    @property
    def total_duration(self) -> float:
        """Seconds for the whole block, after which the target is over."""
        ...

    def value_at(self, t: float) -> float:
        """Target level at task time `t` seconds, in the trajectory's own unit."""
        ...

    def phase_at(self, t: float) -> str:
        """Which segment task time `t` falls in — a key of `PHASE_CODES`."""
        ...


@dataclass(frozen=True, slots=True)
class Trapezoid:
    """A trapezoidal force-tracking target: rest, ramp up, hold, ramp down, recover.

    Named for the shape, not the study — a triangular or sinusoidal target is a
    different shape and gets its own name in this module rather than a flag on this one.

    Every segment is independently configurable and **may be zero**: ``hold_s=0`` is a
    legal triangle, ``rest_s=0`` starts the ramp immediately. A zero-length segment is
    simply skipped; the trajectory steps straight to the next level.

    Parameters
    ----------
    rest_s
        Baseline seconds before the ramp begins.
    ramp_up_s
        Seconds spent rising linearly from baseline to `level_pct`.
    hold_s
        Seconds at `level_pct`.
    ramp_down_s
        Seconds spent falling linearly back to baseline.
    recover_s
        Baseline seconds after the ramp, before the next repetition.
    level_pct
        Plateau height as a percentage of MVC.
    reps
        How many times the shape repeats back to back.

    Examples
    --------
    >>> from myogestic.tracking import Trapezoid
    >>> task = Trapezoid(rest_s=1.0, ramp_up_s=2.0, hold_s=4.0, ramp_down_s=2.0,
    ...                  recover_s=1.0, level_pct=40.0)
    >>> task.duration
    10.0
    >>> task.value_at(2.0), task.phase_at(2.0)
    (20.0, 'ramp_up')
    >>> task.value_at(5.0), task.phase_at(5.0)
    (40.0, 'hold')
    >>> task.value_at(10.0), task.phase_at(10.0)
    (0.0, 'done')
    """

    rest_s: float = 3.0
    ramp_up_s: float = 5.0
    hold_s: float = 10.0
    ramp_down_s: float = 5.0
    recover_s: float = 5.0
    level_pct: float = 30.0
    reps: int = 1

    def __post_init__(self) -> None:
        for name in _SEGMENTS:
            if getattr(self, name) < 0:
                raise ValueError(
                    f"Trapezoid({name}={getattr(self, name)!r}): pass a duration in "
                    f"seconds >= 0 (0 skips the segment)"
                )
        if self.level_pct < 0:
            raise ValueError(
                f"Trapezoid(level_pct={self.level_pct!r}): pass a plateau height >= 0, "
                f"in percent of MVC"
            )
        if self.reps < 1:
            raise ValueError(f"Trapezoid(reps={self.reps!r}): pass at least 1 repetition")

    @property
    def duration(self) -> float:
        """Seconds for one repetition."""
        return float(sum(getattr(self, name) for name in _SEGMENTS))

    @property
    def total_duration(self) -> float:
        """Seconds for the whole block — one repetition times `reps`."""
        return self.duration * self.reps

    def value_at(self, t: float) -> float:
        """Target level in percent of MVC at task time `t` seconds.

        Baseline segments are ``0.0``, ramps are linear, the hold is `level_pct`.
        Before the block starts and once it has finished, the target is ``0.0``.

        Parameters
        ----------
        t
            Task time in seconds since the block started.
        """
        return self._at(t)[1]

    def phase_at(self, t: float) -> str:
        """Which segment task time `t` falls in.

        One of ``"rest"``, ``"ramp_up"``, ``"hold"``, ``"ramp_down"``, ``"recover"``,
        or ``"done"`` once the whole block has elapsed.

        Parameters
        ----------
        t
            Task time in seconds since the block started.
        """
        return self._at(t)[0]

    def _at(self, t: float) -> tuple[str, float]:
        """Resolve `t` to its (phase, level) once, so the two public views cannot drift."""
        if t < 0.0:
            return "rest", 0.0
        if t >= self.total_duration:
            return "done", 0.0

        # Past the guard above the block is non-empty, so `duration` is > 0.
        u = t % self.duration

        # Each `u < edge` is false for a zero-length segment, so an empty ramp is never
        # entered and its division by zero is unreachable.
        edge = self.rest_s
        if u < edge:
            return "rest", 0.0
        start, edge = edge, edge + self.ramp_up_s
        if u < edge:
            return "ramp_up", self.level_pct * (u - start) / self.ramp_up_s
        edge += self.hold_s
        if u < edge:
            return "hold", self.level_pct
        start, edge = edge, edge + self.ramp_down_s
        if u < edge:
            return "ramp_down", self.level_pct * (1.0 - (u - start) / self.ramp_down_s)
        return "recover", 0.0


#: Fractional part of the golden ratio. Irrational, so ``frac(i * _GOLDEN)`` never
#: repeats and never settles into a pattern the subject can learn — the deterministic
#: stand-in for a random draw. It is also the *worst* case for rational approximation,
#: which is exactly why its orbit is the most evenly spread of any rotation: consecutive
#: waypoints land far apart and the set of them fills the range without clumping.
_GOLDEN = (5.0**0.5 - 1.0) / 2.0


@lru_cache(maxsize=64)
def _pursuit_levels(hops: int) -> tuple[float, ...]:
    """Waypoint levels for one `Pursuit` repetition — ``hops + 1`` of them.

    Starts and ends at ``0.0`` so a repetition begins and ends at rest. The interior is
    the golden-ratio orbit, then stretched by a single affine map onto ``[-1, +1]`` so
    the extremes are *reached exactly* rather than approached: the raw orbit's own
    minimum becomes ``-1`` and its maximum ``+1``. Stretching rather than clipping keeps
    the spacing of every other waypoint intact.

    Parameters
    ----------
    hops
        Number of waypoint-to-waypoint segments in one repetition.
    """
    interior = hops - 1
    if interior < 1:
        return (0.0, 0.0)
    if interior == 1:
        # One waypoint has no spread to normalise against; a single full excursion is
        # the only sensible reading of "one hop out and one back".
        return (0.0, 1.0, 0.0)
    raw = [(i * _GOLDEN) % 1.0 for i in range(1, hops)]
    lo, hi = min(raw), max(raw)
    return (0.0, *(2.0 * (u - lo) / (hi - lo) - 1.0 for u in raw), 0.0)


@dataclass(frozen=True, slots=True)
class Pursuit:
    """A signed pursuit target: rest, then a smooth aperiodic wander over [-1, +1].

    Why this shape and not a trapezoid. A cued block that only ever asks for "down",
    "rest" and "up" holds three distinct target values, so a regressor trained on it has
    never seen an intermediate one: nothing in the *data* says what half a contraction
    should produce, and what the fit does between the cued levels is whatever its own
    inductive bias supplies. For the tree ensembles shipped here that is an average of
    the targets it saw, which cannot be an intermediate level at all; least squares, at
    the other end, draws the straight line through them and needs nothing more. This trajectory instead spends its whole length at
    intermediate levels, so the mapping from effort to output is *measured* rather than
    assumed, and monotonicity in effort is something the fit is actually held to.

    The shape is a chain of `hops` equal-length segments between waypoints, each
    interpolated with a smootherstep (:math:`6x^5 - 15x^4 + 10x^3`). That gives three
    things a proportional decoder needs:

    - **Dense, even coverage of the level axis.** Waypoints come from the golden-ratio
      orbit, whose defining property is that it spreads a sequence as evenly as any
      sequence can be spread. The interpolation eases to a standstill at each waypoint,
      so dwell time follows waypoint density and every level is trained on, not just
      the ones between the extremes. With the defaults no twentieth of the range takes
      less than 2% of the **wander** — 1.7% of the whole block, the difference being the
      rest and recover segments, which sit at one level and are not part of the sweep.
    - **Rate largely decoupled from level.** Segments are equal in time but not in
      height, so the same level is crossed slowly on one pass and quickly on another.
      Under a single sinusoid the target is always slowest at the extremes and fastest
      at zero, and a decoder can learn that confound instead of the level; here the
      correlation between level and speed falls from about -0.92 to -0.21. Not to zero,
      and the residue is at the extremes: ±1 are waypoints and the interpolation eases
      to a standstill at every waypoint, so full deflection is still only ever reached
      slowly (mean rate 0.18 units/s beyond |v| > 0.9, against 0.52 below |v| < 0.5).
    - **Nothing to anticipate.** The orbit is irrational, so the path never repeats
      *within* a repetition and the subject has to track rather than recall — yet it is
      pure arithmetic on the hop index, so two sessions record the identical trajectory
      and a test can assert an exact value. `reps` above 1 repeats the same path
      deliberately, to make repetitions comparable, and every rep after the first is
      therefore learnable: raise `hops` rather than `reps` to lengthen a block the
      subject should not be able to anticipate.

    The rest segments matter as much as the wander: they are exactly ``0.0`` and stay
    there, which is where a decoder learns its baseline. A target that is always moving
    never says where zero is.

    Values are continuous everywhere, including across repetitions, and the slope is
    bounded — a target that steps cannot be followed, and every jump would land in the
    training set as effort the subject never produced.

    Parameters
    ----------
    rest_s
        Baseline seconds before the wander begins.
    hop_s
        Seconds per waypoint-to-waypoint segment. The difficulty knob: halving it
        doubles every rate without changing the levels visited.
    hops
        How many segments one repetition is made of. Fewer than about 16 and the
        coverage starts to clump.
    recover_s
        Baseline seconds after the wander, before the next repetition.
    reps
        How many times the trajectory repeats back to back. Identical each time, so
        repetitions are directly comparable.

    Examples
    --------
    >>> from myogestic.tracking import Pursuit
    >>> task = Pursuit(rest_s=2.0, hop_s=1.0, hops=4, recover_s=2.0)
    >>> task.duration
    8.0
    >>> task.value_at(1.0), task.phase_at(1.0)
    (0.0, 'rest')
    >>> task.value_at(4.0), task.phase_at(4.0)
    (-1.0, 'ramp_up')
    >>> round(task.value_at(4.5), 6), task.phase_at(4.5)
    (0.0, 'ramp_up')
    >>> task.value_at(8.0), task.phase_at(8.0)
    (0.0, 'done')
    """

    rest_s: float = 5.0
    hop_s: float = 2.0
    hops: int = 24
    recover_s: float = 5.0
    reps: int = 1

    def __post_init__(self) -> None:
        for name in ("rest_s", "hop_s", "recover_s"):
            if getattr(self, name) < 0:
                raise ValueError(
                    f"Pursuit({name}={getattr(self, name)!r}): pass a duration in "
                    f"seconds >= 0 (0 skips the segment)"
                )
        if self.hops < 1:
            raise ValueError(f"Pursuit(hops={self.hops!r}): pass at least 1 hop")
        if self.reps < 1:
            raise ValueError(f"Pursuit(reps={self.reps!r}): pass at least 1 repetition")

    @property
    def duration(self) -> float:
        """Seconds for one repetition."""
        return float(self.rest_s + self.hops * self.hop_s + self.recover_s)

    @property
    def total_duration(self) -> float:
        """Seconds for the whole block — one repetition times `reps`."""
        return self.duration * self.reps

    def value_at(self, t: float) -> float:
        """Target level in signed control units at task time `t` seconds.

        In ``[-1, +1]``. Rest and recover are exactly ``0.0``, as are the times before
        the block starts and after it has finished.

        Parameters
        ----------
        t
            Task time in seconds since the block started.
        """
        return self._at(t)[1]

    def phase_at(self, t: float) -> str:
        """Which segment task time `t` falls in.

        One of ``"rest"``, ``"ramp_up"`` or ``"ramp_down"`` for a segment heading up or
        down, ``"hold"`` for one whose endpoints are level, ``"recover"``, or ``"done"``
        once the whole block has elapsed. The same vocabulary `Trapezoid` uses, so an
        analysis script can select the rising windows out of either without caring which
        trajectory produced the recording.

        Parameters
        ----------
        t
            Task time in seconds since the block started.
        """
        return self._at(t)[0]

    def _at(self, t: float) -> tuple[str, float]:
        """Resolve `t` to its (phase, level) once, so the two public views cannot drift."""
        if t < 0.0:
            return "rest", 0.0
        if t >= self.total_duration:
            return "done", 0.0

        # Past the guard above the block is non-empty, so `duration` is > 0.
        u = t % self.duration
        if u < self.rest_s:
            return "rest", 0.0
        u -= self.rest_s
        # False for `hop_s == 0`, so an empty wander is skipped and the division below
        # is unreachable with a zero denominator.
        if u >= self.hops * self.hop_s:
            return "recover", 0.0

        levels = _pursuit_levels(self.hops)
        # `min` only guards float slop at the very end of the last hop.
        i = min(int(u // self.hop_s), self.hops - 1)
        a, b = levels[i], levels[i + 1]
        x = (u - i * self.hop_s) / self.hop_s
        # Smootherstep: zero first *and* second derivative at both ends, so the target
        # neither corners nor jerks where two hops meet.
        value = a + (b - a) * (x * x * x * (x * (x * 6.0 - 15.0) + 10.0))
        if b > a:
            return "ramp_up", value
        if b < a:
            return "ramp_down", value
        return "hold", value


@dataclass(frozen=True, slots=True)
class Calibration:
    """Maps a raw force reading onto the percent-of-MVC scale the targets live on.

    Two numbers, not one: a load cell reads some non-zero value with nobody touching it,
    so dividing by `mvc` alone leaves that resting offset in the result and puts every
    target at the wrong force. `zero` is subtracted first, from both the sample and the
    maximum, so 30% really is 30% of the subject's voluntary range.

    Parameters
    ----------
    zero
        The resting reading, in the force channel's own signal units.
    mvc
        The maximum voluntary contraction reading, in the same units.

    Examples
    --------
    >>> from myogestic.tracking import Calibration
    >>> cal = Calibration(zero=1.0, mvc=3.0)
    >>> cal.normalise(1.0), cal.normalise(2.0), cal.normalise(3.0)
    (0.0, 50.0, 100.0)
    """

    zero: float
    mvc: float

    def normalise(self, x: float) -> float:
        """Convert a raw reading to percent of MVC.

        Returns ``0.0`` when `mvc` equals `zero` — an uncalibrated subject reads as no
        effort rather than blowing up mid-trial.

        Parameters
        ----------
        x
            A sample from the force channel, in the channel's own signal units.
        """
        span = self.mvc - self.zero
        if span == 0.0:
            return 0.0
        return 100.0 * (x - self.zero) / span


@dataclass(frozen=True, slots=True)
class Sinusoid:
    """Relaxed hold, half-cosine rise, peak hold and half-cosine return.

    Parameters
    ----------
    move_s
        Positive seconds for each smooth movement.
    hold_high_s, hold_low_s
        Non-negative seconds at the peak and relaxed endpoints.
    peak
        Fraction of the gesture, between zero and one.
    reps
        Positive integer number of cycles.
    lead_s
        Non-negative relaxed preparation time before the first cycle.
    """

    move_s: float = 2.0
    hold_high_s: float = 2.0
    hold_low_s: float = 2.0
    peak: float = 1.0
    reps: int = 5
    lead_s: float = 3.0

    def __post_init__(self) -> None:
        for name in ("move_s", "hold_high_s", "hold_low_s", "lead_s"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or (name == "move_s" and value == 0):
                raise ValueError(
                    f"{name}: pass finite seconds {'> 0' if name == 'move_s' else '>= 0'}"
                )
        if not math.isfinite(self.peak) or not 0 <= self.peak <= 1:
            raise ValueError("peak: pass a finite fraction between 0 and 1")
        if isinstance(self.reps, bool) or not isinstance(self.reps, int) or self.reps < 1:
            raise ValueError("reps: pass a positive integer")
        if not math.isfinite(self.total_duration):
            raise ValueError("durations and reps: pass a finite total run duration")

    @property
    def duration(self) -> float:
        """Seconds per cycle, excluding the lead-in."""
        return self.hold_low_s + 2 * self.move_s + self.hold_high_s

    @property
    def total_duration(self) -> float:
        """Seconds for the lead-in and all cycles."""
        return self.lead_s + self.reps * self.duration

    def value_at(self, t: float) -> float:
        """Fraction of the gesture at `t` seconds; zero outside the run."""
        return self._at(t)[1]

    def phase_at(self, t: float) -> str:
        """Existing phase name at `t`; lead-in and low holds use ``rest``."""
        return self._at(t)[0]

    def _at(self, t: float) -> tuple[str, float]:
        if math.isnan(t):
            raise ValueError("t: pass a time in seconds, not NaN")
        if t < self.lead_s:
            return "rest", 0.0
        if t >= self.total_duration:
            return "done", 0.0
        u = (t - self.lead_s) % self.duration
        if u < self.hold_low_s:
            return "rest", 0.0
        u -= self.hold_low_s
        if u < self.move_s:
            return "ramp_up", self.peak * (1 - math.cos(math.pi * u / self.move_s)) / 2
        u -= self.move_s
        if u < self.hold_high_s:
            return "hold", self.peak
        u -= self.hold_high_s
        return "ramp_down", self.peak * (1 + math.cos(math.pi * u / self.move_s)) / 2


def blend_pose(relaxed: ArrayLike, gesture: ArrayLike, level: float) -> np.ndarray:
    """Blend equally shaped finite pose vectors by a fraction in [0, 1].

    Parameters
    ----------
    relaxed, gesture
        One-dimensional pose vectors in the app's own control units.
    level
        Fraction of the gesture. Values outside [0, 1] are rejected.
    """
    a, b = np.asarray(relaxed, dtype=float), np.asarray(gesture, dtype=float)
    if a.ndim != 1 or a.shape != b.shape or not a.size:
        raise ValueError("relaxed and gesture: pass non-empty pose vectors of the same shape")
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("relaxed and gesture: pass finite pose values")
    if not math.isfinite(level) or not 0 <= level <= 1:
        raise ValueError("level: pass a finite fraction between 0 and 1")
    return a + level * (b - a)


def score_tracking(
    t_target: ArrayLike,
    target: ArrayLike,
    t_pred: ArrayLike,
    pred: ArrayLike,
    *,
    start_s: float | None = None,
    end_s: float | None = None,
    max_lag_s: float = 1.0,
    step_s: float = 0.01,
) -> dict[str, float | None]:
    """Score scalar tracking on a common uniform time grid without extrapolation.

    Parameters
    ----------
    t_target, t_pred
        Strictly increasing finite timestamps in the same clock domain.
    target, pred
        Scalar levels paired with those timestamps. Non-finite levels are discarded.
    start_s, end_s
        Inclusive run bounds on that clock. Set start to run start plus lead-in;
        samples outside these bounds never contribute, including to lag estimation.
        Defaults to the common recorded interval.
    max_lag_s
        Non-negative search radius for normalised cross-correlation.
    step_s
        Positive interpolation step in seconds, also the lag resolution.

    Returns
    -------
    dict
        ``rmse`` and Pearson ``r`` at zero lag, plus ``lag_s`` at the largest
        normalised cross-correlation (positive means prediction follows target).
        A lag needs at least three samples and half the common interval in overlap;
        ties prefer the smallest absolute lag. Undefined metrics are ``None``.
        Constant signals can have an RMSE but no correlation or lag.
    """
    if not math.isfinite(max_lag_s) or max_lag_s < 0:
        raise ValueError("max_lag_s: pass a finite search radius >= 0")
    if not math.isfinite(step_s) or step_s <= 0:
        raise ValueError("step_s: pass a finite sampling step > 0")
    for bound in (start_s, end_s):
        if bound is not None and not math.isfinite(bound):
            raise ValueError("start_s and end_s: pass finite timestamps or None")
    if start_s is not None and end_s is not None and start_s > end_s:
        raise ValueError("end_s: pass a timestamp at or after start_s")

    def samples(times: ArrayLike, values: ArrayLike) -> tuple[np.ndarray, np.ndarray]:
        t, y = np.asarray(times, dtype=float), np.asarray(values, dtype=float)
        if t.ndim != 1 or t.shape != y.shape:
            raise ValueError("timestamps and levels: pass equally sized one-dimensional arrays")
        if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
            raise ValueError("timestamps: pass finite, strictly increasing seconds")
        keep = np.isfinite(y)
        if start_s is not None:
            keep &= t >= start_s
        if end_s is not None:
            keep &= t <= end_s
        return t[keep], y[keep]

    tt, y = samples(t_target, target)
    tp, p = samples(t_pred, pred)
    result: dict[str, float | None] = {"rmse": None, "r": None, "lag_s": None}
    if not len(tt) or not len(tp):
        return result
    lo, hi = max(tt[0], tp[0]), min(tt[-1], tp[-1])
    if hi < lo:
        return result
    grid = lo + np.arange(int((hi - lo) / step_s) + 1) * step_s
    a, b = np.interp(grid, tt, y), np.interp(grid, tp, p)
    result["rmse"] = float(np.sqrt(np.mean((a - b) ** 2)))

    def correlation(x: np.ndarray, y: np.ndarray) -> float | None:
        if len(x) < 2 or np.ptp(x) <= 1e-12 or np.ptp(y) <= 1e-12:
            return None
        return float(np.clip(np.corrcoef(x, y)[0, 1], -1, 1))

    result["r"] = correlation(a, b)
    if result["r"] is None:
        return result
    limit = min(int(max_lag_s / step_s), len(grid) // 2)
    best = -math.inf
    for shift in sorted(range(-limit, limit + 1), key=abs):
        x, y = (
            (a[:-shift], b[shift:])
            if shift > 0
            else (a[-shift:], b[:shift])
            if shift < 0
            else (a, b)
        )
        if len(x) < 3:
            continue
        r = correlation(x, y)
        if r is not None and r > best + 1e-12:
            best, result["lag_s"] = r, shift * step_s
    return result
