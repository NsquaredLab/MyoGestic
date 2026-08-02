"""`RendererTarget` — control values in, one stream per control out, on a negotiated contract.

The target is the only place that knows how a control reaches the renderer. Since the v2
cutover it learns that by *asking*: there is no table and no fallback, so a configuration
it cannot place is refused while a human is still reading the traceback rather than
half-rendered later.

**One stream per DOF.** A control's stream is named for the control's own address and is
one channel wide, so a target driving nine controls owns nine outlets. There is no frame,
no width and no channel index anywhere in here — the manifest carries an address and the
outlet is named after it, which is why a renderer that grows a control needs no change on
this side.

These pin both halves: what `bind` refuses, and what reaches each stream per tick. Every
test runs against a recording interface and a fake client, so the whole target is verified
without a hand running. What that deliberately cannot prove is that VHI *renders* these
values as intended — that needs the binary, and the recorded pose format itself is pinned
in `test_vhi_legacy.py`.
"""

from __future__ import annotations

import queue
import threading
import types

import numpy as np
import pytest

from myogestic.controls import Capability, ControlBus, ControlSet
from myogestic.outputs.filters import GaussianFilter
from myogestic.renderer._control import _QUEUE_DEPTH
from myogestic.renderer.target import RendererTarget
from myogestic.vhi.pose import POSE_DOFS

from .conftest import build_controls


class FakeOutlet:
    """One control's sink, recording every sample that reached its stream."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.samples: list[float] = []
        self.flushes = 0
        self.stops = 0

    def push(self, data: np.ndarray) -> None:
        sample = np.asarray(data)
        assert sample.shape == (1,), f"one control, one channel — got {sample.shape}"
        assert sample.dtype == np.float32, f"the wire is float32 — got {sample.dtype}"
        self.samples.append(float(sample[0]))

    def flush(self) -> None:
        self.flushes += 1

    def stop(self) -> None:
        self.stops += 1

    @property
    def last(self) -> float:
        assert self.samples, f"nothing was ever pushed to {self.name!r}"
        return self.samples[-1]


class FakeInterface:
    """Stands in for `virtual_hand()`: hands out one outlet per address.

    The target is *told* the name — the address it resolved — so an interface has no
    stream names of its own to disagree with. `built` is every outlet ever handed out, in
    order, which is what the lifecycle tests read; `live` is the newest per address.
    """

    def __init__(self) -> None:
        self.built: list[FakeOutlet] = []
        self.live: dict[str, FakeOutlet] = {}

    def stream_outlet(self, name: str, *, n_channels: int | None = None) -> FakeOutlet:
        assert name, "an unnamed stream cannot be resolved"
        assert n_channels == 1, f"one control per stream — asked for {n_channels}"
        outlet = FakeOutlet(name)
        self.built.append(outlet)
        self.live[name] = outlet
        return outlet

    @property
    def names(self) -> list[str]:
        """Every address an outlet was built for, in build order."""
        return [outlet.name for outlet in self.built]


# --- the fake renderer every binding negotiates against -------------------------
#
# The manifest is duck-typed rather than a real protobuf message: RendererTarget reads it
# through `Capability`-shaped objects, which keeps these tests free of the grpc extra.


class FakeClient:
    """A `RendererClient` stand-in: answers the manifest a bind resolves against.

    ``addresses`` is what this renderer exports as numbers, each on a stream of its own.
    ``None`` is a renderer that has not started — silence, which is not an empty manifest.
    """

    def __init__(self, addresses: tuple[str, ...] | None = ()) -> None:
        self.addresses = addresses
        self.sent: list[tuple[dict | None, dict | None]] = []
        #: How many times `capabilities()` was actually asked — `force` re-asks it.
        self.capability_fetches = 0

    def capabilities(self):
        self.capability_fetches += 1
        if self.addresses is None:
            return None
        return [_cap(address) for address in self.addresses]

    def set_control(self, continuous=None, discrete=None):
        self.sent.append((continuous, discrete))


def _cap(address, *, lo=-1.0, hi=1.0, rest=0.0, kind="continuous", states=()):
    """One capability, carrying exactly what a manifest carries: no transport at all."""
    return Capability(
        address=address,
        kind=kind,
        lo=lo,
        hi=hi,
        rest=rest,
        states=tuple(states),
        rest_state=states[0] if states else "",
    )


def _client(order=POSE_DOFS):
    """A renderer that exports the nine pose controls under their own DOF names."""
    return FakeClient(order)


def _controls(*names: str, **entries: object):
    """A pose configuration — all nine pose DOFs when no names are given."""
    dofs: dict[str, object] = dict.fromkeys(names or POSE_DOFS, "continuous")
    dofs.update(entries)
    return build_controls(dofs)


def _bound(*names: str, **entries: object) -> tuple[RendererTarget, FakeInterface]:
    """A target bound to a renderer that names the nine pose controls by address."""
    interface = FakeInterface()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls(*names, **entries))
    return target, interface


# --- bind: refuse what cannot be rendered -------------------------------------


def test_bind_accepts_the_pose_dofs():
    _, interface = _bound()
    assert sorted(interface.names) == sorted(POSE_DOFS)
    for outlet in interface.built:
        assert outlet.samples == [0.0], "binding puts each declared rest on its stream"


def test_bind_builds_one_stream_per_control_named_for_its_address():
    """The whole shape, in one assertion: address in, stream of that name out."""
    _, interface = _bound("index.flexion", "middle.flexion")
    assert interface.names == ["index.flexion", "middle.flexion"]


def test_bind_accepts_a_subset():
    """Declaring one finger is legal; the rest of the hand simply gets no stream.

    The finger's rest is deliberately not zero, or the rest value `bind` pushes would be
    indistinguishable from one that was never written.
    """
    _, interface = _bound(
        "index.flexion",
        **{"index.flexion": {"range": [0.0, 1.0], "rest": 0.25}},
    )
    assert interface.names == ["index.flexion"]
    assert interface.live["index.flexion"].last == pytest.approx(0.25)


def test_bind_refuses_an_empty_configuration():
    """`ControlSet()` directly, because there is no parser to refuse it first."""
    with pytest.raises(ValueError, match="no DOFs at all"):
        RendererTarget(interface=FakeInterface()).bind(ControlSet())


def test_bind_refuses_before_anything_is_published():
    """Refusal happens at setup, so a rejected configuration never actuates.

    Nothing may be left on the network either: a stream published for a binding that was
    then refused would be a name nobody drives, which resolves exactly like one that works.
    """
    interface = FakeInterface()
    with pytest.raises(ValueError):
        RendererTarget(client=_client(), interface=interface).bind(_controls("pinky.abduction"))
    assert interface.built == []


def test_a_target_with_no_interface_is_refused_at_construction():
    """There has to be somewhere to publish. Refused early, not at the first send."""
    with pytest.raises(ValueError, match="needs an `interface="):
        RendererTarget(client=_client())


# --- send: one value per stream -----------------------------------------------


def test_send_pushes_one_float32_sample_per_driven_control():
    target, interface = _bound()
    before = {name: len(o.samples) for name, o in interface.live.items()}
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    for name, outlet in interface.live.items():
        assert len(outlet.samples) == before[name] + 1
        assert outlet.last == pytest.approx(1.0)


def test_send_carries_the_wrist_controls():
    """The wrist used to be zeroed as dead. VHI renders all three, so they carry."""
    target, interface = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    for axis in ("wrist.flexion", "wrist.abduction", "wrist.rotation"):
        assert interface.live[axis].last == pytest.approx(1.0)


def test_send_leaves_undriven_controls_alone_by_publishing_nothing_for_them():
    """A configuration naming one finger must not disturb the rest of the hand.

    Not "writes zero to them" — it does not publish them at all, so whatever else drives
    them keeps driving them and whatever nothing drives holds its last value. That is the
    capability the split-up transport exists for.
    """
    target, interface = _bound("index.flexion")
    target.send({"index.flexion": 1.0}, {})
    assert interface.names == ["index.flexion"]
    assert interface.live["index.flexion"].last == pytest.approx(1.0)


def test_send_ignores_a_name_it_was_not_bound_to():
    """A stray key must not reach a stream — bind is the whole authority."""
    target, interface = _bound("index.flexion")
    target.send({"index.flexion": 1.0, "thumb.flexion": 1.0}, {})
    assert "thumb.flexion" not in interface.live
    assert interface.live["index.flexion"].last == pytest.approx(1.0)


def test_send_falls_back_to_rest_for_a_missing_name():
    """`send` runs on the predict thread: a KeyError there would hold the last pose."""
    target, interface = _bound()
    target.send({"index.flexion": 1.0}, {})
    assert interface.live["index.flexion"].last == pytest.approx(1.0)
    assert interface.live["thumb.flexion"].last == 0.0


def test_send_honours_a_declared_nonzero_rest_for_a_missing_name():
    """The fallback is the DOF's own rest, not a hardcoded zero."""
    target, interface = _bound(
        "index.flexion",
        **{"thumb.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.5}},
    )
    target.send({"index.flexion": 0.0}, {})
    assert interface.live["thumb.flexion"].last == pytest.approx(0.5)


def test_send_accepts_numpy_float32_values():
    """The library's prediction dtype — `isinstance(v, float)` is False for it."""
    target, interface = _bound()
    target.send({n: np.float32(1.0) for n in POSE_DOFS}, {})
    assert all(o.last == pytest.approx(1.0) for o in interface.live.values())


def test_a_routed_binding_clamps_to_the_range_the_target_declared():
    """The bus clips first; a routed slot clamps again to what the renderer accepts.

    The two are not the same bound — a weight is applied between them — so the target's
    own range is the last word before the wire.
    """
    target, interface, _ = _routed_target({"a": "vhi.prediction.index"})
    target.send({"a": 5.0}, {})
    assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)


def test_send_ignores_the_changed_map():
    """No discrete DOFs are bound here, so there are never edges to deliver."""
    target, interface = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 0.0), {"hand.grasp": "fist"})
    assert all(o.last == 0.0 for o in interface.live.values())


def test_a_one_way_dof_never_emits_the_direction_it_excludes():
    target, interface = _bound(
        **{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}}
    )
    index = interface.live["index.flexion"]
    target.send({"index.flexion": 1.0}, {})
    assert index.last == pytest.approx(1.0)
    target.send({"index.flexion": 0.0}, {})
    assert index.last == 0.0


def test_every_send_pushes_exactly_one_sample_per_stream():
    """Latest-wins downstream: a target that pushed twice would drop a tick."""
    target, interface = _bound()
    bound = len(interface.live["index.flexion"].samples)   # bind pushed rest
    for _ in range(5):
        target.send(dict.fromkeys(POSE_DOFS, 0.0), {})
    assert len(interface.live["index.flexion"].samples) - bound == 5


# --- stop: rest has to actually land ------------------------------------------


def test_stop_rests_every_stream_flushes_it_and_takes_it_off_the_network():
    """Pushing alone would leave the value unsent in a paced slot at exit."""
    target, interface = _bound()
    target.send(dict.fromkeys(POSE_DOFS, 1.0), {})
    target.stop()
    for outlet in interface.built:
        assert outlet.last == 0.0
        assert outlet.flushes == 1
        assert outlet.stops == 1, "nothing else can release these — the target built them"


def test_stop_releases_every_outlet_even_when_one_of_them_is_dead():
    """The path most likely to meet a dead outlet, so it must not abandon the rest.

    A raise used to abort the loop: every outlet after the failure stayed published and
    stayed in `_outlets`, so a retry double-stopped the ones already released. The error
    still surfaces — teardown that swallows the reason a stream would not close is how a
    leak becomes invisible — but only once they are all down.
    """

    class Sulky(FakeOutlet):
        def flush(self):
            raise OSError("outlet closed")

    class OneBadOutlet(FakeInterface):
        def stream_outlet(self, name, *, n_channels=None):
            outlet = (Sulky if name == "middle.flexion" else FakeOutlet)(name)
            self.built.append(outlet)
            self.live[name] = outlet
            return outlet

    interface = OneBadOutlet()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls())
    with pytest.raises(OSError, match="outlet closed"):
        target.stop()
    assert all(o.stops == 1 for o in interface.built), (
        "one dead outlet must not strand the others on the network"
    )
    assert target._outlets == {} and target._routed == ()
    target.stop()   # and the retry is a no-op, not a second round of stops
    assert all(o.stops == 1 for o in interface.built)


def test_stop_rests_at_the_declared_rest_not_at_zero():
    target, interface = _bound(
        **{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.5}}
    )
    target.stop()
    assert interface.live["index.flexion"].last == pytest.approx(0.5)


def test_stop_is_idempotent_and_does_not_reuse_a_stopped_outlet():
    """The second call is a no-op, not a second rest onto streams already released."""
    target, interface = _bound()
    target.stop()
    target.stop()
    for outlet in interface.built:
        assert outlet.stops == 1
        assert outlet.flushes == 1


def test_stop_before_bind_does_not_raise():
    """Teardown runs even when setup failed — that is when it matters most."""
    interface = FakeInterface()
    RendererTarget(client=_client(), interface=interface).stop()
    assert interface.built == []


# --- the outlets are the target's, and replacing them is transactional ----------
#
# One outlet became N, so the old "just overwrite the field on a rebind" became N leaks
# per rebind. liblsl keeps a stream discoverable for as long as its StreamOutlet object
# is alive, so an abandoned one stays resolvable and shares a source_id with whatever
# replaced it — a consumer may resolve the corpse.


def test_a_rebind_keeps_the_outlet_of_an_address_it_still_drives():
    """Losing and regaining an unchanged stream is a visible stall on the hand."""
    interface = FakeInterface()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls("index.flexion", "middle.flexion"))
    kept = interface.live["index.flexion"]

    target.bind(_controls("index.flexion", "ring.flexion"))
    assert interface.live["index.flexion"] is kept, "an unchanged address was churned"
    assert kept.stops == 0


def test_a_rebind_rests_and_stops_the_outlet_of_an_address_it_has_dropped():
    interface = FakeInterface()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls("index.flexion", "middle.flexion"))
    dropped = interface.live["middle.flexion"]
    target.send({"index.flexion": 1.0, "middle.flexion": 1.0}, {})
    assert dropped.last == pytest.approx(1.0)

    target.bind(_controls("index.flexion"))
    assert dropped.last == 0.0, "a stream being taken down must be rested first"
    assert dropped.flushes == 1, "a paced push would never have left the queue"
    assert dropped.stops == 1, "and it must actually come off the network"


def test_a_rebind_builds_a_stream_for_an_address_it_has_gained():
    interface = FakeInterface()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls("index.flexion"))
    target.bind(_controls("index.flexion", "ring.flexion"))
    assert interface.names == ["index.flexion", "ring.flexion"]
    assert interface.live["ring.flexion"].samples == [0.0]


def test_a_refused_rebind_leaves_no_stream_behind():
    """Nothing drives them any more, and a live outlet keeps republishing regardless."""
    interface = FakeInterface()
    target = RendererTarget(client=_client(), interface=interface)
    target.bind(_controls("index.flexion"))
    first = interface.live["index.flexion"]

    target._client.addresses = ()   # the renderer came back exporting nothing
    with pytest.raises(ValueError, match="has no place for"):
        target.bind(_controls("index.flexion"))
    assert first.stops == 1
    assert target._outlets == {}
    assert target._routed == (), (
        "routes key into `_outlets`, so leaving them would make `send` raise per tick"
    )
    assert target.claims == frozenset(), "and `claims` would over-report what is driven"
    target.send({"index.flexion": 1.0}, {})   # must not raise


def test_a_binding_that_renders_nothing_of_ours_publishes_nothing():
    """A map entirely on another target: not an error, but not a stream either."""
    from myogestic.controls import load_control_map, resolve

    key = _cap("keyboard.hold.letter.w", kind="discrete", states=("up", "down"))
    controls = resolve(load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [key])
    interface = FakeInterface()
    target = RendererTarget(client=ManifestClient(), interface=interface)
    target.bind(controls)
    assert target.negotiated is True
    assert interface.built == []


def test_a_discrete_only_configuration_publishes_no_stream_at_all():
    """Nothing continuous to carry, so nothing to publish — but it must still bind.

    A target that raised here would make a perfectly valid gesture-only configuration
    unusable, and its held states still have to reach the renderer over gRPC.
    """
    target, interface = _owned({"g": "vhi.control.gesture"})
    assert interface.built == []
    assert target.negotiated is True
    target.send({"g": "Fist"}, {"g": "Fist"})
    # By address, not by the alias `g`: the renderer has never seen the left-hand side of
    # this map and could not resolve it against anything it advertised.
    assert target._client.sent == [(None, {"vhi.control.gesture": "Fist"})]


def test_stop_without_a_stream_does_not_raise():
    target, _ = _owned({"g": "vhi.control.gesture"})
    target.stop()


# --- through a real ControlBus ------------------------------------------------


def test_the_bus_binds_the_target_at_construction():
    interface = FakeInterface()
    with pytest.raises(ValueError, match="has no place for"):
        ControlBus(
            _controls("pinky.abduction"),
            targets=[RendererTarget(client=_client(), interface=interface)],
        )
    assert interface.built == []


def test_a_bus_frame_reaches_the_wire():
    interface = FakeInterface()
    bus = ControlBus(_controls(), targets=[RendererTarget(client=_client(), interface=interface)])
    bus.push({"index.flexion": 0.5})
    assert interface.live["index.flexion"].last == pytest.approx(0.5)


def test_nan_reaches_the_wire_as_rest_not_full_deflection():
    """`min(hi, max(lo, nan))` is `lo` — the bus substitutes rest before clipping."""
    interface = FakeInterface()
    bus = ControlBus(_controls(), targets=[RendererTarget(client=_client(), interface=interface)])
    bus.push({"index.flexion": float("nan")})
    assert interface.live["index.flexion"].last == 0.0


def test_an_out_of_range_prediction_is_clipped_before_the_wire():
    interface = FakeInterface()
    bus = ControlBus(_controls(), targets=[RendererTarget(client=_client(), interface=interface)])
    bus.push(dict.fromkeys(POSE_DOFS, 40.0))
    assert all(o.last <= 1.0 for o in interface.live.values())


def test_smoothing_cannot_push_a_value_out_of_range():
    """The bug the ordering fixes: clip-then-smooth lets the filter overshoot out."""
    interface = FakeInterface()
    bus = ControlBus(
        _controls(**{"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}}),
        targets=[RendererTarget(client=_client(), interface=interface)],
        smoothing=GaussianFilter(sigma=1.0),
    )
    for value in (1.0, 0.0):
        for _ in range(40):
            bus.push({"index.flexion": value})
    seen = interface.live["index.flexion"].samples
    assert min(seen) >= 0.0
    assert max(seen) <= 1.0


def test_bus_stop_returns_the_hand_to_rest_and_flushes():
    """The whole safety chain: rest is delivered, then made to land, then stopped."""
    interface = FakeInterface()
    bus = ControlBus(_controls(), targets=[RendererTarget(client=_client(), interface=interface)])
    bus.push(dict.fromkeys(POSE_DOFS, 1.0))
    assert interface.live["index.flexion"].last == pytest.approx(1.0)
    bus.stop()
    for outlet in interface.built:
        assert outlet.last == 0.0
        assert outlet.flushes == 1


def test_a_broken_outlet_does_not_kill_the_predict_thread():
    """The bus absorbs a target failure; a raise here would log on every tick."""

    class Broken(FakeOutlet):
        """Intact for the rest value `bind` pushes, closed for every sample after it."""

        def push(self, data):
            if self.samples:
                raise OSError("outlet closed")
            super().push(data)

    class BrokenInterface(FakeInterface):
        def stream_outlet(self, name, *, n_channels=None):
            outlet = Broken(name)
            self.built.append(outlet)
            self.live[name] = outlet
            return outlet

    warnings: list[str] = []
    bus = ControlBus(
        _controls(),
        targets=[RendererTarget(client=_client(), interface=BrokenInterface())],
        on_warn=warnings.append,
    )
    bus.push({"index.flexion": 1.0})
    assert any("RendererTarget" in w for w in warnings)


def test_an_outlet_that_is_already_dead_at_bind_raises_out_of_the_bus():
    """The other side of the line above: setup failures are not absorbed.

    Settling a negotiation puts each declared rest on the wire, so a dead outlet is found
    while a traceback is still visible rather than warned about once per tick for the life
    of the session.
    """

    class Dead(FakeOutlet):
        def push(self, data):
            raise OSError("outlet closed")

    class DeadInterface(FakeInterface):
        def stream_outlet(self, name, *, n_channels=None):
            outlet = Dead(name)
            self.built.append(outlet)
            return outlet

    interface = DeadInterface()
    with pytest.raises(OSError, match="outlet closed"):
        ControlBus(_controls(), targets=[RendererTarget(client=_client(), interface=interface)])
    assert all(o.stops == 1 for o in interface.built), (
        "a bind that died mid-publish still has to release what it had published"
    )


def test_two_targets_receive_the_same_frame():
    """One sanitised frame, fanned out — a recorder beside the hand."""
    a, b = FakeInterface(), FakeInterface()
    bus = ControlBus(
        _controls(),
        targets=[
            RendererTarget(client=_client(), interface=a),
            RendererTarget(client=_client(), interface=b),
        ],
    )
    bus.push({"middle.flexion": 0.5})
    assert a.live["middle.flexion"].last == b.live["middle.flexion"].last


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
    first = spec.stream_outlet("vhi.prediction.index", n_channels=1)
    second = spec.stream_outlet("vhi.prediction.index", n_channels=1)
    try:
        a = first._outlet.get_sinfo().source_id
        b = second._outlet.get_sinfo().source_id
        assert a, "an empty source_id is what makes the stream unrecoverable"
        assert a == b, "the id must be stable across restarts, not per-instance"
        assert "vhi.prediction.index" in a, "the stream's name has to be part of the id"
    finally:
        first.stop()
        second.stop()


def test_an_unnamed_stream_is_refused_rather_than_published():
    """An LSL stream with no name cannot be resolved, so it renders nothing, silently."""
    from myogestic.vhi import virtual_hand

    with pytest.raises(ValueError, match="unnamed stream"):
        virtual_hand().stream_outlet("", n_channels=1)


# --- negotiation ---------------------------------------------------------------


def test_a_negotiated_binding_does_not_negate():
    """The sign flip was a property of the old wire, never of the standard."""
    target, interface = _bound()
    target.send({**dict.fromkeys(POSE_DOFS, 0.0), "index.flexion": 1.0}, {})
    assert interface.live["index.flexion"].last == pytest.approx(+1.0)


def test_a_value_reaches_the_wire_with_the_sign_it_was_given():
    """There is one encoding now, so nothing may flip a value on the way out."""
    target, interface = _bound("index.flexion")
    index = interface.live["index.flexion"]
    target.send({"index.flexion": 1.0}, {})
    assert index.last == pytest.approx(1.0), "the value was negated on the way out"
    target.send({"index.flexion": -1.0}, {})
    assert index.last == pytest.approx(-1.0)


def test_an_address_vocabulary_that_disagrees_is_refused():
    """Guessing a mapping is exactly what the standard exists to stop."""
    target = RendererTarget(client=FakeClient(("something.else",)), interface=FakeInterface())
    with pytest.raises(ValueError, match="has no place for"):
        target.bind(_controls(*POSE_DOFS))
    assert target.negotiated is False


def test_a_declared_dof_the_renderer_does_not_export_is_refused():
    """The case that must still fail: a DOF with nowhere to go renders nothing."""
    target = RendererTarget(client=FakeClient(("index.flexion",)), interface=FakeInterface())
    with pytest.raises(ValueError, match="has no place for"):
        target.bind(_controls("index.flexion", **{"wrist.rotation": "continuous"}))
    assert target.negotiated is False


def test_a_subset_of_what_the_renderer_exports_is_legal():
    """VHI reports its whole vocabulary; a client may drive part of it.

    Requiring an exact set match made every subset configuration fall back, even though
    the renderer had accepted it.
    """
    target, interface = _bound("index.flexion")
    assert target.negotiated is True
    target.send({"index.flexion": 1.0}, {})
    assert interface.names == ["index.flexion"]


def test_discrete_edges_go_over_grpc_when_negotiated():
    """v2 lifts v1's pose/movement exclusivity, so both travel at once.

    The discrete DOF is **bound**, not merely named in the edge map. It used to be neither
    — the edge was forwarded because `send` passed on everything the bus handed it, which
    also meant forwarding another target's edges on a shared map.
    """
    client = _client()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(_controls(*POSE_DOFS, **{"hand.grasp": ["rest", "fist"]}))
    target.send(dict.fromkeys(POSE_DOFS, 0.0), {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_no_edge_means_no_rpc():
    """A value is re-sent every tick; a state change is not."""
    client = _client()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(_controls(*POSE_DOFS))
    for _ in range(5):
        target.send(dict.fromkeys(POSE_DOFS, 0.0), {})
    assert client.sent == []


def test_rebinding_re_negotiates_rather_than_keeping_the_old_verdict():
    """A reconnect can land on a different VHI; a stale verdict would encode wrongly."""
    client = _client()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(_controls(*POSE_DOFS))
    assert target.negotiated is True
    client.addresses = None
    target.bind(_controls())
    assert target.negotiated is False


def test_a_discrete_only_configuration_negotiates_and_delivers():
    """The bug tracking negotiation explicitly fixes.

    A discrete-only config drives no stream at all, so inferring "negotiated" from what
    was published left the target believing it had never settled — and it then refused
    every discrete DOF it was handed.
    """
    client = FakeClient(())
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(build_controls({"hand.grasp": ["rest", "fist"]}))
    assert target.negotiated is True
    target.send({"hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_a_mixed_configuration_negotiates_both_kinds():
    """v2 lifts v1's exclusivity: a number and a held state travel together."""
    client = FakeClient(("index.flexion",))
    interface = FakeInterface()
    target = RendererTarget(client=client, interface=interface)
    target.bind(
        build_controls({"index.flexion": "continuous", "hand.grasp": ["rest", "fist"]})
    )
    assert target.negotiated is True
    target.send({"index.flexion": 1.0, "hand.grasp": "fist"}, {"hand.grasp": "fist"})
    assert interface.live["index.flexion"].last == pytest.approx(1.0)
    assert client.sent == [(None, {"hand.grasp": "fist"})]


def test_the_control_client_is_publicly_importable():
    """Nobody should have to reach into a private module to negotiate."""
    pytest.importorskip("grpc")
    import myogestic.renderer as renderer_pkg

    assert "RendererClient" in renderer_pkg.__all__
    assert renderer_pkg.RendererClient.__name__ == "RendererClient"


def test_the_renderer_package_still_rejects_unknown_attributes():
    """The lazy __getattr__ must not turn every typo into an import error."""
    import myogestic.renderer as renderer_pkg

    with pytest.raises(AttributeError, match="no attribute"):
        _ = renderer_pkg.NoSuchThing


def test_importing_the_renderer_package_does_not_require_grpc():
    """A plain install calls virtual_hand().launcher() and must not pay for grpc."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; import myogestic.renderer, myogestic.vhi; "
            "assert 'grpc' not in sys.modules, 'importing the renderer package pulled in grpc'; "
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
        super().__init__(addresses=None)


def test_an_unreachable_vhi_defers_instead_of_failing_the_configuration():
    """The app launches its own renderer, so bind necessarily runs before VHI exists.

    "No answer" cannot be read as "bad configuration" at that point — the renderer
    simply is not there yet, and the same configuration will be fine in a second.
    """
    target = RendererTarget(client=Deaf(), interface=FakeInterface())
    target.bind(build_controls({"g": ["rest", "fist"]}))   # must not raise
    assert target.negotiated is False


def test_a_deferred_edge_is_dropped_loudly_rather_than_raising():
    """`send` runs on the predict thread, where a raise would log every tick."""
    client = Deaf()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(build_controls({"g": ["rest", "fist"]}))
    target.send({"g": "fist"}, {"g": "fist"})   # must not raise
    assert client.sent == []


def test_negotiate_settles_once_vhi_appears():
    client = Deaf()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(build_controls({"g": ["rest", "fist"]}))
    assert target.negotiate() is False
    client.addresses = ()
    assert target.negotiate() is True
    target.send({"g": "fist"}, {"g": "fist"})
    assert client.sent == [(None, {"g": "fist"})]


def test_a_target_with_no_client_is_refused_at_bind():
    """Every address comes from the manifest, so there is nothing to render without one."""
    with pytest.raises(ValueError, match="needs a control client"):
        RendererTarget(interface=FakeInterface()).bind(_controls("index.flexion"))


def test_negotiate_is_idempotent_when_already_settled():
    target, _ = _bound("index.flexion")
    assert target.negotiate() is True
    assert target.negotiate() is True


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
    target = RendererTarget(client=Silent(), interface=FakeInterface())
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
        target = RendererTarget(client=Silent(), interface=FakeInterface())
        target.bind(controls)  # must not raise
        assert target._pending is not None


def test_a_silent_renderer_that_appears_later_gets_negotiated():
    """The whole point of deferring: the app launches VHI after the bus is built."""
    client = FakeClient(addresses=None)
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(_controls("index.flexion"))
    assert target.negotiated is False

    client.addresses = POSE_DOFS
    assert target.negotiate() is True
    assert target.negotiated is True
    assert target._pending is None


def test_force_re_fetches_the_manifest_after_a_settled_negotiation():
    """A renderer restart can hand back a different manifest; force is the remedy."""
    client = _client()
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    before = client.capability_fetches
    assert target.negotiate() is True
    assert client.capability_fetches == before, "settled means no further fetch"
    assert target.negotiate(force=True) is True
    assert client.capability_fetches == before + 1, "force must re-fetch the manifest"


# --- address routing: alias -> address -> its own stream ---------------------------
#
# The routed path is what makes a user-owned alias drive a target-owned control. It is
# keyed on what the *target* published, so these fakes carry a manifest.


MANIFEST = [
    _cap("vhi.prediction.thumb.flexion"),
    _cap("vhi.prediction.index"),
    _cap("vhi.prediction.middle"),
    _cap("vhi.grip.force", lo=0.0, hi=1.0),
    _cap("vhi.control.gesture", kind="discrete", states=("Rest", "Fist")),
]


def test_a_target_binds_without_declaring():
    """The manifest is the whole contract. A client that cannot Declare still binds.

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

    interface = FakeInterface()
    # By-name: address == alias, exactly as `_client()` synthesises it.
    manifest = [_cap(name) for name in POSE_DOFS]
    target = RendererTarget(client=ManifestOnlyClient(manifest), interface=interface)
    target.bind(_controls("index.flexion"))
    target.send({"index.flexion": 1.0}, {})
    assert interface.live["index.flexion"].last == pytest.approx(1.0)


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
    interface = FakeInterface()
    target = RendererTarget(client=ManifestClient(manifest), interface=interface)
    target.bind(controls)
    return target, interface, controls


def _owned(dofs, **kwargs):
    """`_routed_target` without the resolved set — every target owns its streams now."""
    target, interface, _ = _routed_target(dofs, **kwargs)
    return target, interface


def test_an_alias_lands_on_the_stream_named_for_the_address_it_points_at():
    """Not on a channel of a shared frame — on a stream of that control's own name."""
    target, interface, _ = _routed_target({"my_index": "vhi.prediction.index"})
    assert target.negotiated is True
    assert interface.names == ["vhi.prediction.index"]
    target.send({"my_index": 1.0}, {})
    assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)


def test_a_fan_out_reaches_every_listed_control():
    target, interface, _ = _routed_target(
        {"fist": ["vhi.prediction.index", "vhi.prediction.middle"]}
    )
    target.send({"fist": 1.0}, {})
    assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)
    assert interface.live["vhi.prediction.middle"].last == pytest.approx(1.0)


def test_a_weight_scales_one_member_of_a_fan_out():
    target, interface, _ = _routed_target(
        {
            "fist": [
                {"target": "vhi.prediction.thumb.flexion", "weight": 0.6},
                "vhi.prediction.index",
            ]
        }
    )
    target.send({"fist": 1.0}, {})
    assert interface.live["vhi.prediction.thumb.flexion"].last == pytest.approx(0.6)
    assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)


def test_a_weight_cannot_push_a_value_past_the_targets_range():
    """Weight applies first, then the target's own range — the gain is not an escape."""
    target, interface, _ = _routed_target(
        {"a": [{"target": "vhi.grip.force", "weight": 1.0}]}
    )
    target.send({"a": 5.0}, {})
    assert interface.live["vhi.grip.force"].last == pytest.approx(1.0)


def test_two_aliases_on_one_control_are_refused_rather_than_racing():
    """Whichever wrote last would win silently, and the other would look broken."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map(
            {"dofs": {"a": "vhi.prediction.index", "b": "vhi.prediction.index"}}
        ),
        MANIFEST,
    )
    target = RendererTarget(client=ManifestClient(), interface=FakeInterface())
    with pytest.raises(ValueError, match="both map to"):
        target.bind(controls)


def test_an_address_the_renderer_does_not_export_as_a_number_is_refused():
    """A held state cannot be driven as a number — say so rather than dropping it."""
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": {"target": "vhi.control.gesture"}}}), MANIFEST
    )
    target = RendererTarget(client=ManifestClient(), interface=FakeInterface())
    target.bind(controls)
    # A discrete alias is not routed onto a stream at all; it is commanded over gRPC.
    assert target._routed == ()
    assert "a" in target.claims


def test_a_discrete_alias_is_not_routed_onto_a_stream():
    """Held states travel over gRPC; only continuous aliases get a stream."""
    target, interface, _ = _routed_target(
        {"g": {"target": "vhi.control.gesture", "debounce_s": 0.1}}
    )
    assert target._routed == (), "a discrete alias drives no stream"
    assert interface.built == []


def test_stop_rests_every_stream_it_routed():
    target, interface, _ = _routed_target(
        {"fist": ["vhi.prediction.index", "vhi.prediction.middle"]}
    )
    target.send({"fist": 1.0}, {})
    target.stop()
    for outlet in interface.built:
        assert outlet.last == 0.0
        assert outlet.flushes == 1
        assert outlet.stops == 1


# --- two hands, one target ---------------------------------------------------------
#
# vhi.prediction.* is the model-driven hand; vhi.control.pose.* is the operator's. They
# used to be two streams whose channels both numbered from zero, which is why a target
# drove exactly one of them and an application had to build one per hand. Every control
# has its own stream now, so the two hands are simply eighteen addresses and one target
# drives whichever of them a map names.


TWO_HANDS = [
    _cap("vhi.prediction.index"),
    _cap("vhi.prediction.thumb.flexion"),
    _cap("vhi.control.pose.index"),
    _cap("vhi.control.pose.thumb.flexion"),
    _cap("vhi.control.gesture", kind="discrete", states=("Rest", "Fist")),
]


def _two_hand_controls():
    from myogestic.controls import load_control_map, resolve

    return resolve(
        load_control_map(
            {
                "dofs": {
                    "model_index": "vhi.prediction.index",
                    "operator_thumb": "vhi.control.pose.thumb.flexion",
                    "gesture": "vhi.control.gesture",
                }
            }
        ),
        TWO_HANDS,
    )


def test_one_target_follows_the_map_onto_the_operators_hand():
    """No hand is chosen here — the map names one, and its addresses say which.

    This used to route *nothing*: a target defaulted to the model's hand and left every
    control-pose address to a target the application had not built, so a map like this
    rendered nowhere at all.
    """
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.control.pose.index"}}), TWO_HANDS
    )
    interface = FakeInterface()
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=interface)
    target.bind(controls)
    assert target.claims == frozenset({"a"})
    assert interface.names == ["vhi.control.pose.index"]


def test_one_target_drives_both_hands_from_one_map():
    """The whole point of dropping the split: one map, one target, all of it claimed.

    Two targets used to be mandatory here, because one outlet carrying both hands would
    have put the operator's index on the model's channel 2.
    """
    controls = _two_hand_controls()
    interface = FakeInterface()
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=interface)
    bus = ControlBus(controls, targets=[target], hz=32)   # refuses an unclaimed alias
    assert target.claims == {"model_index", "operator_thumb", "gesture"}
    bus.push({"model_index": 1.0, "operator_thumb": -1.0})
    assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)
    assert interface.live["vhi.control.pose.thumb.flexion"].last == pytest.approx(-1.0)
    bus.stop()


def test_each_hand_gets_only_its_own_values():
    """A leak between the hands would be silent, not loud — so pin it by name."""
    controls = _two_hand_controls()
    interface = FakeInterface()
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=interface)
    bus = ControlBus(controls, targets=[target], hz=32)
    bus.push({"model_index": 1.0, "operator_thumb": -1.0})
    assert interface.names == ["vhi.prediction.index", "vhi.control.pose.thumb.flexion"], (
        "only the two controls the map names may be published — a stream for the model's "
        "thumb or the operator's index would be a name nobody drives"
    )
    bus.stop()


def test_a_held_state_is_claimed_alongside_the_streams():
    controls = _two_hand_controls()
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=FakeInterface())
    target.bind(controls)
    assert "gesture" in target.claims


def test_an_address_no_renderer_exports_is_still_refused():
    """"Not mine" must not swallow a typo, and the refusal names both namespaces.

    A namespace mix-up is the likely mistake — `…index` on the wrong one moves the other
    hand and nothing reports anything — so the sentence has to say which is which rather
    than leaving the reader to work out that two hands exist at all.
    """
    from myogestic.controls import load_control_map, resolve

    controls = resolve(
        load_control_map({"dofs": {"a": "vhi.prediction.index"}}), TWO_HANDS
    )
    thinner = [cap for cap in TWO_HANDS if cap.address != "vhi.prediction.index"]
    target = RendererTarget(client=ManifestClient(thinner), interface=FakeInterface())
    with pytest.raises(ValueError, match="no target can drive") as excinfo:
        target.bind(controls)
    message = str(excinfo.value)
    assert "vhi.prediction" in message and "vhi.control.pose" in message, message


def test_a_target_that_does_not_report_claims_is_assumed_to_take_everything():
    """A recorder consumes the whole frame, and must not trip the unclaimed check."""

    class Recorder:
        def bind(self, controls) -> None: ...

        def send(self, values, changed) -> None: ...

        def stop(self) -> None: ...

    controls = _two_hand_controls()
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=FakeInterface())
    bus = ControlBus(controls, targets=[target, Recorder()], hz=32)
    bus.stop()


def test_a_control_no_target_claims_is_refused_by_the_bus():
    """Skipping a control silently is the failure this whole layer exists to prevent."""
    from myogestic.controls import load_control_map, resolve

    key = _cap("keyboard.hold.letter.w", kind="discrete", states=("up", "down"))
    controls = resolve(
        load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [key]
    )
    target = RendererTarget(client=ManifestClient(TWO_HANDS), interface=FakeInterface())
    with pytest.raises(ValueError, match="no target renders"):
        ControlBus(controls, targets=[target], hz=32)


# --- the stream name is the address, and nothing else ------------------------------
#
# Nothing on this side writes a stream name down, and there is no longer a field that
# could: a renderer that renames a control, or ships a new one, needs no configuration at
# all, because the name it publishes under is the address it advertises.


def test_a_renamed_control_needs_no_configuration_at_all():
    """The manifest says `rig.a.index`, so that is what is negotiated *and* published."""
    manifest = [_cap("rig.a.index")]
    target, interface = _owned({"a": "rig.a.index"}, manifest=manifest)
    assert interface.names == ["rig.a.index"]
    target.send({"a": 1.0}, {})
    assert interface.live["rig.a.index"].last == pytest.approx(1.0)


def test_a_renamed_control_is_honoured_on_the_by_name_path_too():
    """A configuration without routes finds its stream the same way a routed one does.

    It used to be a second implementation, which is how the two drifted apart; there is
    one now, and this pins that a routeless set reaches it with the right name.
    """
    client = ManifestClient([_cap("index.flexion")])
    interface = FakeInterface()
    target = RendererTarget(client=client, interface=interface)
    target.bind(_controls("index.flexion"))
    assert target.negotiated is True
    assert interface.names == ["index.flexion"]
    target.send({"index.flexion": 1.0}, {})
    assert interface.live["index.flexion"].last == pytest.approx(1.0)


# --- one file, several targets ----------------------------------------------------


KEY = _cap("keyboard.hold.letter.w", kind="discrete", states=("up", "down"))


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
            _cap("vhi.prediction.index"),
            _cap("vhi.control.gesture", kind="discrete", states=("Rest", "Fist")),
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
            _cap("vhi.prediction.index"),
            _cap("vhi.control.gesture", kind="discrete", states=("Rest", "Fist")),
        ])

    def test_a_foreign_control_is_not_claimed(self):
        """`ControlBus` trusts `claims` to catch an alias nothing renders. Over-claiming
        would make a genuinely orphaned control look covered."""
        target = RendererTarget(client=self._vhi_only_client(), interface=FakeInterface())
        target.bind(self._mixed())
        assert "walk" not in target.claims
        assert {"close", "grip"} <= target.claims

    def test_vhis_own_discrete_control_is_still_claimed(self):
        """The filter must not over-reach: a gRPC-only VHI control is genuinely VHI's."""
        target = RendererTarget(client=self._vhi_only_client(), interface=FakeInterface())
        target.bind(self._mixed())
        assert "grip" in target.claims

    def test_the_vhi_controls_still_bind(self):
        interface = FakeInterface()
        target = RendererTarget(client=self._vhi_only_client(), interface=interface)
        target.bind(self._mixed())
        assert target.negotiated is True
        target.send({"close": 1.0, "grip": "Fist", "walk": "down"}, {})
        assert interface.live["vhi.prediction.index"].last == pytest.approx(1.0)

    def test_a_map_with_nothing_of_ours_binds_and_claims_nothing(self):
        """A keyboard-only file in an app that also holds a RendererTarget. Not an error: the
        bus checks that *someone* claims every alias, so this is simply not our business."""
        from myogestic.controls import load_control_map, resolve

        controls = resolve(
            load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [KEY]
        )
        target = RendererTarget(client=self._vhi_only_client(), interface=FakeInterface())
        target.bind(controls)
        assert target.claims == frozenset()
        assert target.negotiated is True

    def test_the_bus_still_catches_a_control_nothing_renders(self):
        """The filter exists to keep this check honest, so prove it still fires."""
        from myogestic.controls import ControlBus, load_control_map, resolve

        controls = resolve(
            load_control_map({"dofs": {"walk": "keyboard.hold.letter.w"}}), [KEY]
        )
        target = RendererTarget(client=self._vhi_only_client(), interface=FakeInterface())
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
        _cap("vhi.control.gesture", kind="discrete", states=("Rest", "Fist")),
        _cap("keyboard.hold.letter.w", kind="discrete", states=("up", "down")),
    ]
    controls = resolve(
        load_control_map(
            {"dofs": {"grip": "vhi.control.gesture", "walk": "keyboard.hold.letter.w"}}
        ),
        manifest,
    )
    client = ManifestClient([manifest[0]])
    target = RendererTarget(client=client, interface=FakeInterface())
    target.bind(controls)
    target.send({"grip": "Fist", "walk": "down"}, {"grip": "Fist", "walk": "down"})
    assert client.sent == [(None, {"vhi.control.gesture": "Fist"})]


def test_a_frame_of_only_foreign_edges_sends_nothing_at_all():
    """Not an empty gRPC call — no call. A round trip per keystroke for nothing."""
    from myogestic.controls import load_control_map, resolve

    key = _cap("keyboard.hold.letter.w", kind="discrete", states=("up", "down"))
    vhi_cap = _cap("vhi.prediction.index")
    controls = resolve(
        load_control_map(
            {"dofs": {"close": "vhi.prediction.index", "walk": "keyboard.hold.letter.w"}}
        ),
        [vhi_cap, key],
    )
    client = ManifestClient([vhi_cap])
    target = RendererTarget(client=client, interface=FakeInterface())
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
        from myogestic.renderer._control import RendererClient

        client = RendererClient.__new__(RendererClient)
        client._running = True
        client._dropped = 0
        client._commands = queue.Queue(maxsize=_QUEUE_DEPTH)
        return client

    def test_the_real_client_bounds_its_queue(self):
        """The bound has to be in `__init__`, not just in the drop path above."""
        from myogestic.renderer._control import RendererClient

        client = RendererClient(host="127.0.0.1", port=59999)   # nothing listening
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
