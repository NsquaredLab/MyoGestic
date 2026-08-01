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
import queue
import threading
import types

import numpy as np
import pytest

from myogestic.controls import ControlBus, ControlSet
from myogestic.outputs.filters import GaussianFilter
from myogestic.vhi._control import _QUEUE_DEPTH
from myogestic.vhi.pose import POSE_DOFS, POSE_WIDTH
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
# The manifest is duck-typed rather than a real protobuf message: VhiTarget reads it
# through `Capability`-shaped objects, which keeps these tests free of the grpc extra.


@dataclasses.dataclass
class FakeReply:
    """The channel order a fake renderer's manifest implies, in declaration order.

    Index i of ``continuous_channel_order`` becomes channel i of `FakeClient`'s
    synthesised manifest — the same wire order VHI itself assigns.
    """

    continuous_channel_order: tuple[str, ...] = ()


class FakeClient:
    """A `VhiControlClient` stand-in: answers the manifest a bind resolves against."""

    def __init__(self, reply=None) -> None:
        self.reply = reply
        self.sent: list[tuple[dict | None, dict | None]] = []
        #: How many times `capabilities()` was actually asked — `force` re-asks it.
        self.capability_fetches = 0

    def capabilities(self):
        self.capability_fetches += 1
        if self.reply is None:
            return None
        return [_cap(name, i) for i, name in enumerate(self.reply.continuous_channel_order)]

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
POSE = POSE_DOFS


def _client(order=POSE, **reply):
    """A renderer that accepts a by-name declaration in control units."""
    return FakeClient(FakeReply(continuous_channel_order=order, **reply))


def _controls(*names: str, **entries: object):
    """A pose configuration — all nine pose DOFs when no names are given."""
    dofs: dict[str, object] = dict.fromkeys(names or POSE_DOFS, "continuous")
    dofs.update(entries)
    return build_controls(dofs)


def _bound(*names: str, **entries: object) -> tuple[VhiTarget, FakeOutlet]:
    """A target bound to a renderer that names the six pose controls by address."""
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=_client())
    target.bind(_controls(*names, **entries))
    return target, outlet


# --- bind: refuse what cannot be rendered -------------------------------------


def test_bind_accepts_the_pose_dofs():
    target, outlet = _bound()
    assert len(outlet.frames) == 1, "binding puts the declared rest pose on the wire"
    target.send(dict.fromkeys(POSE_DOFS, 0.0), {})
    assert outlet.last.shape == (POSE_WIDTH,)


def test_bind_accepts_a_subset():
    """Declaring one finger is legal; the rest of the hand simply stays neutral.

    The finger's rest is deliberately not zero, or the rest frame `bind` pushes would be
    indistinguishable from one that was never written.
    """
    _, outlet = _bound(
        "index.flexion",
        **{"index.flexion": {"range": [0.0, 1.0], "rest": 0.25}},
    )
    assert outlet.last[2] == pytest.approx(0.25)
    assert np.count_nonzero(outlet.last) == 1


def test_bind_refuses_an_empty_configuration():
    """`ControlSet()` directly, because there is no parser to refuse it first."""
    with pytest.raises(ValueError, match="no DOFs at all"):
        VhiTarget(FakeOutlet()).bind(ControlSet())


def test_bind_refuses_before_anything_is_pushed():
    """Refusal happens at setup, so a rejected configuration never actuates.

    `wrist.rotation` used to be the example of something this hand cannot render. It
    renders now — all nine channels do — so the unrenderable name has to be one the
    renderer genuinely never names.
    """
    outlet = FakeOutlet()
    with pytest.raises(ValueError):
        VhiTarget(outlet, client=_client()).bind(_controls("pinky.abduction"))
    assert outlet.frames == []


# --- send: the wire frame -----------------------------------------------------


def test_send_pushes_a_full_width_float32_frame():
    target, outlet = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    assert outlet.last.shape == (POSE_WIDTH,)
    assert outlet.last.dtype == np.float32


def test_send_carries_the_wrist_channels():
    """6-8 were zeroed as dead. VHI renders the wrist on all three, so they carry."""
    target, outlet = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    assert outlet.last.tolist() == [1.0] * POSE_WIDTH


def test_send_leaves_unbound_channels_at_rest():
    """A configuration naming one finger must not disturb the rest of the hand."""
    target, outlet = _bound("index.flexion")
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == 1.0
    assert np.count_nonzero(outlet.last) == 1


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
    target.send({n: np.float32(1.0) for n in POSE_DOFS}, {})
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
    target = VhiTarget(outlet, client=ManifestClient())
    target.bind(controls)
    target.send({"a": 5.0}, {})
    assert outlet.last.max() <= 1.0


def test_send_ignores_the_changed_map():
    """No discrete DOFs can be bound, so there are never edges to deliver."""
    target, outlet = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 0.0), {"hand.grasp": "fist"})
    assert outlet.last.tolist() == [0.0] * POSE_WIDTH


def test_a_one_way_dof_never_emits_the_direction_it_excludes():
    target, outlet = _bound(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}})
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == pytest.approx(1.0)
    target.send({"index.flexion": 0.0}, {})
    assert outlet.last[2] == 0.0


def test_every_send_pushes_exactly_one_frame():
    """Latest-wins downstream: a target that pushed twice would drop a tick."""
    target, outlet = _bound()
    bound = len(outlet.frames)   # binding pushed rest; count only what `send` adds
    for _ in range(5):
        target.send(dict.fromkeys(POSE_DOFS, 0.0), {})
    assert len(outlet.frames) - bound == 5


# --- stop: rest has to actually land ------------------------------------------


def test_stop_pushes_rest_and_flushes_it():
    """Pushing alone would leave the frame unsent in a paced slot at exit."""
    target, outlet = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    target.stop()
    assert outlet.last.tolist() == [0.0] * POSE_WIDTH
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
    assert outlet.last.tolist() == [0.0] * POSE_WIDTH
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
    with pytest.raises(ValueError, match="has no place for"):
        ControlBus(_controls("pinky.abduction"), targets=[VhiTarget(outlet, client=_client())])
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
    bus.push(dict.fromkeys(POSE_DOFS, 40.0))
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
    bus.push(dict.fromkeys(POSE_DOFS, 1.0))
    assert outlet.last.max() == pytest.approx(1.0)
    bus.stop()
    assert outlet.last.tolist() == [0.0] * POSE_WIDTH
    assert outlet.flushes == 1


def test_a_broken_outlet_does_not_kill_the_predict_thread():
    """The bus absorbs a target failure; a raise here would log on every tick."""

    class Broken(FakeOutlet):
        """Intact for the rest pose `bind` pushes, closed for every frame after it."""

        def push(self, data):
            if self.frames:
                raise OSError("outlet closed")
            super().push(data)

    warnings: list[str] = []
    bus = ControlBus(
        _controls(), targets=[VhiTarget(Broken(), client=_client())], on_warn=warnings.append
    )
    bus.push({"index.flexion": 1.0})
    assert any("VhiTarget" in w for w in warnings)


def test_an_outlet_that_is_already_dead_at_bind_raises_out_of_the_bus():
    """The other side of the line above: setup failures are not absorbed.

    Settling a negotiation puts the declared rest pose on the wire, so a dead outlet is
    found while a traceback is still visible rather than warned about once per tick for
    the life of the session.
    """

    class Dead(FakeOutlet):
        def push(self, data):
            raise OSError("outlet closed")

    with pytest.raises(OSError, match="outlet closed"):
        ControlBus(_controls(), targets=[VhiTarget(Dead(), client=_client())])


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


def test_a_value_reaches_the_wire_with_the_sign_it_was_given():
    """There is one encoding now, so nothing may flip a value on the way out."""
    outlet = FakeOutlet()
    controls = _controls("index.flexion")
    target = VhiTarget(outlet, client=FakeClient(FakeReply(
        continuous_channel_order=("index.flexion",),
    )))
    target.bind(controls)
    target.send({"index.flexion": 1.0}, {})

    assert outlet.last[0] == pytest.approx(1.0), "the value was negated on the way out"

    target.send({"index.flexion": -1.0}, {})
    assert outlet.last[0] == pytest.approx(-1.0)


def test_a_channel_order_that_disagrees_is_refused():
    """Guessing a mapping is exactly what the standard exists to stop."""
    client = FakeClient(FakeReply(continuous_channel_order=("something.else",) * 9))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="has no place for"):
        target.bind(_controls(*NINE))
    assert target.negotiated is False


def test_a_width_the_outlet_cannot_carry_is_refused():
    """The outlet's channel count is fixed at construction; a wider frame cannot fit."""
    order = (*NINE, "extra.dof")
    client = FakeClient(FakeReply(continuous_channel_order=order))
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="outlet carries 9"):
        target.bind(_controls(*order))
    assert target.negotiated is False


def test_a_manifest_wider_than_the_outlet_is_fine_if_the_configuration_fits():
    """The rule is the channels declared, not the widest channel in the manifest.

    VHI publishes its whole map, so a manifest wider than the outlet is ordinary. Only
    a channel this configuration actually drives has to fit — the by-name path used to
    measure the manifest instead and refuse a frame that fits.
    """
    client = FakeClient(FakeReply(continuous_channel_order=(*NINE, "extra.dof")))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    assert target._routed[0][0] == 2


def test_discrete_edges_go_over_grpc_when_negotiated():
    """v2 lifts v1's pose/movement exclusivity, so both travel at once.

    The discrete DOF is **bound**, not merely named in the edge map. It used to be neither
    — the edge was forwarded because `send` passed on everything the bus handed it, which
    also meant forwarding another target's edges on a shared map.
    """
    client = FakeClient(FakeReply(continuous_channel_order=NINE))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls(*NINE, **{"hand.grasp": ["rest", "fist"]}))
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


def test_a_negotiated_order_shorter_than_the_wire_pads_the_tail():
    """VHI names six channels on a nine-float transport; the tail stays at rest.

    It will not name a channel it does not read — naming dead channels is how the four
    wrong pose tables came to exist — so a short order is normal, not a mismatch.
    """
    six = POSE_DOFS
    outlet = FakeOutlet()
    target = VhiTarget(
        outlet,
        client=FakeClient(FakeReply(continuous_channel_order=six)),
    )
    target.bind(_controls(*six))
    assert target.negotiated is True
    target.send({**dict.fromkeys(six, 0.0), "little.flexion": 1.0}, {})
    assert outlet.last.shape == (POSE_WIDTH,)
    assert outlet.last[5] == pytest.approx(1.0)
    assert outlet.last[6:].tolist() == [0.0, 0.0, 0.0]


def test_a_discrete_only_configuration_negotiates_and_delivers():
    """The bug tracking negotiation explicitly fixes.

    A discrete-only config has an empty continuous channel order, so inferring
    "negotiated" from that order left the target believing it was on the legacy path
    — which refuses discrete DOFs and would have rendered nothing at all.
    """
    client = FakeClient(FakeReply(continuous_channel_order=()))
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(build_controls({"hand.grasp": ["rest", "fist"]}))
    assert target.negotiated is True
    target.send({"hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_a_mixed_configuration_negotiates_both_kinds():
    """v2 lifts v1's exclusivity: a pose and a held state travel together."""
    client = FakeClient(
        FakeReply(continuous_channel_order=("index.flexion",))
    )
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=client)
    target.bind(
        build_controls({"index.flexion": "continuous", "hand.grasp": ["rest", "fist"]})
    )
    assert target.negotiated is True
    target.send({"index.flexion": 1.0, "hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert outlet.last[0] == pytest.approx(1.0)
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
            FakeReply(continuous_channel_order=POSE_DOFS)
        ),
    )
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    target.send({"index.flexion": 1.0}, {})
    # Placed at the channel VHI named, not at position 0 of the declaration.
    assert outlet.last[2] == pytest.approx(1.0)
    assert outlet.last[0] == 0.0


def test_a_declared_dof_with_no_negotiated_channel_is_refused():
    """The case that must still fail: a DOF with nowhere to go renders nothing."""
    client = FakeClient(
        FakeReply(continuous_channel_order=("index.flexion",))
    )
    target = VhiTarget(FakeOutlet(), client=client)
    with pytest.raises(ValueError, match="has no place for"):
        target.bind(_controls("index.flexion", **{"wrist.rotation": "continuous"}))
    assert target.negotiated is False


def test_the_control_client_is_publicly_importable():
    """Nobody should have to reach into a private module to negotiate."""
    pytest.importorskip("grpc")
    import myogestic.vhi as vhi_pkg

    assert "VhiControlClient" in vhi_pkg.__all__
    assert vhi_pkg.VhiControlClient.__name__ == "VhiControlClient"


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
    """A renderer that is not up yet: silent."""

    def __init__(self) -> None:
        super().__init__(reply=None)


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


def test_a_target_with_no_client_is_refused_at_bind():
    """Every channel comes from the manifest, so there is nothing to render without one."""
    with pytest.raises(ValueError, match="needs a control client"):
        VhiTarget(FakeOutlet()).bind(_controls("index.flexion"))


def test_negotiate_is_idempotent_when_already_settled():
    target, _ = _bound("index.flexion")
    assert target.negotiate() is True
    assert target.negotiate() is True


# --- the control-pose stream: a second stream, its own channel order -------------


@pytest.mark.parametrize("bad", ["", "predicted", "Output", "control-pose"])
def test_an_unknown_stream_name_is_refused_at_construction(bad):
    """A typo here would silently drive the wrong hand with the wrong convention."""
    with pytest.raises(ValueError, match="stream must be"):
        VhiTarget(FakeOutlet(), stream=bad)


def test_a_by_name_binding_reads_its_own_streams_channel():
    """The same DOF name can sit on both pose streams; each target reads only its own."""

    class TwoStreamClient:
        def capabilities(self):
            return [
                _cap("index.flexion", 2, stream="MyoGestic_Output"),
                _cap("index.flexion", 5, stream="MyoGestic_ControlPose"),
            ]

        def set_control(self, continuous=None, discrete=None):
            pass

    out = FakeOutlet()
    output = VhiTarget(out, client=TwoStreamClient())
    output.bind(_controls("index.flexion"))
    output.send({"index.flexion": 1.0}, {})
    assert out.last[2] == pytest.approx(1.0)

    pose_out = FakeOutlet()
    control_pose = VhiTarget(pose_out, client=TwoStreamClient(), stream="control_pose")
    control_pose.bind(_controls("index.flexion"))
    control_pose.send({"index.flexion": 1.0}, {})
    assert pose_out.last[5] == pytest.approx(1.0)


# --- deferral must not commit to a convention while VHI is silent -----------------


class Silent:
    """A client whose renderer never answers."""

    def capabilities(self):
        return None

    def set_control(self, continuous=None, discrete=None):
        raise AssertionError("must not be called before negotiation")


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

    client.reply = FakeReply(continuous_channel_order=POSE_DOFS)
    assert target.negotiate() is True
    assert target.negotiated is True
    assert target._pending is None


def test_force_re_fetches_the_manifest_after_a_settled_negotiation():
    """A renderer restart can hand back a different manifest; force is the remedy."""
    client = FakeClient(FakeReply(continuous_channel_order=POSE_DOFS))
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    before = client.capability_fetches
    assert target.negotiate() is True
    assert client.capability_fetches == before, "settled means no further fetch"
    assert target.negotiate(force=True) is True
    assert client.capability_fetches == before + 1, "force must re-fetch the manifest"


# --- address routing: alias -> address -> channel ---------------------------------
#
# The routed path is what makes a user-owned alias drive a target-owned control. It is
# keyed on what the *target* published, so these fakes carry a manifest.


def _cap(
    address,
    channel,
    *,
    lo=-1.0,
    hi=1.0,
    kind="continuous",
    states=(),
    stream=None,
):
    """One capability, named the way a real manifest names it.

    ``stream`` defaults to what VHI itself reports: the predicted hand's stream for a
    capability that *is* on a stream, and nothing at all for one that is not (a discrete
    control travels over gRPC and names no stream). That default matters — the target
    filters the manifest by stream name, and a fixture that left every name empty would
    only ever exercise the wildcard fallback. The wildcard is pinned on its own in
    `test_a_renderer_that_names_no_stream_is_read_anyway`.
    """
    if stream is None:
        stream = "MyoGestic_Output" if channel >= 0 else ""
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
        stream_name=stream,
    )


MANIFEST = [
    _cap("vhi.prediction.thumb", 0),
    _cap("vhi.prediction.index", 2),
    _cap("vhi.prediction.middle", 3),
    _cap("vhi.grip.force", 4, lo=0.0, hi=1.0),
    _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
]

#: The pose width this manifest implies: highest advertised channel, plus one.
MANIFEST_WIDTH = 5


def test_a_target_binds_without_declaring():
    """The manifest is the whole contract. A client that cannot Declare still binds.

    Declare's reply was accepted/verdicts plus a channel order. The order is the
    manifest sorted by channel; the verdicts were validation this target already does
    against `by_address` (for a routed alias) or the order itself (for a by-name one),
    raising its own error for an address no capability carries.

    `ManifestOnlyClient` implements *only* `capabilities`: no `declare`, no
    `set_control`. If `bind` reached for either, this would raise `AttributeError`
    before the assertion below runs.
    """
    class ManifestOnlyClient:
        """A renderer that serves GetControlManifest and nothing else."""

        def __init__(self, manifest):
            self.manifest = manifest

        def capabilities(self):
            return self.manifest

    outlet = FakeOutlet()
    # By-name, like `_client()`: address == alias, at the pose channel it names.
    manifest = [_cap(name, channel) for channel, name in enumerate(POSE)]
    target = VhiTarget(outlet, client=ManifestOnlyClient(manifest))
    target.bind(_controls("index.flexion"))
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == 1.0


class ManifestClient(FakeClient):
    """A client that answers a fixed manifest instead of synthesising one."""

    def __init__(self, manifest=MANIFEST):
        super().__init__()
        self.manifest = manifest

    def capabilities(self):
        # Counted here too, or a `force`-refetch assertion made against this client
        # would pass without the manifest ever being asked for a second time.
        self.capability_fetches += 1
        return self.manifest


def _routed_target(dofs, *, manifest=MANIFEST):
    """A bound target for an alias/address configuration."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(load_control_map({"dofs": dofs}), manifest)
    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=ManifestClient(manifest))
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
    target = VhiTarget(FakeOutlet(), client=ManifestClient())
    with pytest.raises(ValueError, match="both map to"):
        target.bind(controls)


def test_an_unstreamed_capability_is_refused():
    """A control with no channel cannot be driven over the stream — say so."""
    from myogestic.controls import load_control_map, resolve

    off_stream = [_cap("vhi.prediction.index", -1)]
    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), off_stream
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(off_stream))
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
    assert outlet.last.tolist() == [0.0] * POSE_WIDTH
    assert outlet.flushes == 1


# --- two namespaces, two streams -------------------------------------------------
#
# vhi.prediction.* is the model-driven hand on MyoGestic_Output; vhi.control.pose.* is the
# operator's hand on MyoGestic_ControlPose. They share channel numbers, so a target that
# ignored stream_name would put a value on the wrong hand.

def _cap_on(address, channel, stream, **kw):
    from myogestic.controls import Capability

    return Capability(
        address=address, kind="continuous", lo=-1.0, hi=1.0, rest=0.0,
        channel=channel, stream_name=stream, **kw
    )


TWO_STREAMS = [
    _cap_on("vhi.prediction.index", 2, "MyoGestic_Output"),
    _cap_on("vhi.prediction.middle", 3, "MyoGestic_Output"),
    _cap_on("vhi.control.pose.index", 2, "MyoGestic_ControlPose"),
    _cap_on("vhi.control.pose.middle", 3, "MyoGestic_ControlPose"),
]


def test_an_output_target_ignores_control_pose_addresses():
    """Channel 2 of one stream is not channel 2 of the other, so it routes nothing.

    Left to the target that drives that stream rather than refused: a bus may hold one
    target per hand and share a single map. `ControlBus` is what notices a control *no*
    target claimed.
    """
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.control.pose.index"}}), TWO_STREAMS
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(TWO_STREAMS))
    target.bind(controls)
    assert target.claims == frozenset(), "it claims nothing on this stream"
    assert target._routed == ()


def test_a_control_pose_target_ignores_prediction_addresses():
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), TWO_STREAMS
    )
    target = VhiTarget(
        FakeOutlet(), client=ManifestClient(TWO_STREAMS), stream="control_pose"
    )
    target.bind(controls)
    assert target.claims == frozenset()
    assert target._routed == ()


def test_the_refusal_names_both_namespaces():
    """A namespace mix-up is the likely mistake, so the error should say which is which.

    A *known* other-stream address is now another target's business; this is the refusal
    that remains, for an address no stream exports at all.
    """
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.wrist"}}),
        [*TWO_STREAMS, _cap("vhi.prediction.wrist", -1, stream="MyoGestic_Output")],
    )
    target = VhiTarget(FakeOutlet(), client=ManifestClient(TWO_STREAMS))
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
            outlet, client=ManifestClient(TWO_STREAMS), stream=stream
        )
        target.bind(controls)
        assert target.negotiated is True, stream
        target.send({"a": 1.0}, {})
        assert outlet.last[3] == pytest.approx(1.0), stream


# --- two hands at once: one map, one target per stream ----------------------------


def _two_hand_manifest():
    """A renderer that carries both pose streams, as VHI does."""
    return [
        _cap("vhi.prediction.index", 2, stream="MyoGestic_Output"),
        _cap("vhi.prediction.thumb", 0, stream="MyoGestic_Output"),
        _cap("vhi.control.pose.thumb", 0, stream="MyoGestic_ControlPose"),
        _cap("vhi.control.pose.index", 2, stream="MyoGestic_ControlPose"),
        _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
    ]


def _two_hand_controls():
    from myogestic.controls import load_control_map, resolve

    return resolve(
        load_control_map(
            {
                "dofs": {
                    "model_index": "vhi.prediction.index",
                    "operator_thumb": "vhi.control.pose.thumb",
                    "gesture": "vhi.control.gesture",
                }
            }
        ),
        _two_hand_manifest(),
    )


def test_one_map_drives_both_hands_through_two_targets():
    """The natural way to drive both: a target per stream, sharing one control space.

    Each target used to *refuse* the other's addresses, so this could not bind at all —
    the map had to be split in two. A control on another stream is now simply not this
    target's, which is a different thing from an address nothing exports.
    """
    controls = _two_hand_controls()
    manifest = _two_hand_manifest()
    predicted = VhiTarget(FakeOutlet(), client=ManifestClient(manifest))
    operator = VhiTarget(
        FakeOutlet(),
        client=ManifestClient(manifest),
        stream="control_pose",
    )
    bus = ControlBus(controls, targets=[predicted, operator], hz=32)
    assert "model_index" in predicted.claims
    assert "operator_thumb" not in predicted.claims
    assert "operator_thumb" in operator.claims
    assert "model_index" not in operator.claims
    bus.stop()


def test_each_hand_gets_only_its_own_values():
    """Both streams number channels from 0, so a leak would be silent, not loud."""
    controls = _two_hand_controls()
    manifest = _two_hand_manifest()
    left, right = FakeOutlet(), FakeOutlet()
    predicted = VhiTarget(left, client=ManifestClient(manifest))
    operator = VhiTarget(
        right, client=ManifestClient(manifest), stream="control_pose"
    )
    bus = ControlBus(controls, targets=[predicted, operator], hz=32)
    bus.push({"model_index": 1.0, "operator_thumb": -1.0})
    assert left.last[2] == pytest.approx(1.0), "the model's index, on channel 2"
    assert left.last[0] == 0.0, "the operator's thumb must not reach the model's hand"
    assert right.last[0] == pytest.approx(-1.0), "the operator's thumb, on channel 0"
    assert right.last[2] == 0.0
    bus.stop()


def test_a_held_state_is_claimed_by_whichever_target_negotiated():
    controls = _two_hand_controls()
    manifest = _two_hand_manifest()
    predicted = VhiTarget(FakeOutlet(), client=ManifestClient(manifest))
    predicted.bind(controls)
    assert "gesture" in predicted.claims


def test_a_control_no_target_claims_is_refused_by_the_bus():
    """The hazard of "not mine": with one target, the other hand's control renders nowhere.

    Skipping it silently is the failure this whole layer exists to prevent, so the bus
    checks the union of what its targets claim.
    """
    controls = _two_hand_controls()
    manifest = _two_hand_manifest()
    target = VhiTarget(FakeOutlet(), client=ManifestClient(manifest))
    with pytest.raises(ValueError, match="no target renders"):
        ControlBus(controls, targets=[target], hz=32)


def test_an_address_no_stream_exports_is_still_refused():
    """"Not mine" must not swallow a typo."""
    from myogestic.controls import load_control_map, resolve

    manifest = _two_hand_manifest()
    # The same address, but declared with no channel — as a control that exists and is not
    # streamed. "Not mine" must not swallow that.
    bad = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}),
        [cap for cap in manifest if cap.address != "vhi.prediction.index"]
        + [_cap("vhi.prediction.index", -1, stream="MyoGestic_Output")],
    )
    unstreamed = [
        cap for cap in manifest if cap.address != "vhi.prediction.index"
    ] + [_cap("vhi.prediction.index", -1, stream="MyoGestic_Output")]
    target = VhiTarget(FakeOutlet(), client=ManifestClient(unstreamed))
    with pytest.raises(ValueError, match="not carried on a stream"):
        target.bind(bad)


def test_a_target_that_does_not_report_claims_is_assumed_to_take_everything():
    """A recorder consumes the whole frame, and must not trip the unclaimed check."""

    class Recorder:
        def bind(self, controls) -> None: ...

        def send(self, values, changed) -> None: ...

        def stop(self) -> None: ...

    controls = _two_hand_controls()
    manifest = _two_hand_manifest()
    target = VhiTarget(FakeOutlet(), client=ManifestClient(manifest))
    bus = ControlBus(controls, targets=[target, Recorder()], hz=32)
    bus.stop()


# --- a target that builds its own stream ------------------------------------------
#
# `interface=` instead of an outlet: the caller gets a correctly-sized stream without
# owning one. It carries the renderer's pose layout at the renderer's own channel
# indices, because a channel *is* an address — the manifest says `vhi.prediction.index`
# is channel 2 and both ends read that from the same table. It used to be compacted and
# labelled, which bought three floats a frame and cost a routing table at each end.


class FakeInterface:
    """The slice of `InterfaceSpec` a target builds an outlet from.

    It carries the two stream *names* as well as the two builders: they are what the
    outlets it builds are published under, so they are also what the manifest has to be
    filtered by.
    """

    def __init__(
        self,
        output_stream_name="MyoGestic_Output",
        control_pose_stream_name="MyoGestic_ControlPose",
    ) -> None:
        self.output_stream_name = output_stream_name
        self.control_pose_stream_name = control_pose_stream_name
        self.built: list[tuple[str, int, tuple[str, ...]]] = []

    def outlet(self, *, n_channels=None):
        return self._build("output", n_channels)

    def control_outlet(self, *, n_channels=None):
        return self._build("control_pose", n_channels)

    def _build(self, which, n_channels):
        self.built.append((which, n_channels))
        return FakeOutlet()


def _owned(dofs, *, manifest=MANIFEST, stream="output", interface=None):
    """A bound target that built its own outlet from `dofs`."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(load_control_map({"dofs": dofs}), manifest)
    interface = FakeInterface() if interface is None else interface
    client = ManifestClient(manifest)
    target = VhiTarget(client=client, interface=interface, stream=stream)
    target.bind(controls)
    return target, interface


def test_neither_an_outlet_nor_an_interface_is_refused():
    """There has to be somewhere to write. Refused at construction, not at first send."""
    with pytest.raises(ValueError, match="either an outlet .* or an `interface="):
        VhiTarget(client=_client())


def test_the_stream_is_the_renderers_full_pose_width():
    """Two controls, but the renderer's whole layout — the undriven channels sit at rest.

    Narrower would mean the receiver had to be told how to put the frame back, which is a
    routing table on both sides to save three floats a frame.
    """
    _, interface = _owned({"a": "vhi.prediction.index", "b": "vhi.prediction.middle"})
    which, width = interface.built[0]
    assert which == "output"
    assert width == MANIFEST_WIDTH


def test_a_value_lands_on_the_renderers_own_channel():
    """Channel 2 of the manifest is channel 2 of the stream. No renumbering."""
    target, _ = _owned({"m": "vhi.prediction.middle", "i": "vhi.prediction.index"})
    target.send({"i": 1.0, "m": 0.5}, {})
    frame = target._outlet.last.tolist()
    assert frame[2] == 1.0, frame   # vhi.prediction.index
    assert frame[3] == 0.5, frame   # vhi.prediction.middle
    assert sum(1 for v in frame if v) == 2, frame


def test_a_high_manifest_channel_is_no_longer_a_width_error():
    """The check that refused this is meaningless once the target sizes its own stream."""
    manifest = [*MANIFEST, _cap("vhi.prediction.far", 40)]
    target, interface = _owned({"a": "vhi.prediction.far"}, manifest=manifest)
    assert interface.built[0][1] == 41
    target.send({"a": 1.0}, {})
    frame = target._outlet.last.tolist()
    assert frame[40] == 1.0 and sum(1 for v in frame if v) == 1, frame


def test_a_supplied_outlet_still_refuses_a_channel_it_cannot_reach():
    """The positional path is unchanged: its width is fixed and cannot be renumbered."""
    from myogestic.controls import load_control_map, resolve

    manifest = [*MANIFEST, _cap("vhi.prediction.far", 40)]
    controls = resolve(load_control_map({"dofs": {"a": "vhi.prediction.far"}}), manifest)
    target = VhiTarget(FakeOutlet(), client=ManifestClient(manifest))
    with pytest.raises(ValueError, match="carries 9"):
        target.bind(controls)


def test_the_control_pose_stream_is_built_from_the_control_outlet():
    """Not the prediction one — the two hands are different streams."""
    manifest = [_cap("vhi.control.pose.index", 2, stream="MyoGestic_ControlPose")]
    _, interface = _owned(
        {"a": "vhi.control.pose.index"}, manifest=manifest, stream="control_pose"
    )
    assert interface.built[0][0] == "control_pose"


def test_a_discrete_only_configuration_builds_no_stream_at_all():
    """Nothing continuous to carry, and a zero-channel LSL outlet is not a thing.

    It must still bind and still deliver its held states over gRPC — a target that
    raised here would make a perfectly valid gesture-only configuration unusable.
    """
    target, interface = _owned({"g": "vhi.control.gesture"})
    assert interface.built == []
    assert target.negotiated is True
    target.send({"g": "Fist"}, {"g": "Fist"})
    assert target._client.sent == [(None, {"g": "Fist"})]


def test_stop_without_a_stream_does_not_raise():
    target, _ = _owned({"g": "vhi.control.gesture"})
    target.stop()


def test_an_owned_outlet_is_stopped_but_a_supplied_one_is_not():
    """Whoever built it stops it. An application's outlet may still be in use."""

    class Stoppable(FakeOutlet):
        def __init__(self) -> None:
            super().__init__()
            self.stopped = 0

        def stop(self) -> None:
            self.stopped += 1

    supplied = Stoppable()
    target, _, _ = _routed_target({"a": "vhi.prediction.index"})
    target._outlet = supplied
    target.stop()
    assert supplied.stopped == 0

    owned, interface = _owned({"a": "vhi.prediction.index"})
    built = Stoppable()
    owned._outlet = built
    owned.stop()
    assert built.stopped == 1


# --- the stream name is configuration, not a literal ------------------------------
#
# `InterfaceSpec` carries `output_stream_name` and `control_pose_stream_name`, so a
# renamed stream is a supported configuration, not just a third-party renderer's
# problem. Filtering the manifest by a hardcoded name would leave such a target
# publishing to one name and negotiating against another — every capability dropped, and
# the map refused with nothing pointing at the cause.


def test_a_renamed_output_stream_is_negotiated_under_its_configured_name():
    manifest = [_cap("vhi.prediction.index", 2, stream="RigA_Pose")]
    target, _ = _owned(
        {"a": "vhi.prediction.index"},
        manifest=manifest,
        interface=FakeInterface(output_stream_name="RigA_Pose"),
    )
    target.send({"a": 1.0}, {})
    assert target._outlet.last[2] == pytest.approx(1.0)


def test_a_renamed_control_pose_stream_is_negotiated_under_its_configured_name():
    manifest = [_cap("vhi.control.pose.index", 2, stream="RigA_ControlPose")]
    target, _ = _owned(
        {"a": "vhi.control.pose.index"},
        manifest=manifest,
        stream="control_pose",
        interface=FakeInterface(control_pose_stream_name="RigA_ControlPose"),
    )
    target.send({"a": 1.0}, {})
    assert target._outlet.last[2] == pytest.approx(1.0)


def test_a_renamed_stream_is_honoured_on_the_by_name_path_too():
    """A configuration without routes filters by the same name a routed one does.

    It used to be a second implementation, which is how the two drifted apart; there is
    one now, and this pins that a routeless set reaches it with the right stream name.
    """
    client = ManifestClient([_cap("index.flexion", 2, stream="RigA_Pose")])

    # No interface: the outlet-only fallback name applies, nothing matches — and the
    # refusal says which stream it looked on, which is the whole diagnosis.
    with pytest.raises(ValueError, match="MyoGestic_Output"):
        VhiTarget(FakeOutlet(), client=client).bind(_controls("index.flexion"))

    # With one, the configured name is what the manifest is filtered by — and the outlet
    # it builds is sized from the manifest it filtered, exactly as a routed binding's is.
    # It used not to build one at all, so this bound, reported itself negotiated, and
    # then rendered nothing.
    interface = FakeInterface(output_stream_name="RigA_Pose")
    target = VhiTarget(client=client, interface=interface)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    assert target._routed[0][0] == 2
    assert interface.built == [("output", 3)], "no outlet means nothing renders"
    target.send({"index.flexion": 1.0}, {})
    assert target._outlet.last[2] == pytest.approx(1.0)


def test_a_renderer_that_names_no_stream_is_read_anyway():
    """An empty `stream_name` stays a wildcard: a renderer need not name its streams."""
    nameless = [_cap("vhi.prediction.index", 2, stream="")]
    routed, _, _ = _routed_target({"a": "vhi.prediction.index"}, manifest=nameless)
    routed.send({"a": 1.0}, {})
    assert routed._routed[0][0] == 2

    by_name = VhiTarget(FakeOutlet(), client=ManifestClient([_cap("index.flexion", 2, stream="")]))
    by_name.bind(_controls("index.flexion"))
    assert by_name.negotiated is True


# --- one file, several targets ----------------------------------------------------


KEY = _cap(
    "keyboard.hold.letter.w", -1, kind="discrete", states=("up", "down")
)


class TestItClaimsOnlyWhatVhiExports:
    """A map may name controls on other targets. VHI must ignore them, not refuse them.

    Since a key resolves to a *discrete* DOF, and this target used to claim every
    discrete DOF unconditionally, a mixed map made it over-claim a `keyboard.*`
    control that happened to share the file — reporting it as covered when nothing
    here actually renders it.
    """

    @staticmethod
    def _mixed():
        from myogestic.controls import load_control_map, resolve

        manifest = [
            _cap("vhi.prediction.index", 2, stream="MyoGestic_Output"),
            _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
            KEY,
        ]
        return resolve(
            load_control_map(
                {
                    "dofs": {
                        "close": "vhi.prediction.index",
                        "grip": "vhi.control.gesture",
                        "walk": "keyboard.hold.letter.w",
                    }
                }
            ),
            manifest,
        )

    @staticmethod
    def _vhi_only_client():
        # The target asks its *own* client, which knows nothing of a keyboard.
        return ManifestClient([
                _cap("vhi.prediction.index", 2, stream="MyoGestic_Output"),
                _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
            ],
        )

    def test_a_foreign_control_is_not_claimed(self):
        """`ControlBus` trusts `claims` to catch an alias nothing renders. Over-claiming
        would make a genuinely orphaned control look covered."""
        target = VhiTarget(FakeOutlet(), client=self._vhi_only_client())
        target.bind(self._mixed())
        assert "walk" not in target.claims
        assert {"close", "grip"} <= target.claims

    def test_vhis_own_discrete_control_is_still_claimed(self):
        """The filter must not over-reach: a gRPC-only VHI control is genuinely VHI's."""
        target = VhiTarget(FakeOutlet(), client=self._vhi_only_client())
        target.bind(self._mixed())
        assert "grip" in target.claims

    def test_the_vhi_controls_still_bind(self):
        target = VhiTarget(FakeOutlet(), client=self._vhi_only_client())
        target.bind(self._mixed())
        assert target.negotiated is True
        target.send({"close": 1.0, "grip": "Fist", "walk": "down"}, {})
        assert target._outlet.last[2] == pytest.approx(1.0)

    def test_a_map_with_nothing_of_ours_binds_and_claims_nothing(self):
        """A keyboard-only file in an app that also holds a VhiTarget. Not an error: the
        bus checks that *someone* claims every alias, so this is simply not our business."""
        from myogestic.controls import load_control_map, resolve

        controls = resolve(
            load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [KEY]
        )
        target = VhiTarget(FakeOutlet(), client=self._vhi_only_client())
        target.bind(controls)
        assert target.claims == frozenset()
        assert target.negotiated is True

    def test_the_bus_still_catches_a_control_nothing_renders(self):
        """The filter exists to keep this check honest, so prove it still fires."""
        from myogestic.controls import ControlBus, load_control_map, resolve

        controls = resolve(
            load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [KEY]
        )
        target = VhiTarget(FakeOutlet(), client=self._vhi_only_client())
        with pytest.raises(ValueError, match="no target renders"):
            ControlBus(controls, targets=[target], hz=32)


def test_a_foreign_edge_is_not_forwarded_to_vhi():
    """`changed` is the *bus's*, so on a shared map it carries every target's edges.

    Forwarding them made VHI log "no movement matches state 'down'" once per keystroke for
    a control that was never its to render — harmless but wrong, and it would bury a real
    rejection in noise.
    """
    from myogestic.controls import load_control_map, resolve

    manifest = [
        _cap("vhi.control.gesture", -1, kind="discrete", states=("Rest", "Fist")),
        _cap("keyboard.hold.letter.w", -1, kind="discrete", states=("up", "down")),
    ]
    controls = resolve(
        load_control_map(
            {"dofs": {"grip": "vhi.control.gesture", "walk": "keyboard.hold.letter.w"}}
        ),
        manifest,
    )
    client = ManifestClient([manifest[0]])
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(controls)
    target.send({"grip": "Fist", "walk": "down"}, {"grip": "Fist", "walk": "down"})
    assert client.sent == [(None, {"grip": "Fist"})]


def test_a_frame_of_only_foreign_edges_sends_nothing_at_all():
    """Not an empty gRPC call — no call. A round trip per keystroke for nothing."""
    from myogestic.controls import load_control_map, resolve

    key = _cap("keyboard.hold.letter.w", -1, kind="discrete", states=("up", "down"))
    vhi_cap = _cap("vhi.prediction.index", 2, stream="MyoGestic_Output")
    controls = resolve(
        load_control_map(
            {"dofs": {"close": "vhi.prediction.index", "walk": "keyboard.hold.letter.w"}}
        ),
        [vhi_cap, key],
    )
    client = ManifestClient([vhi_cap])
    target = VhiTarget(FakeOutlet(), client=client)
    target.bind(controls)
    target.send({"close": 0.5, "walk": "down"}, {"walk": "down"})
    assert client.sent == []


class TestTheControlQueueCannotGrowForever:
    """`set_control` is fed at predict_hz; `_send_loop` drains one blocking RPC at a time.

    Against a VHI that accepts the connection and does not answer, each send costs the full
    RPC timeout — measured 0.5 frames/s drained against 50/s produced. Unbounded, the queue
    grew for as long as the app ran, held every frame live, and replayed the whole stale
    backlog in order once the renderer came back.
    """

    @staticmethod
    def _client():
        """A client whose sender never runs, so the queue only fills."""
        from myogestic.vhi._control import VhiControlClient

        client = VhiControlClient.__new__(VhiControlClient)
        client._running = True
        client._dropped = 0
        client._commands = queue.Queue(maxsize=_QUEUE_DEPTH)
        return client

    def test_the_real_client_bounds_its_queue(self):
        """The bound has to be in `__init__`, not just in the drop path above."""
        from myogestic.vhi._control import VhiControlClient

        client = VhiControlClient(host="127.0.0.1", port=59999)   # nothing listening
        try:
            assert client._commands.maxsize == _QUEUE_DEPTH, "the queue is unbounded"
        finally:
            client.stop()

    def test_it_drops_the_oldest_and_keeps_the_newest(self):
        client = self._client()
        for i in range(_QUEUE_DEPTH * 3):
            client.set_control(discrete={"gesture": f"s{i}"})

        assert client._commands.qsize() == _QUEUE_DEPTH, "the queue grew past its bound"
        assert client._dropped == _QUEUE_DEPTH * 2

        frames = [client._commands.get_nowait() for _ in range(_QUEUE_DEPTH)]
        newest = frames[-1].discrete["gesture"]
        assert newest == f"s{_QUEUE_DEPTH * 3 - 1}", "the latest frame was the one dropped"

    def test_stop_keeps_the_rest_frame_and_does_not_queue_behind_the_backlog(self):
        """`ControlBus.stop` queues rest, then teardown runs — rest must survive."""
        client = self._client()
        for i in range(_QUEUE_DEPTH):
            client.set_control(discrete={"gesture": f"s{i}"})
        client.set_control(discrete={"gesture": "Rest"})   # what ControlBus.stop sends

        client._thread = threading.current_thread()        # skip the join
        client._channel = types.SimpleNamespace(close=lambda: None)
        client.stop()

        left = []
        while True:
            try:
                left.append(client._commands.get_nowait())
            except queue.Empty:
                break
        assert left[-1] is None, "the sentinel must be last, or the worker never exits"
        assert len(left) == 2, f"the sentinel sat behind {len(left) - 1} stale frames"
        assert left[0].discrete["gesture"] == "Rest", "teardown dropped the rest frame"
