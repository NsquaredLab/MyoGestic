"""Tests for `ControlBus` — the ordering that keeps a target safe.

The bus exists so no application re-derives the sanitise order. These pin the
parts that move a hand if they are wrong: that NaN never becomes full-scale
deflection, that a value cannot leave its declared range even after smoothing,
that the predict thread survives anything, and that rest is delivered before a
target is torn down.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from myogestic.controls import ControlBus, load_dofs

MIXED = load_dofs(
    {
        "dofs": {
            "a.flexion": "continuous",                                     # [-1, 1]
            "g.force": {"kind": "continuous", "range": [0.0, 1.0]},        # one-way
            "hand.grasp": ["rest", "fist"],
        }
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
    out = bus.push({"a.flexion": -0.5, "g.force": 0.25, "hand.grasp": "fist"})
    assert out["a.flexion"] == pytest.approx(-0.5)
    values, _changed = rec.frames[-1]
    assert values["a.flexion"] == pytest.approx(-0.5)


def test_nan_never_becomes_full_deflection():
    """`min(hi, max(lo, nan))` is `lo`; rest substitution must come first."""
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    out = bus.push({"a.flexion": math.nan, "g.force": math.nan})
    assert out["a.flexion"] == 0.0
    assert out["g.force"] == 0.0


def test_values_cannot_leave_their_declared_range():
    bus = ControlBus(MIXED, targets=[])
    out = bus.push({"a.flexion": 9.0, "g.force": -9.0})
    assert out["a.flexion"] == 1.0
    assert out["g.force"] == 0.0  # NOT -1.0 — this DOF declares [0, 1]


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
    controls = load_dofs(
        {"dofs": {"h.grasp": {"kind": "discrete", "states": ["rest", "fist"],
                              "debounce_s": 0.1}}}
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
    out = bus.push({"a.flexion": 1.0, "g.force": 1.0})
    assert -1.0 <= out["a.flexion"] <= 1.0
    assert 0.0 <= out["g.force"] <= 1.0, "a one-way DOF must not be driven negative"


def test_a_filter_emitting_nan_does_not_reach_a_target():
    def poisoned(x, timestamp=None):
        return np.full_like(np.asarray(x, dtype=np.float32), np.nan)

    bus = ControlBus(MIXED, targets=[], smoothing=poisoned)
    out = bus.push({"a.flexion": 0.5, "g.force": 0.5})
    assert math.isfinite(out["a.flexion"])
    assert math.isfinite(out["g.force"])


def test_push_never_raises_and_falls_back_to_rest():
    """The predict thread logs a traceback every tick, so it must not fail there."""

    def hostile(x, timestamp=None):
        raise RuntimeError("filter boom")

    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec], smoothing=hostile)
    out = bus.push({"a.flexion": 0.9})
    assert out == MIXED.rest_values()
    assert rec.frames[-1][0] == MIXED.rest_values()


def test_one_failing_target_does_not_stop_the_others():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[Exploding(), rec])
    bus.push({"a.flexion": 0.5})
    assert rec.frames, "the healthy target must still receive the frame"


def test_stop_delivers_rest_before_stopping_targets():
    """A target torn down mid-command leaves the application holding that value."""
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[rec])
    bus.push({"a.flexion": 1.0, "hand.grasp": "fist"})
    bus.stop()
    assert rec.frames[-1][0] == MIXED.rest_values()
    assert rec.stopped == 1


def test_stop_survives_a_target_that_raises():
    rec = Recorder()
    bus = ControlBus(MIXED, targets=[Exploding(), rec])
    bus.stop()
    assert rec.stopped == 1


def test_select_bypasses_debounce_and_rebases():
    controls = load_dofs(
        {"dofs": {"h.grasp": {"kind": "discrete", "states": ["rest", "fist"],
                              "debounce_s": 1.0}}}
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
    assert bus.select("a.flexion", "fist") is False  # continuous is not selectable


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
    out = bus.push({"a.flexion": 0.02})
    assert out["a.flexion"] == pytest.approx(0.02), "a default dead zone would eat this"


def test_dead_zone_suppresses_small_values_and_rescales():
    bus = ControlBus(MIXED, targets=[], dead_zone=0.1)
    assert bus.push({"a.flexion": 0.05})["a.flexion"] == 0.0
    # Just outside the zone starts from 0, not from a 0.1 jump.
    assert bus.push({"a.flexion": 0.1000001})["a.flexion"] == pytest.approx(0.0, abs=1e-5)
    # Full scale still reaches full scale.
    assert bus.push({"a.flexion": 1.0})["a.flexion"] == pytest.approx(1.0)
    assert bus.push({"a.flexion": -1.0})["a.flexion"] == pytest.approx(-1.0)


def test_hysteresis_blocks_chatter_across_rest():
    """Rest is interior for a signed DOF, so noise around 0 would reverse direction."""
    bus = ControlBus(MIXED, targets=[], hysteresis=0.3)
    assert bus.push({"a.flexion": 0.8})["a.flexion"] == pytest.approx(0.8)
    # A small excursion the other way is held at rest rather than reversing.
    assert bus.push({"a.flexion": -0.1})["a.flexion"] == 0.0
    # A decisive move the other way is allowed through.
    assert bus.push({"a.flexion": -0.9})["a.flexion"] == pytest.approx(-0.9)


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
        bus.push({"a.flexion": 9.0})
    assert len(warnings) == 1, "a per-tick warning erases the log that explains it"
    assert "a.flexion" in warnings[0]
