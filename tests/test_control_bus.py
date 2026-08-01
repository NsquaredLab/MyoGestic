"""Tests for `ControlBus` — the ordering that keeps a target safe.

The bus exists so no application re-derives the sanitise order. These pin the
parts that move a hand if they are wrong: that NaN never becomes full-scale
deflection, that a value cannot leave its declared range even after smoothing,
that the predict thread survives anything, and that rest is delivered before a
target is torn down.
"""

from __future__ import annotations

import math
import types

import numpy as np
import pytest

from myogestic.controls import Continuous, ControlBus, ControlSet, Discrete

#: Aliases with the three shapes that exercise every branch. Built directly: a resolved
#: set is what the bus operates on, and its keys are the user's own names.
MIXED = ControlSet(
    dofs={
        "a": Continuous("a"),                              # signed [-1, 1]
        "g": Continuous("g", lo=0.0, hi=1.0),              # one-way
        "hand.grasp": Discrete("hand.grasp", ("rest", "fist"), "rest"),
    }
)


class Recorder:
    """A target that records what it was handed."""

    def __init__(self) -> None:
        self.bound = None
        self.frames: list[tuple[dict, dict]] = []
        self.stopped = 0

    def bind(self, controls) -> None:
        self.bound = controls

    def send(self, values, changed) -> None:
        self.frames.append((dict(values), dict(changed)))

    def stop(self) -> None:
        self.stopped += 1


class Exploding:
    """A target that fails at everything, to prove the bus survives it."""

    def bind(self, controls) -> None:  # binding must still work
        pass

    def send(self, values, changed) -> None:
        raise RuntimeError("send boom")

    def stop(self) -> None:
        raise RuntimeError("stop boom")


def test_targets_are_bound_at_construction():
    """A target rejects a configuration while a human is still watching."""
    rec = Recorder()
    ControlBus(MIXED, targets=[rec])
    assert rec.bound is MIXED


def test_bind_may_raise_at_construction():
    class Picky:
        def bind(self, controls):
            raise ValueError("cannot render this")

        def send(self, values, changed): ...
        def stop(self): ...

    with pytest.raises(ValueError, match="cannot render"):
        ControlBus(MIXED, targets=[Picky()])


def test_push_delivers_sanitised_values():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    out = bus.push({"a": -0.5, "g": 0.25, "hand.grasp": "fist"})
    assert out["a"] == pytest.approx(-0.5)
    values, _changed = rec.frames[-1]
    assert values["a"] == pytest.approx(-0.5)


def test_nan_never_becomes_full_deflection():
    """`min(hi, max(lo, nan))` is `lo`; rest substitution must come first."""
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    out = bus.push({"a": math.nan, "g": math.nan})
    assert out["a"] == 0.0
    assert out["g"] == 0.0


def test_values_cannot_leave_their_declared_range():
    bus = ControlBus(MIXED, targets=[])
    out = bus.push({"a": 9.0, "g": -9.0})
    assert out["a"] == 1.0
    assert out["g"] == 0.0  # NOT -1.0 — this DOF declares [0, 1]


def test_discrete_edges_only_appear_when_they_change():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    bus.push({"hand.grasp": "fist"})
    assert rec.frames[-1][1] == {"hand.grasp": "fist"}
    bus.push({"hand.grasp": "fist"})
    assert rec.frames[-1][1] == {}, "an unchanged state is not an edge"
    bus.push({"hand.grasp": "rest"})
    assert rec.frames[-1][1] == {"hand.grasp": "rest"}


def test_debounce_seconds_become_ticks_at_the_declared_rate():
    """0.1 s at 50 Hz is five calls: four are silent, the fifth fires."""
    controls = ControlSet(
        dofs={"h.grasp": Discrete("h.grasp", ("rest", "fist"), "rest", debounce_s=0.1)}
    )
    rec = Recorder()
    bus = ControlBus(controls, targets=[rec], hz=50.0)
    for _ in range(4):
        bus.push({"h.grasp": "fist"})
    assert all(not changed for _v, changed in rec.frames)
    bus.push({"h.grasp": "fist"})
    assert rec.frames[-1][1] == {"h.grasp": "fist"}


def test_smoothing_output_is_re_sanitised_and_clipped_per_channel():
    """A filter carries state and can overshoot; the final clip is not cosmetic."""

    def overshooting(x, timestamp=None):
        return np.asarray(x, dtype=np.float32) * 5.0 - 2.0

    bus = ControlBus(MIXED, targets=[], smoothing=overshooting)
    out = bus.push({"a": 1.0, "g": 1.0})
    assert -1.0 <= out["a"] <= 1.0
    assert 0.0 <= out["g"] <= 1.0, "a one-way DOF must not be driven negative"


def test_a_filter_emitting_nan_does_not_reach_a_target():
    def poisoned(x, timestamp=None):
        return np.full_like(np.asarray(x, dtype=np.float32), np.nan)

    bus = ControlBus(MIXED, targets=[], smoothing=poisoned)
    out = bus.push({"a": 0.5, "g": 0.5})
    assert math.isfinite(out["a"])
    assert math.isfinite(out["g"])


def test_push_never_raises_and_falls_back_to_rest():
    """The predict thread logs a traceback every tick, so it must not fail there."""

    def hostile(x, timestamp=None):
        raise RuntimeError("filter boom")

    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec], smoothing=hostile)
    out = bus.push({"a": 0.9})
    assert out == MIXED.rest_values()
    assert rec.frames[-1][0] == MIXED.rest_values()


def test_one_failing_target_does_not_stop_the_others():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[Exploding(), rec])
    bus.push({"a": 0.5})
    assert rec.frames, "the healthy target must still receive the frame"


def test_stop_delivers_rest_before_stopping_targets():
    """A target torn down mid-command leaves the application holding that value."""
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    bus.push({"a": 1.0, "hand.grasp": "fist"})
    bus.stop()
    assert rec.frames[-1][0] == MIXED.rest_values()
    assert rec.stopped == 1


def test_stop_survives_a_target_that_raises():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[Exploding(), rec])
    bus.stop()
    assert rec.stopped == 1


def test_select_bypasses_debounce_and_rebases():
    controls = ControlSet(
        dofs={"h.grasp": Discrete("h.grasp", ("rest", "fist"), "rest", debounce_s=1.0)}
    )
    rec = Recorder()
    bus = ControlBus(controls, targets=[rec], hz=50.0)
    assert bus.select("h.grasp", "fist") is True
    assert rec.frames[-1][1] == {"h.grasp": "fist"}
    before = len(rec.frames)
    bus.push({"h.grasp": "fist"})
    assert rec.frames[-1][1] == {}, "select must rebase so push does not re-fire"
    assert len(rec.frames) == before + 1


def test_select_refuses_an_unknown_dof_or_state():
    bus = ControlBus(MIXED, targets=[])
    assert bus.select("nope", "fist") is False
    assert bus.select("hand.grasp", "nope") is False
    assert bus.select("a", "fist") is False  # continuous is not selectable


def test_rebase_does_not_deliver():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    bus.rebase("hand.grasp", "fist")
    assert rec.frames == []
    bus.push({"hand.grasp": "fist"})
    assert rec.frames[-1][1] == {}, "rebased state must not fire"


# --- conditioning is opt-in, with no invented constant ------------------------


def test_dead_zone_and_hysteresis_are_off_by_default():
    """No universal constant is shipped; both must be measured before use."""
    bus = ControlBus(MIXED, targets=[])
    out = bus.push({"a": 0.02})
    assert out["a"] == pytest.approx(0.02), "a default dead zone would eat this"


def test_dead_zone_suppresses_small_values_and_rescales():
    bus = ControlBus(MIXED, targets=[], dead_zone=0.1)
    assert bus.push({"a": 0.05})["a"] == 0.0
    # Just outside the zone starts from 0, not from a 0.1 jump.
    assert bus.push({"a": 0.1000001})["a"] == pytest.approx(0.0, abs=1e-5)
    # Full scale still reaches full scale.
    assert bus.push({"a": 1.0})["a"] == pytest.approx(1.0)
    assert bus.push({"a": -1.0})["a"] == pytest.approx(-1.0)


def test_hysteresis_blocks_chatter_across_rest():
    """Rest is interior for a signed DOF, so noise around 0 would reverse direction."""
    bus = ControlBus(MIXED, targets=[], hysteresis=0.3)
    assert bus.push({"a": 0.8})["a"] == pytest.approx(0.8)
    # A small excursion the other way is held at rest rather than reversing.
    assert bus.push({"a": -0.1})["a"] == 0.0
    # A decisive move the other way is allowed through.
    assert bus.push({"a": -0.9})["a"] == pytest.approx(-0.9)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"hz": 0.0}, "hz must be > 0"),
        ({"hz": math.inf}, "hz must be > 0"),
        ({"dead_zone": 1.0}, "dead_zone must be >= 0 and < 1"),
        ({"dead_zone": -0.1}, "dead_zone must be >= 0 and < 1"),
        ({"hysteresis": 1.5}, "hysteresis must be >= 0 and < 1"),
    ],
)
def test_bad_construction_arguments_are_refused(kwargs, match):
    with pytest.raises(ValueError, match=match):
        ControlBus(MIXED, targets=[], **kwargs)


def test_a_clip_is_reported_once_not_every_tick():
    warnings: list[str] = []
    bus = ControlBus(MIXED, targets=[], on_warn=warnings.append)
    for _ in range(5):
        bus.push({"a": 9.0})
    assert len(warnings) == 1, "a per-tick warning erases the log that explains it"
    assert "a" in warnings[0]


# --- the three layers, and the boundaries between them --------------------------
#
# Smoothing is not one mechanism. Continuous DOFs are numerically filtered; discrete
# DOFs are *stability gated*; a renderer may additionally blend for appearance. The
# tests below pin the boundaries, because collapsing any two of them is a bug and each
# collapse has its own failure mode.


def test_layer_1_continuous_smoothing_actually_ramps():
    """A step must arrive as a ramp — otherwise `smoothing` is doing nothing.

    The filter is settled at rest first: a one-euro filter's very first sample passes
    through unchanged, correctly, because there is nothing yet to interpolate from.
    """
    from myogestic.outputs.filters import OneEuroFilter

    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec], smoothing=OneEuroFilter(), hz=50)
    for _ in range(4):
        bus.push({"a": 0.0, "hand.grasp": "rest"})
    settled = len(rec.frames)

    for _ in range(6):
        bus.push({"a": 1.0, "hand.grasp": "rest"})
    ramp = [f[0]["a"] for f in rec.frames[settled:]]
    assert ramp[0] < 1.0, f"the step must lag rather than jump: {ramp}"
    assert ramp == sorted(ramp), f"a step should approach monotonically, got {ramp}"
    assert ramp[-1] > ramp[0], "and it must actually be approaching"


def test_layer_1_smoothing_is_applied_before_the_target_sees_anything():
    """Authoritative means *before* delivery: two targets must never disagree."""
    from myogestic.outputs.filters import OneEuroFilter

    a, b = Recorder(), Recorder()
    bus = ControlBus(MIXED, targets=[a, b], smoothing=OneEuroFilter(), hz=50)
    for _ in range(4):
        bus.push({"a": 1.0})
    assert [f[0]["a"] for f in a.frames] == [f[0]["a"] for f in b.frames]


def test_layer_2_a_discrete_dof_is_never_numerically_filtered():
    """The invariant the split exists for.

    Averaging "rest" and "fist" would interpolate through a state nobody selected. A
    discrete value must always be exactly one of its declared states, no matter what
    filter is configured — the filter only ever sees the continuous vector.
    """
    from myogestic.outputs.filters import OneEuroFilter

    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec], smoothing=OneEuroFilter(), hz=50)
    for state in ("rest", "fist", "rest", "fist", "fist", "rest"):
        bus.push({"a": 0.5, "hand.grasp": state})
    delivered = [f[0]["hand.grasp"] for f in rec.frames]
    assert set(delivered) <= {"rest", "fist"}, delivered
    for value in delivered:
        assert isinstance(value, str), f"a filtered discrete value would be a float: {value!r}"


def test_layer_2_the_filter_only_ever_sees_continuous_channels():
    """Proven by inspecting the vector handed to the filter, not just the output."""
    widths: list[int] = []

    def spy(vec):
        widths.append(len(vec))
        return vec

    ControlBus(MIXED, targets=[Recorder()], smoothing=spy, hz=50).push(
        {"a": 0.2, "g": 0.4, "hand.grasp": "fist"}
    )
    # Two continuous DOFs in MIXED; the discrete one is not in the vector at all.
    assert widths == [2]


def test_layer_2_debounce_gates_a_chattering_classifier():
    """The thing a low-pass filter cannot do for a discrete control.

    A classifier flickering between states tick to tick must produce *no* transition
    until one state holds — not an averaged in-between, and not a stream of edges.
    """
    controls = ControlSet(
        dofs={
            # 0.06 s at 50 Hz is 3 ticks.
            "hand.grasp": Discrete("hand.grasp", ("rest", "fist"), "rest", debounce_s=0.06)
        }
    )
    rec = Recorder()
    bus = ControlBus(controls, targets=[rec], hz=50)
    for state in ("fist", "rest", "fist", "rest", "fist", "rest"):
        bus.push({"hand.grasp": state})
    assert all(not f[1] for f in rec.frames), "chatter must not produce a single edge"

    for _ in range(4):
        bus.push({"hand.grasp": "fist"})
    assert any(f[1] == {"hand.grasp": "fist"} for f in rec.frames), "a settled state must fire"


def test_layer_2_a_settled_state_fires_exactly_once():
    """A held state is not an event stream — re-sending it must not re-fire."""
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec], hz=50)
    for _ in range(8):
        bus.push({"hand.grasp": "fist"})
    fired = [f[1] for f in rec.frames if f[1]]
    assert len(fired) == 1, fired


def test_the_two_gates_are_independent():
    """Debounce must not delay a continuous value, nor smoothing delay a transition."""
    from myogestic.outputs.filters import OneEuroFilter

    controls = ControlSet(
        dofs={
            "a": Continuous("a"),
            "hand.grasp": Discrete("hand.grasp", ("rest", "fist"), "rest", debounce_s=0.1),
        }
    )
    rec = Recorder()
    bus = ControlBus(controls, targets=[rec], smoothing=OneEuroFilter(), hz=50)
    bus.push({"a": 1.0, "hand.grasp": "fist"})
    # The continuous channel is delivered on the very first tick even though the
    # discrete one is still inside its debounce window.
    assert rec.frames[0][0]["a"] != 0.0
    assert rec.frames[0][1] == {}


def test_layer_3_is_not_represented_in_the_bus_at_all():
    """Renderer blending is the target's business, and the bus has no opinion on it.

    If the bus grew a "visual smoothing" setting it would be the second authoritative
    smoother, and two authorities is how a commanded value stops being knowable.
    """
    import inspect

    params = set(inspect.signature(ControlBus.__init__).parameters)
    assert params & {"smoothing", "hysteresis", "dead_zone"}
    assert not {p for p in params if "blend" in p or "visual" in p or "present" in p}


def test_connect_controls_reports_a_refusing_target_instead_of_raising():
    """`_ensure_vhi()` is a button handler in every shipped example.

    `capabilities()` gained a third outcome with the version gate — answered, silent, or
    *refused* — and only the first two were handled, so an old renderer took the window
    down. Loud beats silent, but fatal was never the intent: the caller can act on "got a
    bus" and "did not", and the reason belongs in the log where it can be read.
    """
    from myogestic.controls import connect_controls, load_control_map

    class TooOld:
        def capabilities(self):
            raise ValueError("speaks control vocabulary 1 ... Update the renderer.")

    logged: list[str] = []
    ctx = types.SimpleNamespace(log=logged.append, control_space=None)
    control_map = load_control_map({"dofs": {"a": "vhi.prediction.index"}})
    assert connect_controls(control_map, [TooOld()], ctx=ctx) is None
    assert any("vocabulary 1" in line for line in logged), logged
