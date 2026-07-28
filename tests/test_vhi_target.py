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

import dataclasses

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


# --- the outlet the target is normally handed -----------------------------------


def test_the_vhi_outlet_advertises_a_stable_source_id():
    """Without one, a consumer that resolved the old outlet keeps a dead inlet.

    Measured against the real binary: VHI warns about the missing source ID on
    connect, and its own re-resolve only runs while it holds no inlet at all — so
    after a MyoGestic restart it stayed deaf until VHI itself was restarted. LSL can
    only recover the pairing if the outlet identifies itself the same way twice.
    """
    from myogestic.vhi import virtual_hand

    spec = virtual_hand()
    first, second = spec.outlet(), spec.outlet()
    try:
        a = first._outlet.get_sinfo().source_id
        b = second._outlet.get_sinfo().source_id
        assert a, "an empty source_id is what makes the stream unrecoverable"
        assert a == b, "the id must be stable across restarts, not per-instance"
        assert spec.output_stream_name in a
    finally:
        first.stop()
        second.stop()


# --- v2 probing and the fallback ------------------------------------------------
#
# The reply is duck-typed rather than a real protobuf message: VhiTarget reads four
# fields off it, and pinning those four keeps these tests free of the grpc extra.
# `test_declare_request_maps_the_control_set` covers the real message separately.


@dataclasses.dataclass
class FakeVerdict:
    name: str
    renderable: bool = True
    message: str = ""


#: The v2 `ContinuousEncoding` values.
UNSPECIFIED, CANONICAL, LEGACY_NEGATED = 0, 1, 2


@dataclasses.dataclass
class FakeReply:
    accepted: bool = True
    continuous_channel_order: tuple[str, ...] = ()
    verdicts: tuple[FakeVerdict, ...] = ()
    standard_version: str = "1"
    continuous_encoding: int = CANONICAL


class FakeClient:
    """A `VhiCanonicalClient` stand-in recording what the target asked of it."""

    def __init__(self, reply=None) -> None:
        self.reply = reply
        self.declared: list[object] = []
        self.sent: list[tuple[dict | None, dict | None]] = []

    def declare(self, controls, client_name=""):
        self.declared.append(controls)
        return self.reply

    def set_control(self, continuous=None, discrete=None):
        self.sent.append((continuous, discrete))


NINE = (
    "thumb.flexion",
    "thumb.abduction",
    "index.flexion",
    "middle.flexion",
    "ring.flexion",
    "little.flexion",
    "wrist.flexion",
    "wrist.abduction",
    "wrist.rotation",
)


def test_without_a_client_the_legacy_path_is_used():
    target, _ = _bound()
    assert target.negotiated is False


def test_an_older_vhi_answers_nothing_and_the_legacy_path_is_used():
    """`declare` returning None means "does not speak v2" — an answer, not a failure."""
    client = FakeClient(reply=None)
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls())
    assert client.declared, "the handshake must at least be attempted"
    assert target.negotiated is False


def test_a_negotiated_binding_uses_the_declared_order():
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=FakeClient(FakeReply(continuous_channel_order=NINE)))
    target.bind(_controls(*NINE))
    assert target.negotiated is True
    target.send({**dict.fromkeys(NINE, 0.0), "wrist.rotation": 1.0}, {})
    assert outlet.last[8] == pytest.approx(1.0)


def test_a_negotiated_binding_does_not_negate():
    """The sign flip was a property of the old wire, never of the standard."""
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=FakeClient(FakeReply(continuous_channel_order=NINE)))
    target.bind(_controls(*NINE))
    target.send({**dict.fromkeys(NINE, 0.0), "index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(+1.0)


def test_negotiation_lifts_the_legacy_refusals():
    """A wrist is renderable once VHI says so — the limit was the wire's, not ours."""
    target = VhiTarget(FakeOutlet(), client=FakeClient(FakeReply(continuous_channel_order=NINE)))
    target.bind(_controls(*NINE))  # would raise "no legacy channel" without v2
    assert target.negotiated is True


def test_a_partial_acceptance_falls_all_the_way_back():
    """Rendering only the accepted DOFs would hide the refused ones as held joints."""
    client = FakeClient(
        FakeReply(
            accepted=False,
            continuous_channel_order=NINE,
            verdicts=(FakeVerdict("wrist.rotation", renderable=False, message="no wrist"),),
        )
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="no legacy channel"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_channel_order_that_disagrees_falls_back():
    """Guessing a mapping is exactly what the standard exists to stop."""
    client = FakeClient(FakeReply(continuous_channel_order=("something.else",) * 9))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="no legacy channel"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_width_the_outlet_cannot_carry_falls_back():
    """The outlet's channel count is fixed at construction; a wider frame cannot fit."""
    order = (*NINE, "extra.dof")
    client = FakeClient(FakeReply(continuous_channel_order=order))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="no legacy channel"):
        target.bind(_controls(*order))
    assert target.negotiated is False


def test_discrete_edges_go_over_grpc_when_negotiated():
    """v2 lifts v1's pose/movement exclusivity, so both travel at once."""
    client = FakeClient(FakeReply(continuous_channel_order=NINE))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls(*NINE))
    target.send(dict.fromkeys(NINE, 0.0), {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_no_edge_means_no_rpc():
    """A pose is re-sent every tick; a state change is not."""
    client = FakeClient(FakeReply(continuous_channel_order=NINE))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls(*NINE))
    for _ in range(5):
        target.send(dict.fromkeys(NINE, 0.0), {})
    assert client.sent == []


def test_stop_rests_in_the_negotiated_order_and_flushes():
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=FakeClient(FakeReply(continuous_channel_order=NINE)))
    target.bind(_controls(*NINE))
    target.send(dict.fromkeys(NINE, 1.0), {})
    target.stop()
    assert outlet.last.tolist() == [0.0] * 9
    assert outlet.flushes == 1


def test_rebinding_re_negotiates_rather_than_keeping_the_old_verdict():
    """A reconnect can land on a different VHI; a stale mode would encode wrongly."""
    client = FakeClient(FakeReply(continuous_channel_order=NINE))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls(*NINE))
    assert target.negotiated is True
    client.reply = None
    target.bind(_controls())
    assert target.negotiated is False


def test_declare_request_maps_the_control_set():
    """The real protobuf message, including declaration order and both kinds."""
    pytest.importorskip("grpc")
    from myogestic.vhi._client_v2 import declare_request

    controls = load_dofs(
        {
            "dofs": {
                "index.flexion": "continuous",
                "grip.force": {"kind": "continuous", "range": [0.0, 1.0]},
                "hand.grasp": ["rest", "fist"],
            }
        }
    )
    request = declare_request(controls, "probe")
    assert request.client_name == "probe"
    assert [d.name for d in request.dofs] == ["index.flexion", "grip.force", "hand.grasp"]
    index, grip, grasp = request.dofs
    assert (index.lo, index.hi, index.rest) == (-1.0, 1.0, 0.0)
    assert (grip.lo, grip.hi) == (0.0, 1.0)
    assert list(grasp.states) == ["rest", "fist"]
    assert grasp.rest_state == "rest"


def test_a_reply_that_does_not_state_its_encoding_falls_back():
    """The bug the field exists for: guessing a sign convention inverts every joint.

    The first end-to-end v2 run agreed on channel names while VHI still decoded legacy
    units, so a canonical +1 arrived as legacy +1 and the hand extended when it was
    told to flex. A server that will not say gets no benefit of the doubt.
    """
    client = FakeClient(
        FakeReply(continuous_channel_order=NINE, continuous_encoding=UNSPECIFIED)
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="no legacy channel"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_legacy_negated_wire_is_negated():
    """VHI reports this while its continuous path is still the pre-v2 decoder."""
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(
            FakeReply(continuous_channel_order=NINE, continuous_encoding=LEGACY_NEGATED)
        ),
    )
    target.bind(_controls(*NINE))
    assert target.negotiated is True
    target.send({**dict.fromkeys(NINE, 0.0), "index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(-1.0)


def test_a_canonical_wire_is_not_negated():
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(
            FakeReply(continuous_channel_order=NINE, continuous_encoding=CANONICAL)
        ),
    )
    target.bind(_controls(*NINE))
    target.send({**dict.fromkeys(NINE, 0.0), "index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(+1.0)


def test_a_negotiated_order_shorter_than_the_wire_pads_the_tail():
    """VHI names six channels on a nine-float transport; the tail stays at rest.

    It will not name a channel it does not read — naming dead channels is how the four
    wrong pose tables came to exist — so a short order is normal, not a mismatch.
    """
    six = LEGACY_POSE_DOFS
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(
            FakeReply(continuous_channel_order=six, continuous_encoding=LEGACY_NEGATED)
        ),
    )
    target.bind(_controls(*six))
    assert target.negotiated is True
    target.send({**dict.fromkeys(six, 0.0), "little.flexion": 1.0}, {})
    assert outlet.last.shape == (LEGACY_POSE_WIDTH,)
    assert outlet.last[5] == pytest.approx(-1.0)
    assert outlet.last[6:].tolist() == [0.0, 0.0, 0.0]


def test_a_discrete_only_configuration_negotiates_and_delivers():
    """The bug tracking negotiation explicitly fixes.

    A discrete-only config has an empty continuous channel order, so inferring
    "negotiated" from that order left the target believing it was on the legacy path
    — which refuses discrete DOFs and would have rendered nothing at all.
    """
    client = FakeClient(
        FakeReply(
            continuous_channel_order=(),
            continuous_encoding=LEGACY_NEGATED,
            verdicts=(FakeVerdict("hand.grasp"),),
        )
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(load_dofs({"dofs": {"hand.grasp": ["rest", "fist"]}}))
    assert target.negotiated is True
    target.send({"hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_a_mixed_configuration_negotiates_both_kinds():
    """v2 lifts v1's exclusivity: a pose and a held state travel together."""
    client = FakeClient(
        FakeReply(
            continuous_channel_order=("index.flexion",),
            continuous_encoding=LEGACY_NEGATED,
        )
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(
        load_dofs({"dofs": {"index.flexion": "continuous", "hand.grasp": ["rest", "fist"]}})
    )
    assert target.negotiated is True
    target.send({"index.flexion": 1.0, "hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert outlet.last[0] == pytest.approx(-1.0)
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_a_subset_of_the_negotiated_channels_is_legal():
    """VHI reports its whole channel map; a client may command part of it.

    Requiring an exact set match made every subset configuration fall back, even
    though Declare had accepted it — and the negotiated order is a channel map, not a
    demand that the client drive every channel on it.
    """
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(
            FakeReply(
                continuous_channel_order=LEGACY_POSE_DOFS,
                continuous_encoding=LEGACY_NEGATED,
            )
        ),
    )
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    target.send({"index.flexion": 1.0}, {})
    # Placed at the channel VHI named, not at position 0 of the declaration.
    assert outlet.last[2] == pytest.approx(-1.0)
    assert outlet.last[0] == 0.0


def test_a_declared_dof_with_no_negotiated_channel_falls_back():
    """The case that must still fail: a DOF with nowhere to go renders nothing."""
    client = FakeClient(
        FakeReply(
            continuous_channel_order=("index.flexion",),
            continuous_encoding=LEGACY_NEGATED,
        )
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="no legacy channel"):
        target.bind(_controls("index.flexion", **{"wrist.rotation": "continuous"}))
    assert target.negotiated is False
