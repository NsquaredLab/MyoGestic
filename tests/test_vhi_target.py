"""`VhiTarget` — control values in, pose frames out, on a contract it negotiated.

The target is the only place that knows VHI counts channels, which channel a control
sits on, or which way the renderer's units run. Since the v2 cutover it learns all of
that by *asking*: there is no table of channels and no fallback, so a configuration it
cannot place is refused while a human is still reading the traceback rather than
half-rendered later.

These pin both halves of that: what `bind` refuses, and what reaches the wire per tick.
Every test runs against a recording `PoseSink` and a fake client, so the whole target is
verified without a hand running. What that deliberately cannot prove is that VHI
*renders* these frames as intended — that needs the binary, and the recorded pose format
itself is pinned in `test_vhi_legacy.py`.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from myogestic.controls import ControlBus, ControlSet
from myogestic.outputs.filters import GaussianFilter
from myogestic.vhi.legacy import LEGACY_POSE_DOFS, LEGACY_POSE_WIDTH
from myogestic.vhi.target import VhiTarget

from .conftest import build_controls


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


# --- the fake renderer every binding negotiates against -------------------------
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
UNSPECIFIED, CANONICAL, NEGATED = 0, 1, 2


@dataclasses.dataclass
class FakeReply:
    accepted: bool = True
    continuous_channel_order: tuple[str, ...] = ()
    verdicts: tuple[FakeVerdict, ...] = ()
    standard_version: str = "1"
    continuous_encoding: int = CANONICAL
    control_pose_stream_name: str = ""
    control_pose_channel_order: tuple[str, ...] = ()
    control_pose_encoding: int = UNSPECIFIED


class FakeClient:
    """A `VhiCanonicalClient` stand-in recording what the target asked of it."""

    def __init__(self, reply=None) -> None:
        self.reply = reply
        self.declared: list[object] = []
        self.sent: list[tuple[dict | None, dict | None]] = []

    def declare(self, controls, client_name="", control_pose=""):
        self.declared.append((controls, control_pose))
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


#: The six controls VHI's pose transport actually renders. Channels 6-8 exist on the
#: wire and are read by nothing, which is why a negotiated order can be shorter than it.
POSE = LEGACY_POSE_DOFS


def _client(order=POSE, **reply):
    """A renderer that accepts a by-name declaration in canonical units."""
    return FakeClient(FakeReply(continuous_channel_order=order, **reply))


def _controls(*names: str, **entries: object):
    """A pose configuration — all six legacy DOFs when no names are given."""
    dofs: dict[str, object] = dict.fromkeys(names or LEGACY_POSE_DOFS, "continuous")
    dofs.update(entries)
    return build_controls(dofs)


def _bound(*names: str, **entries: object) -> tuple[VhiTarget, FakeOutlet]:
    """A target bound to a renderer that names the six pose controls, canonically."""
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=_client())
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


def test_bind_refuses_an_empty_configuration():
    """`ControlSet()` directly, because there is no parser to refuse it first."""
    with pytest.raises(ValueError, match="no DOFs at all"):
        VhiTarget(FakeOutlet()).bind(ControlSet())


def test_bind_refuses_before_anything_is_pushed():
    """Refusal happens at setup, so a rejected configuration never actuates."""
    outlet = FakeOutlet()
    with pytest.raises(ValueError):
        VhiTarget(outlet, client=_client()).bind(_controls("wrist.rotation"))
    assert outlet.frames == []


# --- send: the wire frame -----------------------------------------------------


def test_send_pushes_a_full_width_float32_frame():
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 1.0), {})
    assert outlet.last.shape == (LEGACY_POSE_WIDTH,)
    assert outlet.last.dtype == np.float32


def test_send_zeroes_the_dead_channels():
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 1.0), {})
    assert outlet.last[6:].tolist() == [0.0, 0.0, 0.0]


def test_send_ignores_a_name_it_was_not_bound_to():
    """A stray key must not reach a channel — bind is the whole authority."""
    target, outlet = _bound("index.flexion")
    target.send({"index.flexion": 1.0, "thumb.flexion": 1.0}, {})
    assert outlet.last[0] == 0.0
    assert outlet.last[2] == pytest.approx(1.0)


def test_send_falls_back_to_rest_for_a_missing_name():
    """`send` runs on the predict thread: a KeyError there would hold the last pose."""
    target, outlet = _bound()
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last.tolist() == [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_send_honours_a_declared_nonzero_rest_for_a_missing_name():
    """The fallback is the DOF's own rest, not a hardcoded zero."""
    target, outlet = _bound(
        "index.flexion",
        **{"thumb.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.5}},
    )
    target.send({"index.flexion": 0.0}, {})
    assert outlet.last[0] == pytest.approx(0.5)


def test_send_accepts_numpy_float32_values():
    """The library's prediction dtype — `isinstance(v, float)` is False for it."""
    target, outlet = _bound()
    target.send({n: np.float32(1.0) for n in LEGACY_POSE_DOFS}, {})
    assert outlet.last[:6].tolist() == [1.0] * 6


def test_a_routed_binding_clamps_to_the_range_the_target_declared():
    """The bus clips first; a routed slot clamps again to what the renderer accepts.

    The two are not the same bound — a weight is applied between them — so the target's
    own range is the last word before the wire.
    """
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), MANIFEST
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=ManifestClient(FakeReply()))
    target.bind(controls)
    target.send({"a": 5.0}, {})
    assert outlet.last.max() <= 1.0


def test_send_ignores_the_changed_map():
    """No discrete DOFs can be bound, so there are never edges to deliver."""
    target, outlet = _bound()
    target.send(dict.fromkeys(LEGACY_POSE_DOFS, 0.0), {"hand.grasp": "fist"})
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH


def test_a_one_way_dof_never_emits_the_direction_it_excludes():
    target, outlet = _bound(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}})
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(1.0)
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
    assert outlet.last[2] == pytest.approx(0.5)


def test_stop_is_idempotent():
    target, outlet = _bound()
    target.stop()
    target.stop()
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH
    assert outlet.flushes == 2


def test_stop_before_bind_does_not_raise():
    """Teardown runs even when setup failed — that is when it matters most."""
    outlet = FakeOutlet()
    VhiTarget(outlet, client=_client()).stop()
    assert outlet.frames == []
    assert outlet.flushes == 1


# --- through a real ControlBus ------------------------------------------------


def test_the_bus_binds_the_target_at_construction():
    outlet = FakeOutlet()
    with pytest.raises(ValueError, match="has no place for them"):
        ControlBus(_controls("wrist.rotation"), targets=[VhiTarget(outlet, client=_client())])
    assert outlet.frames == []


def test_a_bus_frame_reaches_the_wire():
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet, client=_client())])
    bus.push({"index.flexion": 0.5})
    assert outlet.last[2] == pytest.approx(0.5)


def test_nan_reaches_the_wire_as_rest_not_full_deflection():
    """`min(hi, max(lo, nan))` is `lo` — the bus substitutes rest before clipping."""
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet, client=_client())])
    bus.push({"index.flexion": float("nan")})
    assert outlet.last[2] == 0.0


def test_an_out_of_range_prediction_is_clipped_before_the_wire():
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet, client=_client())])
    bus.push(dict.fromkeys(LEGACY_POSE_DOFS, 40.0))
    assert outlet.last.min() >= -1.0


def test_smoothing_cannot_push_a_value_out_of_range():
    """The bug the ordering fixes: clip-then-smooth lets the filter overshoot out."""
    outlet = FakeOutlet()
    bus = ControlBus(
        _controls(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}}),
        targets=[VhiTarget(outlet, client=_client())],
        smoothing=GaussianFilter(sigma=1.0),
    )
    for _ in range(40):
        bus.push({"index.flexion": 1.0})
    for _ in range(40):
        bus.push({"index.flexion": 0.0})
    stacked = np.stack(outlet.frames)
    assert stacked[:, 2].min() >= 0.0
    assert stacked[:, 2].max() <= 1.0


def test_bus_stop_returns_the_hand_to_rest_and_flushes():
    """The whole safety chain: rest is delivered, then made to land, then stopped."""
    outlet = FakeOutlet()
    bus = ControlBus(_controls(), targets=[VhiTarget(outlet, client=_client())])
    bus.push(dict.fromkeys(LEGACY_POSE_DOFS, 1.0))
    assert outlet.last.max() == pytest.approx(1.0)
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
        _controls(), targets=[VhiTarget(Broken(), client=_client())], on_warn=warnings.append
    )
    bus.push({"index.flexion": 1.0})
    assert any("VhiTarget" in w for w in warnings)


def test_two_targets_receive_the_same_frame():
    """One sanitised frame, fanned out — a recorder beside the hand."""
    a, b = FakeOutlet(), FakeOutlet()
    bus = ControlBus(
        _controls(), targets=[VhiTarget(a, client=_client()), VhiTarget(b, client=_client())]
    )
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


def test_a_partial_acceptance_is_refused_outright():
    """Rendering only the accepted DOFs would hide the refused ones as held joints."""
    client = FakeClient(
        FakeReply(
            accepted=False,
            continuous_channel_order=NINE,
            verdicts=(FakeVerdict("wrist.rotation", renderable=False, message="no wrist"),),
        )
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="declined part of the control space"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_channel_order_that_disagrees_is_refused():
    """Guessing a mapping is exactly what the standard exists to stop."""
    client = FakeClient(FakeReply(continuous_channel_order=("something.else",) * 9))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="has no place for them"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_width_the_outlet_cannot_carry_is_refused():
    """The outlet's channel count is fixed at construction; a wider frame cannot fit."""
    order = (*NINE, "extra.dof")
    client = FakeClient(FakeReply(continuous_channel_order=order))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="carries only"):
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

    controls = build_controls(
        {
            "index.flexion": "continuous",
            "grip.force": {"range": [0.0, 1.0]},
            "hand.grasp": ["rest", "fist"],
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


def test_a_reply_that_does_not_state_its_encoding_is_refused():
    """The bug the field exists for: guessing a sign convention inverts every joint.

    The first end-to-end v2 run agreed on channel names while VHI still decoded legacy
    units, so a canonical +1 arrived as legacy +1 and the hand extended when it was
    told to flex. A server that will not say gets no benefit of the doubt.
    """
    client = FakeClient(
        FakeReply(continuous_channel_order=NINE, continuous_encoding=UNSPECIFIED)
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="did not say how to encode"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_legacy_negated_wire_is_negated():
    """VHI reports this while its continuous path is still the pre-v2 decoder."""
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(
            FakeReply(continuous_channel_order=NINE, continuous_encoding=NEGATED)
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
            FakeReply(continuous_channel_order=six, continuous_encoding=NEGATED)
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
            continuous_encoding=NEGATED,
            verdicts=(FakeVerdict("hand.grasp"),),
        )
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(build_controls({"hand.grasp": ["rest", "fist"]}))
    assert target.negotiated is True
    target.send({"hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_a_mixed_configuration_negotiates_both_kinds():
    """v2 lifts v1's exclusivity: a pose and a held state travel together."""
    client = FakeClient(
        FakeReply(
            continuous_channel_order=("index.flexion",),
            continuous_encoding=NEGATED,
        )
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(
        build_controls({"index.flexion": "continuous", "hand.grasp": ["rest", "fist"]})
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
                continuous_encoding=NEGATED,
            )
        ),
    )
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    target.send({"index.flexion": 1.0}, {})
    # Placed at the channel VHI named, not at position 0 of the declaration.
    assert outlet.last[2] == pytest.approx(-1.0)
    assert outlet.last[0] == 0.0


def test_a_declared_dof_with_no_negotiated_channel_is_refused():
    """The case that must still fail: a DOF with nowhere to go renders nothing."""
    client = FakeClient(
        FakeReply(
            continuous_channel_order=("index.flexion",),
            continuous_encoding=NEGATED,
        )
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="has no place for them"):
        target.bind(_controls("index.flexion", **{"wrist.rotation": "continuous"}))
    assert target.negotiated is False


def test_the_canonical_client_is_publicly_importable():
    """Nobody should have to reach into a private module to negotiate."""
    pytest.importorskip("grpc")
    import myogestic.vhi as vhi_pkg

    assert "VhiCanonicalClient" in vhi_pkg.__all__
    assert vhi_pkg.VhiCanonicalClient.__name__ == "VhiCanonicalClient"


def test_the_vhi_package_still_rejects_unknown_attributes():
    """The lazy __getattr__ must not turn every typo into an import error."""
    import myogestic.vhi as vhi_pkg

    with pytest.raises(AttributeError, match="no attribute"):
        _ = vhi_pkg.NoSuchThing


def test_importing_the_vhi_package_does_not_require_grpc():
    """A plain install calls virtual_hand().outlet() and must not pay for grpc."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; import myogestic.vhi; "
            "assert 'grpc' not in sys.modules, 'importing myogestic.vhi pulled in grpc'; "
            "print('ok')",
        ],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


# --- deferred negotiation: an app that launches its own renderer ------------------


class Deaf(FakeClient):
    """A renderer that is not up yet: silent, and never says it will not speak v2."""

    unimplemented = False

    def __init__(self) -> None:
        super().__init__(reply=None)

    def capabilities(self):
        return None


def test_an_unreachable_vhi_defers_instead_of_failing_the_configuration():
    """The app launches its own renderer, so bind necessarily runs before VHI exists.

    "No answer" cannot be read as "bad configuration" at that point — the renderer
    simply is not there yet, and the same configuration will be fine in a second.
    """
    target = VhiTarget(FakeOutlet(), client=Deaf())
    target.bind(build_controls({"g": ["rest", "fist"]}))   # must not raise
    assert target.negotiated is False


def test_a_deferred_edge_is_dropped_loudly_rather_than_raising():
    """`send` runs on the predict thread, where a raise would log every tick."""
    client = Deaf()
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(build_controls({"g": ["rest", "fist"]}))
    target.send({"g": "fist"}, {"g": "fist"})   # must not raise
    assert client.sent == []


def test_negotiate_settles_once_vhi_appears():
    client = Deaf()
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(build_controls({"g": ["rest", "fist"]}))
    assert target.negotiate() is False
    client.reply = FakeReply(continuous_channel_order=())
    assert target.negotiate() is True
    target.send({"g": "fist"}, {"g": "fist"})
    assert client.sent == [(None, {"g": "fist"})]


def test_a_renderer_that_answers_and_does_not_speak_v2_is_refused():
    """The cutover: a pre-2.0 build is a settled fact, and it is not driveable.

    It used to be driven on a table of channel numbers. That table is gone, so the
    alternative to refusing is guessing where a control lives — which is how the first
    end-to-end run made a hand extend when it was told to flex.
    """

    class PreV2(FakeClient):
        unimplemented = True

        def capabilities(self):
            return None

    target = VhiTarget(FakeOutlet(), client=PreV2(reply=None))
    with pytest.raises(ValueError, match="does not serve the v2 control contract"):
        target.bind(_controls("index.flexion"))


def test_the_refusal_says_how_to_get_a_v2_build():
    """A refusal a user cannot act on is only half a refusal."""

    class PreV2(FakeClient):
        unimplemented = True

        def capabilities(self):
            return None

    target = VhiTarget(FakeOutlet(), client=PreV2(reply=None))
    with pytest.raises(ValueError) as excinfo:
        target.bind(_controls("index.flexion"))
    message = str(excinfo.value)
    assert "install_vhi" in message
    assert "VHI_PATH" in message


def test_a_target_with_no_client_is_refused_at_bind():
    """Every channel comes from the manifest, so there is nothing to render without one."""
    with pytest.raises(ValueError, match="needs a canonical client"):
        VhiTarget(FakeOutlet()).bind(_controls("index.flexion"))


def test_negotiate_is_idempotent_when_already_settled():
    target, _ = _bound("index.flexion")
    assert target.negotiate() is True
    assert target.negotiate() is True


# --- the control-pose stream: a second stream, its own convention ----------------


def test_the_control_pose_stream_reads_its_own_order_and_encoding():
    """Two streams, two conventions. Reading the wrong pair inverts every joint."""
    outlet = FakeOutlet()
    client = FakeClient(
        FakeReply(
            continuous_channel_order=LEGACY_POSE_DOFS,
            continuous_encoding=CANONICAL,
            control_pose_stream_name="MyoGestic_ControlPose",
            control_pose_channel_order=LEGACY_POSE_DOFS,
            control_pose_encoding=NEGATED,
        )
    )
    target = VhiTarget(outlet, client=client, stream="control_pose")
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    target.send({"index.flexion": 1.0}, {})
    # NEGATED on *this* stream, even though the other stream is CANONICAL.
    assert outlet.last[2] == pytest.approx(-1.0)


def test_the_output_stream_is_unaffected_by_the_control_pose_encoding():
    outlet = FakeOutlet()
    client = FakeClient(
        FakeReply(
            continuous_channel_order=LEGACY_POSE_DOFS,
            continuous_encoding=CANONICAL,
            control_pose_channel_order=LEGACY_POSE_DOFS,
            control_pose_encoding=NEGATED,
        )
    )
    target = VhiTarget(outlet, client=client)  # default stream="output"
    target.bind(_controls("index.flexion"))
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(+1.0)


def test_declaring_the_control_pose_stream_is_opt_in():
    """Default must not declare it — that is what keeps existing producers working."""
    client = FakeClient(FakeReply(continuous_channel_order=LEGACY_POSE_DOFS))
    VhiTarget(FakeOutlet(), client=client).bind(_controls("index.flexion"))
    assert client.declared[-1][1] == "", "the output target must not declare a control pose"

    client2 = FakeClient(
        FakeReply(
            control_pose_channel_order=LEGACY_POSE_DOFS,
            control_pose_encoding=CANONICAL,
        )
    )
    VhiTarget(FakeOutlet(), client=client2, stream="control_pose").bind(
        _controls("index.flexion")
    )
    assert client2.declared[-1][1] == "canonical"


def test_a_control_pose_reply_with_no_encoding_is_refused():
    """An unnegotiated second stream must not be guessed at either."""
    client = FakeClient(
        FakeReply(
            continuous_channel_order=LEGACY_POSE_DOFS,
            continuous_encoding=CANONICAL,
            control_pose_channel_order=LEGACY_POSE_DOFS,
            control_pose_encoding=UNSPECIFIED,
        )
    )
    target = VhiTarget(FakeOutlet(), client=client, stream="control_pose")
    with pytest.raises(ValueError, match="did not say how to encode"):
        target.bind(_controls("index.flexion"))
    assert target.negotiated is False


@pytest.mark.parametrize("bad", ["", "predicted", "Output", "control-pose"])
def test_an_unknown_stream_name_is_refused_at_construction(bad):
    """A typo here would silently drive the wrong hand with the wrong convention."""
    with pytest.raises(ValueError, match="stream must be"):
        VhiTarget(FakeOutlet(), stream=bad)


def test_declare_request_carries_the_control_pose_encoding():
    pytest.importorskip("grpc")
    from myogestic.vhi._client_v2 import declare_request

    controls = build_controls({"index.flexion": "continuous"})
    assert declare_request(controls).control_pose_encoding == UNSPECIFIED
    assert declare_request(controls, control_pose="canonical").control_pose_encoding == CANONICAL
    assert (
        declare_request(controls, control_pose="legacy").control_pose_encoding
        == NEGATED
    )
    with pytest.raises(ValueError, match="control_pose must be one of"):
        declare_request(controls, control_pose="nonsense")


# --- deferral must not commit to a convention while VHI is silent -----------------


class Silent:
    """A client whose renderer never answers — 'old build' and 'not up' look the same."""

    def declare(self, controls, client_name="", control_pose=""):
        return None

    def set_control(self, continuous=None, discrete=None):
        raise AssertionError("must not be called before a handshake")


def test_a_continuous_only_config_keeps_retrying_while_vhi_is_silent():
    """The defect this pins: it used to commit to the legacy encoding forever.

    A continuous-only configuration bound while VHI was down never set `_pending`, so
    `negotiate()` reported success and never re-declared — and against a v2 build every
    joint then rendered inverted, because the target had settled on the legacy sign.
    Continuous-only is the common case, so this was the common case.
    """
    target = VhiTarget(FakeOutlet(), client=Silent())
    target.bind(_controls("index.flexion"))
    assert target.negotiated is False
    assert target.negotiate() is False, "unsettled: VHI has not answered"
    assert target.negotiated is False, "and it must not claim to have negotiated"
    assert target._pending is not None, "and it must still be willing to retry"


def test_a_silent_renderer_does_not_fail_a_v2_only_configuration():
    """Refusing at construction would reject a configuration v2 can render.

    Two shapes used to raise out of ControlBus(): a discrete DOF with no legacy_client,
    and a DOF the legacy wire has no channel for. Both are fine on v2, and "VHI has not
    answered" is not evidence that it never will.
    """
    for controls in (
        build_controls({"hand.gesture": ["rest", "fist"]}),
        _controls("wrist.rotation"),
    ):
        target = VhiTarget(FakeOutlet(), client=Silent())
        target.bind(controls)  # must not raise
        assert target._pending is not None


def test_a_silent_renderer_that_appears_later_gets_negotiated():
    """The whole point of deferring: the app launches VHI after the bus is built."""
    client = FakeClient(reply=None)
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is False

    client.reply = FakeReply(
        continuous_channel_order=LEGACY_POSE_DOFS, continuous_encoding=CANONICAL
    )
    assert target.negotiate() is True
    assert target.negotiated is True
    assert target._pending is None


def test_force_re_declares_after_a_settled_handshake():
    """A renderer restart loses VHI's side of the contract; force is the remedy."""
    client = FakeClient(
        FakeReply(continuous_channel_order=LEGACY_POSE_DOFS, continuous_encoding=CANONICAL)
    )
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    before = len(client.declared)
    assert target.negotiate() is True
    assert len(client.declared) == before, "settled means no further RPC"
    assert target.negotiate(force=True) is True
    assert len(client.declared) == before + 1, "force must re-declare"


# --- address routing: alias -> address -> channel ---------------------------------
#
# The routed path is what makes a user-owned alias drive a target-owned control. It is
# keyed on what the *target* published, so these fakes carry a manifest.

CANONICAL_ENC, LEGACY_ENC = 1, 2


def _cap(address, channel, *, lo=-1.0, hi=1.0, kind="continuous", enc=CANONICAL_ENC, states=()):
    from myogestic.controls import Capability

    return Capability(
        address=address,
        kind=kind,
        lo=lo,
        hi=hi,
        rest=0.0,
        states=tuple(states),
        rest_state=states[0] if states else "",
        channel=channel,
        encoding=enc,
    )


MANIFEST = [
    _cap("vhi.prediction.thumb", 0),
    _cap("vhi.prediction.index", 2),
    _cap("vhi.prediction.middle", 3),
    _cap("vhi.grip.force", 4, lo=0.0, hi=1.0),
    _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
]


class ManifestClient(FakeClient):
    """A client that also answers the capability manifest."""

    def __init__(self, reply=None, manifest=MANIFEST):
        super().__init__(reply)
        self.manifest = manifest

    def capabilities(self):
        return self.manifest


def _routed_target(dofs, *, manifest=MANIFEST, order=()):
    """A bound target for an alias/address configuration."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(load_control_map({"dofs": dofs}), manifest)
    outlet = FakeOutlet()
    client = ManifestClient(FakeReply(continuous_channel_order=order or ()), manifest)
    target = VhiTarget(outlet, client=client)
    target.bind(controls)
    return target, outlet, controls


def test_an_alias_lands_on_the_channel_the_target_published():
    """Not on its position in the declaration — on the channel the manifest names."""
    target, outlet, _ = _routed_target({"my_index": "vhi.prediction.index"})
    assert target.negotiated is True
    target.send({"my_index": 1.0}, {})
    assert outlet.last[2] == pytest.approx(1.0), "channel 2, per the manifest"
    assert outlet.last[0] == 0.0


def test_a_fan_out_reaches_every_listed_channel():
    target, outlet, _ = _routed_target(
        {"fist": ["vhi.prediction.index", "vhi.prediction.middle"]}
    )
    target.send({"fist": 1.0}, {})
    assert outlet.last[2] == pytest.approx(1.0)
    assert outlet.last[3] == pytest.approx(1.0)


def test_a_weight_scales_one_member_of_a_fan_out():
    target, outlet, _ = _routed_target(
        {
            "fist": [
                {"target": "vhi.prediction.thumb", "weight": 0.6},
                "vhi.prediction.index",
            ]
        }
    )
    target.send({"fist": 1.0}, {})
    assert outlet.last[0] == pytest.approx(0.6), "thumb gets 0.6x"
    assert outlet.last[2] == pytest.approx(1.0), "index gets the full value"


def test_a_weight_cannot_push_a_value_past_the_targets_range():
    """Weight applies first, then the target's own range — the gain is not an escape."""
    target, outlet, _ = _routed_target(
        {"a": [{"target": "vhi.grip.force", "weight": 1.0}]}
    )
    target.send({"a": 5.0}, {})
    assert outlet.last[4] == pytest.approx(1.0), "clamped to the declared hi"


def test_the_declared_encoding_decides_the_sign():
    """Per capability, because two streams on one target need not share a convention."""
    legacy = [_cap("vhi.prediction.index", 2, enc=LEGACY_ENC)]
    target, outlet, _ = _routed_target({"a": "vhi.prediction.index"}, manifest=legacy)
    target.send({"a": 1.0}, {})
    assert outlet.last[2] == pytest.approx(-1.0), "legacy-negated wire"


def test_two_aliases_on_one_channel_are_refused_rather_than_racing():
    """Whichever wrote last would win silently, and the other would look broken."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map(
            {"a": "x", "b": "y"}
            if False
            else {"dofs": {"a": "vhi.prediction.index", "b": "vhi.prediction.index"}}
        ),
        MANIFEST,
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(FakeReply()))
    with pytest.raises(ValueError, match="both map to"):
        target.bind(controls)


def test_an_unstreamed_capability_is_refused():
    """A control with no channel cannot be driven over the stream — say so."""
    from myogestic.controls import load_control_map, resolve

    off_stream = [_cap("vhi.prediction.index", -1)]
    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), off_stream
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(FakeReply(), off_stream))
    with pytest.raises(ValueError, match="not carried on a stream"):
        target.bind(controls)


def test_a_discrete_alias_is_not_routed_onto_the_stream():
    """Held states travel over gRPC; only continuous aliases occupy channels."""
    target, outlet, _ = _routed_target(
        {"g": {"target": "vhi.control.gesture", "debounce_s": 0.1}}
    )
    assert target._routed == (), "a discrete alias claims no channel"


def test_stop_rests_every_routed_channel():
    target, outlet, _ = _routed_target(
        {"fist": ["vhi.prediction.index", "vhi.prediction.middle"]}
    )
    target.send({"fist": 1.0}, {})
    target.stop()
    assert outlet.last.tolist() == [0.0] * LEGACY_POSE_WIDTH
    assert outlet.flushes == 1


# --- two namespaces, two streams -------------------------------------------------
#
# vhi.prediction.* is the model-driven hand on MyoGestic_Output; vhi.control.pose.* is the
# operator's hand on MyoGestic_ControlPose. They share channel numbers, so a target that
# ignored stream_name would put a value on the wrong hand.

TWO_STREAM_MANIFEST = [
    _cap("vhi.prediction.index", 2),
    _cap("vhi.control.pose.index", 2),
]


def _cap_on(address, channel, stream, **kw):
    from myogestic.controls import Capability

    return Capability(
        address=address, kind="continuous", lo=-1.0, hi=1.0, rest=0.0,
        channel=channel, encoding=CANONICAL_ENC, stream_name=stream, **kw
    )


TWO_STREAMS = [
    _cap_on("vhi.prediction.index", 2, "MyoGestic_Output"),
    _cap_on("vhi.prediction.middle", 3, "MyoGestic_Output"),
    _cap_on("vhi.control.pose.index", 2, "MyoGestic_ControlPose"),
    _cap_on("vhi.control.pose.middle", 3, "MyoGestic_ControlPose"),
]


def test_an_output_target_ignores_control_pose_addresses():
    """Channel 2 of one stream is not channel 2 of the other."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.control.pose.index"}}), TWO_STREAMS
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(FakeReply(), TWO_STREAMS))
    with pytest.raises(ValueError, match="cannot drive"):
        target.bind(controls)


def test_a_control_pose_target_ignores_prediction_addresses():
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), TWO_STREAMS
    )
    target = VhiTarget(
        FakeOutlet(), client=ManifestClient(FakeReply(), TWO_STREAMS), stream="control_pose"
    )
    with pytest.raises(ValueError, match="cannot drive"):
        target.bind(controls)


def test_the_refusal_names_both_namespaces():
    """A namespace mix-up is the likely mistake, so the error should say which is which."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.control.pose.index"}}), TWO_STREAMS
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(FakeReply(), TWO_STREAMS))
    with pytest.raises(ValueError) as excinfo:
        target.bind(controls)
    message = str(excinfo.value)
    assert "vhi.prediction" in message and "vhi.control.pose" in message


def test_each_target_routes_its_own_stream():
    """The same alias name, two targets, two hands — each lands on its own stream."""
    from myogestic.controls import load_control_map, resolve

    for stream, address in (
        ("output", "vhi.prediction.middle"),
        ("control_pose", "vhi.control.pose.middle"),
    ):
        controls = resolve(load_control_map({"dofs": {"a": address}}), TWO_STREAMS)
        outlet = FakeOutlet()
        target = VhiTarget(
            outlet, client=ManifestClient(FakeReply(), TWO_STREAMS), stream=stream
        )
        target.bind(controls)
        assert target.negotiated is True, stream
        target.send({"a": 1.0}, {})
        assert outlet.last[3] == pytest.approx(1.0), stream
