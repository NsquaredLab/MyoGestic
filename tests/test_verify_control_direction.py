"""The direction gate's own decisions, checked without a renderer.

`tools/verify_control_direction.py` is a gate: a live run of it is what says the
predicted hand still flexes on a control +1. That makes its *judgement* load-bearing —
a gate whose assertions are inverted or vacuous is worse than no gate, because it blesses
the regression it was written to catch. These tests feed it canned observations and pin
what it accepts and what it refuses.

Nothing here launches VHI or opens a stream; the tool's four checks are pure decisions
over numbers, and this is that layer.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

TOOL = pathlib.Path(__file__).parent.parent / "tools" / "verify_control_direction.py"


def _load():
    """Import the tool by path — `tools/` is not a package."""
    spec = importlib.util.spec_from_file_location("verify_control_direction", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load()


class _Observation:
    """One bone in a sweep reply."""

    def __init__(self, element: str, degrees_at_hi: float):
        self.element = element
        self.degrees_at_hi = degrees_at_hi


class _Reply:
    """A `SweepControlReply`, as much of one as the tool reads."""

    def __init__(self, observed, completed=True, message=""):
        self.observed = observed
        self.completed = completed
        self.message = message


class _Client:
    """A control client whose sweep returns whatever the test wants."""

    def __init__(self, reply):
        self._reply = reply

    def sweep(self, name, duration_s=2.0, both_directions=True):
        return self._reply


FLEXED = [_Observation("WaveBone_7", -85.0), _Observation("WaveBone_8", -75.0)]
EXTENDED = [_Observation("WaveBone_7", 85.0), _Observation("WaveBone_8", 75.0)]


# --- check 1: direction ---------------------------------------------------------


def test_a_closing_hand_passes():
    """Negative degrees is what `Movements.Fist` is, so this is the accepting case."""
    assert "WaveBone_7 -85.0°" in verify.check_direction(_Client(_Reply(FLEXED)))


def test_an_opening_hand_is_refused():
    """The regression this whole gate exists for: +1 rendered as extension."""
    with pytest.raises(verify.Failure, match="extended WaveBone_7"):
        verify.check_direction(_Client(_Reply(EXTENDED)))


def test_one_backwards_bone_out_of_two_is_refused():
    """A partly-inverted rig is not a pass — a mixed sign is worse than a clean flip."""
    mixed = [_Observation("WaveBone_7", -85.0), _Observation("WaveBone_8", 75.0)]
    with pytest.raises(verify.Failure, match="extended WaveBone_8"):
        verify.check_direction(_Client(_Reply(mixed)))


def test_a_bone_resting_at_zero_is_refused():
    """`>= 0` not `> 0`: a bone that did not move renders no direction at all."""
    with pytest.raises(verify.Failure, match="extended"):
        verify.check_direction(_Client(_Reply([_Observation("WaveBone_7", 0.0)])))


def test_a_sweep_that_moved_nothing_is_refused():
    """An empty `observed` must not read as "nothing was wrong"."""
    with pytest.raises(verify.Failure, match="moved nothing"):
        verify.check_direction(_Client(_Reply([])))


def test_an_incomplete_sweep_is_refused():
    with pytest.raises(verify.Failure, match="did not complete"):
        verify.check_direction(_Client(_Reply(FLEXED, completed=False)))


def test_a_missing_reply_is_refused():
    """`sweep` returns None on any RPC failure — that is not a pass either."""
    with pytest.raises(verify.Failure, match="did not complete"):
        verify.check_direction(_Client(None))


# --- checks 2-4: round-trip, declaration independence, frame stability ---------


@pytest.fixture
def scenarios(monkeypatch):
    """Drive `check_scenarios` off canned read-backs, one list per scenario."""

    def run(*per_scenario):
        frames = list(per_scenario)
        monkeypatch.setattr(verify, "_declared", lambda *a, **k: _Bus())
        monkeypatch.setattr(
            verify, "_hold", lambda *a, **k: frames.pop(0) if frames else []
        )
        return verify.check_scenarios(None, None, None, None)

    return run


class _Bus:
    """A bus the scenario stops when it is done with it."""

    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


HELD = [1.0] * 12


def test_three_agreeing_scenarios_pass(scenarios):
    assert scenarios(HELD, HELD, HELD) == {
        "undeclared": 1.0,
        "predicted-only": 1.0,
        "predicted+control-pose": 1.0,
    }


def test_an_inverted_read_back_is_refused(scenarios):
    """Sent +1, read -1: exactly what a renderer negating on ingest reports."""
    with pytest.raises(verify.Failure, match="not the identity"):
        scenarios([-1.0] * 12, HELD, HELD)


def test_a_zero_read_back_is_refused(scenarios):
    """A dead inlet reads zero, and zero is not +1. It must not pass as "no movement"."""
    with pytest.raises(verify.Failure, match="not the identity"):
        scenarios([0.0] * 12, HELD, HELD)


def test_a_read_back_that_drifts_while_held_is_refused(scenarios):
    """Frame stability: the input was constant, so the output may not wander."""
    with pytest.raises(verify.Failure, match="moved while the input was held"):
        scenarios([1.0, 1.0, 0.4, 1.0], HELD, HELD)


def test_a_declaration_dependent_direction_is_refused(scenarios):
    """The finding that started this: same +1, different render per declaration.

    The band this fires in is deliberately narrow, and worth being clear about: a gross
    disagreement — say undeclared reading -1 while declared reads +1 — trips the identity
    check first, on the scenario that is wrong. What is left for the cross-check is a
    drift that every scenario passes on its own, which is why both values here sit just
    inside tolerance of +1 while being further than that from each other.
    """
    low, high = 1.0 - 0.9 * verify.TOL, 1.0 + 0.9 * verify.TOL
    with pytest.raises(verify.Failure, match="depends on what was declared"):
        scenarios([low] * 12, HELD, [high] * 12)


def test_too_few_frames_is_refused(scenarios):
    """One sample cannot show stability, so it is not allowed to stand in for it."""
    with pytest.raises(verify.Failure, match="need frames"):
        scenarios([1.0], HELD, HELD)


def test_the_tolerance_is_not_wide_enough_to_hide_a_sign(scenarios):
    """Guards the constant itself: `TOL` must reject -1 against +1 by a wide margin."""
    assert verify.TOL < 0.5
    with pytest.raises(verify.Failure):
        scenarios([-1.0] * 12, HELD, HELD)
