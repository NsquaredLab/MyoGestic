"""`VhiTarget` — canonical DOF values in, legacy VHI pose frames out.

The target is the only place that knows VHI counts channels, that flexion is
negative there, and that three channels are dead. These pin both halves of that
contract: what it refuses at `bind` (while a human is still reading the traceback),
and what it puts on the wire per tick.

Every test here runs against a recording `PoseSink`, so the whole target is
verified without a hand running. What that deliberately cannot prove is that VHI
*renders* these frames as intended — that needs the binary, and the wire values
themselves are pinned against real recordings in `test_vhi_legacy.py`.
"""

from __future__ import annotations

import numpy as np
import pytest

from myogestic.controls import ControlBus, ControlSet, load_dofs
from myogestic.outputs.filters import GaussianFilter
from myogestic.vhi.legacy import LEGACY_POSE_DOFS, LEGACY_POSE_WIDTH, decode_pose
from myogestic.vhi.target import VhiTarget


class FakeOutlet:
    """A `PoseSink` that records what reached the wire."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.flushes = 0

    def push(self, data: np.ndarray) -> None:
        self.frames.append(np.array(data, copy=True))

    def flush(self) -> None:
        self.flushes += 1

    @property
    def last(self) -> np.ndarray:
        assert self.frames, "nothing was ever pushed"
        return self.frames[-1]


def _controls(*names: str, **entries: object):
    """A pose configuration — all six legacy DOFs when no names are given."""
    dofs: dict[str, object] = dict.fromkeys(names or LEGACY_POSE_DOFS, "continuous")
    dofs.update(entries)
    return load_dofs({"dofs": dofs})


def _bound(*names: str, **entries: object) -> tuple[VhiTarget, FakeOutlet]:
    outlet = FakeOutlet()
    target = VhiTarget(outlet)
    target.bind(_controls(*names, **entries))
    return target, outlet


# --- bind: refuse what cannot be rendered -------------------------------------


def test_bind_accepts_the_six_legacy_dofs():
    target, outlet = _bound()
    assert outlet.frames == []
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 0.0), {})
    assert outlet.last.shape == (LEGACY_POSE_WIDTH,)


def test_bind_accepts_a_subset():
    """Declaring one finger is legal; the rest of the hand simply stays neutral."""
    _, outlet = _bound("index.flexion")
    assert outlet.frames == []


def test_bind_refuses_discrete_dofs():
    """Legacy ControlMode makes streamed pose and named movements exclusive."""
    with pytest.raises(ValueError, match="ControlMode"):
        VhiTarget(FakeOutlet()).bind(
            load_dofs({"dofs": {"index.flexion": "continuous", "hand.grasp": ["rest", "fist"]}})
        )


def test_bind_refuses_a_discrete_only_configuration():
    with pytest.raises(ValueError, match="cannot render discrete"):
        VhiTarget(FakeOutlet()).bind(load_dofs({"dofs": {"hand.grasp": ["rest", "fist"]}}))


def test_bind_refuses_an_empty_configuration():
    """`ControlSet()` directly, because `load_dofs` refuses an empty table first."""
    with pytest.raises(ValueError, match="no continuous DOFs"):
        VhiTarget(FakeOutlet()).bind(ControlSet())


@pytest.mark.parametrize("name", ["wrist.rotation", "wrist.flexion", "hand.aperture"])
def test_bind_refuses_a_dof_with_no_legacy_channel(name):
    """A silently dropped joint is indistinguishable from one holding still."""
    with pytest.raises(ValueError, match="no legacy channel"):
        VhiTarget(FakeOutlet()).bind(_controls("index.flexion", **{name: "continuous"}))


def test_the_refusal_names_what_is_renderable():
    """The message has to be actionable, not just a rejection."""
    with pytest.raises(ValueError) as excinfo:
        VhiTarget(FakeOutlet()).bind(_controls("wrist.rotation"))
    message = str(excinfo.value)
    assert "wrist.rotation" in message
    assert "index.flexion" in message


def test_bind_refuses_before_anything_is_pushed():
    """Refusal happens at setup, so a rejected configuration never actuates."""
    outlet = FakeOutlet()
    with pytest.raises(ValueError):
        VhiTarget(outlet).bind(_controls("wrist.rotation"))
    assert outlet.frames == []


# --- send: the wire frame -----------------------------------------------------


def test_send_pushes_a_full_width_float32_frame():
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 1.0), {})
    assert outlet.last.shape == (LEGACY_POSE_WIDTH,)
    assert outlet.last.dtype == np.float32


def test_send_negates_into_the_legacy_convention():
    """Canonical +1 means the direction the name denotes; VHI wants -1 for flexion."""
    target, outlet = _bound()
    target.send({**dict.fromkeys(LEGACY_POSE_DOFS, 0.0), "index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(-1.0)


def test_send_zeroes_the_dead_channels():
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 1.0), {})
    assert outlet.last[6:].tolist() == [0.0, 0.0, 0.0]


def test_send_round_trips_through_decode():
    """The two halves of the bridge agree, so train and serve cannot drift."""
    values = {
        "thumb.flexion": 0.25,
        "thumb.abduction": -1.0,
        "index.flexion": 1.0,
        "middle.flexion": 0.0,
        "ring.flexion": -0.5,
        "little.flexion": 0.75,
    }
    target, outlet = _bound()
    target.send(values, {})
    decoded = decode_pose(outlet.last)
    for name, v in values.items():
        assert float(decoded[name]) == pytest.approx(v, abs=1e-6), name


def test_send_ignores_a_name_it_was_not_bound_to():
    """A stray key must not reach a channel — bind is the whole authority."""
    target, outlet = _bound("index.flexion")
    target.send({"index.flexion": 1.0, "thumb.flexion": 1.0}, {})
    assert outlet.last[0] == 0.0
    assert outlet.last[2] == pytest.approx(-1.0)


def test_send_falls_back_to_rest_for_a_missing_name():
    """`send` runs on the predict thread: a KeyError there would hold the last pose."""
    target, outlet = _bound()
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last.tolist() == [0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_send_honours_a_declared_nonzero_rest_for_a_missing_name():
    """The fallback is the DOF's own rest, not a hardcoded zero."""
    target, outlet = _bound(
        "index.flexion",
        **{"thumb.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.5}},
    )
    target.send({"index.flexion": 0.0}, {})
    assert outlet.last[0] == pytest.approx(-0.5)


def test_send_accepts_numpy_float32_values():
    """The library's prediction dtype — `isinstance(v, float)` is False for it."""
    target, outlet = _bound()
    target.send({n: np.float32(1.0) for n in LEGACY_POSE_DOFS}, {})
    assert outlet.last[:6].tolist() == [-1.0] * 6


def test_send_clamps_a_value_outside_the_canonical_domain():
    """The bus clips first, but the encoder is the last line before the wire."""
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 5.0), {})
    assert outlet.last.min() >= -1.0
    assert outlet.last.max() <= 1.0


def test_send_ignores_the_changed_map():
    """No discrete DOFs can be bound, so there are never edges to deliver."""
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 0.0), {"hand.grasp": "fist"})
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH


def test_a_one_way_dof_never_emits_the_direction_it_excludes():
    target, outlet = _bound(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}})
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(-1.0)
    target.send({"index.flexion": 0.0}, {})
    assert outlet.last[2] == 0.0


def test_every_send_pushes_exactly_one_frame():
    """Latest-wins downstream: a target that pushed twice would drop a tick."""
    target, outlet = _bound()
    for _ in range(5):
        target.send(dict.fromkeys(LEGACY_POSE_DOFS, 0.0), {})
    assert len(outlet.frames) == 5


# --- stop: rest has to actually land ------------------------------------------


def test_stop_pushes_rest_and_flushes_it():
    """Pushing alone would leave the frame unsent in a paced slot at exit."""
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 1.0), {})
    target.stop()
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH
    assert outlet.flushes == 1


def test_stop_rests_at_the_declared_rest_not_at_zero():
    target, outlet = _bound(
        **{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.5}}
    )
    target.stop()
    assert outlet.last[2] == pytest.approx(-0.5)


def test_stop_is_idempotent():
    target, outlet = _bound()
    target.stop()
    target.stop()
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH
    assert outlet.flushes == 2


def test_stop_before_bind_does_not_raise():
    """Teardown runs even when setup failed — that is when it matters most."""
    outlet = FakeOutlet()
    VhiTarget(outlet).stop()
    assert outlet.frames == []
    assert outlet.flushes == 1


# --- through a real ControlBus ------------------------------------------------


def test_the_bus_binds_the_target_at_construction():
    outlet = FakeOutlet()
    with pytest.raises(ValueError, match="no legacy channel"):
        ControlBus(_controls("wrist.rotation"), targets=[VhiTarget(outlet)])
    assert outlet.frames == []


def test_a_bus_frame_reaches_the_wire():
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet)])
    bus.push({"index.flexion": 0.5})
    assert outlet.last[2] == pytest.approx(-0.5)


def test_nan_reaches_the_wire_as_rest_not_full_deflection():
    """`min(hi, max(lo, nan))` is `lo` — the bus substitutes rest before clipping."""
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet)])
    bus.push({"index.flexion": float("nan")})
    assert outlet.last[2] == 0.0


def test_an_out_of_range_prediction_is_clipped_before_the_wire():
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet)])
    bus.push(dict.fromkeys(LEGACY_POSE_DOFS, 40.0))
    assert outlet.last.min() >= -1.0


def test_smoothing_cannot_push_a_value_out_of_range():
    """The bug the ordering fixes: clip-then-smooth lets the filter overshoot out."""
    outlet = FakeOutlet()
    bus = ControlBus(
        _controls(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}}),
        targets=[VhiTarget(outlet)],
        smoothing=GaussianFilter(sigma=1.0),
    )
    for _ in range(40):
        bus.push({"index.flexion": 1.0})
    for _ in range(40):
        bus.push({"index.flexion": 0.0})
    stacked = np.stack(outlet.frames)
    assert stacked[:, 2].min() >= -1.0
    assert stacked[:, 2].max() <= 0.0


def test_bus_stop_returns_the_hand_to_rest_and_flushes():
    """The whole safety chain: rest is delivered, then made to land, then stopped."""
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet)])
    bus.push(dict.fromkeys(LEGACY_POSE_DOFS, 1.0))
    assert outlet.last.min() == pytest.approx(-1.0)
    bus.stop()
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH
    assert outlet.flushes == 1


def test_a_broken_outlet_does_not_kill_the_predict_thread():
    """The bus absorbs a target failure; a raise here would log on every tick."""

    class Broken(FakeOutlet):
        def push(self, data):
            raise OSError("outlet closed")

    warnings: list[str] = []
    bus = ControlBus(
        _controls(), targets=[VhiTarget(Broken())], on_warn=warnings.append
    )
    bus.push({"index.flexion": 1.0})
    assert any("VhiTarget" in w for w in warnings)


def test_two_targets_receive_the_same_frame():
    """One sanitised frame, fanned out — a recorder beside the hand."""
    a, b = FakeOutlet(), FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(a), VhiTarget(b)])
    bus.push({"middle.flexion": 0.5})
    assert a.last.tolist() == b.last.tolist()
