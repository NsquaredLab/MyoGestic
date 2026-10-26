"""`DevicePicker`: option resolution, the shipped device entries, and source swapping.

Headless ImGui frames cover chip interactions, action states, recording guards,
and responsive layout. Source tests cover configuration defaults, connection
lifecycle, and closing the source being replaced.
"""

import itertools
import threading
import time

import pytest

from myogestic.sources.otb import _constants as C
from myogestic.stream import Stream, StreamInfo
from myogestic.widgets.signals.device_picker import (
    DEFAULT_DEVICES,
    OTB_DEVICES,
    SYNTHETIC_DEVICE,
    DeviceOption,
    DeviceParam,
    DevicePicker,
    DeviceSpec,
    _chosen_kwargs,
    _default_choices,
    _swap_source,
)

_IDS = [d.label for d in DEFAULT_DEVICES]


class _FakeSource:
    """Minimal `Source` whose disconnects are observable."""

    def __init__(self, n_channels: int = 4) -> None:
        self.n_channels = n_channels
        self.disconnects = 0

    def connect(self) -> StreamInfo:
        return StreamInfo(n_channels=self.n_channels, fs=100.0)

    def read(self):
        return None, None

    def disconnect(self) -> None:
        self.disconnects += 1


class _UnreachableSource(_FakeSource):
    """A device that is configured fine but is not actually there."""

    def connect(self) -> StreamInfo:
        raise RuntimeError("no device answered")


class _FakeCtx:
    """Only the two attributes the picker touches on a real `Context`."""

    state = "idle"

    def __init__(self, streams) -> None:
        self.streams = streams
        self.messages: list[str] = []

    def log(self, message: str) -> None:
        self.messages.append(message)


def _settled(picker: DevicePicker, timeout: float = 5.0) -> None:
    """Block until the off-thread connect has finished.

    Safe against a race: ``_connect`` sets the flag synchronously before it
    starts the thread.
    """
    deadline = time.monotonic() + timeout
    while picker._connecting and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not picker._connecting, "connect thread never finished"


# --- the shipped device entries ---------------------------------------------
@pytest.mark.parametrize("dev", DEFAULT_DEVICES, ids=_IDS)
def test_a_device_builds_its_source_from_the_default_choices(dev):
    assert dev.factory(**_chosen_kwargs(dev, _default_choices(dev))) is not None


@pytest.mark.parametrize("dev", DEFAULT_DEVICES, ids=_IDS)
def test_every_offered_option_value_builds_a_source(dev):
    """No combination reachable from the dropdowns can raise."""
    keys = [o.kwarg for o in dev.options]
    for combo in itertools.product(*(range(len(o.choices)) for o in dev.options)):
        choices = dict(zip(keys, combo, strict=True))
        dev.factory(**_chosen_kwargs(dev, choices))


@pytest.mark.parametrize("dev", DEFAULT_DEVICES, ids=_IDS)
def test_untouched_dropdowns_reproduce_the_factorys_own_defaults(dev):
    """The panel opens on exactly what ``factory()`` would do unaided.

    This is what lets the device entries carry no defaults of their own — the
    constructors stay the single source of truth.
    """
    seeded = dev.factory(**_chosen_kwargs(dev, _default_choices(dev)))
    assert seeded.__dict__ == dev.factory().__dict__


def test_the_synthetic_device_actually_streams(tmp_path):
    """The point of shipping it: a working app with no hardware attached.

    Connects for real through the same `Stream` path an amplifier uses, so this
    fails if the picker's entry and the source's signature ever drift apart.
    """
    from myogestic.widgets.signals.device_picker import _chosen_kwargs, _default_choices

    dev = SYNTHETIC_DEVICE
    choices = dict(_default_choices(dev))
    choices["n_channels"] = 3  # "64"
    source = dev.factory(**_chosen_kwargs(dev, choices))

    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()
    assert stream.info is not None
    assert stream.info.n_channels == 64

    data, timestamps = source.read()
    assert data is not None and timestamps is not None
    assert data.shape[1] == 64
    assert len(timestamps) == data.shape[0]
    # Timestamps must be monotonic or the viewer's time axis walks backwards.
    assert (timestamps[1:] > timestamps[:-1]).all()


def test_the_synthetic_device_says_in_its_label_that_it_is_not_real():
    """A take recorded from it is not data, and the dropdown has to say so."""
    label = SYNTHETIC_DEVICE.label.lower()
    assert "synthetic" in label and "no hardware" in label
    assert SYNTHETIC_DEVICE in DEFAULT_DEVICES


def test_shipped_device_labels_are_unique():
    """They are dropdown entries: two identical rows would be unpickable."""
    labels = [d.label for d in DEFAULT_DEVICES]
    assert len(set(labels)) == len(labels)


@pytest.mark.parametrize(
    ("prefix", "constant"),
    [
        ("Quattrocento", C.QUATTRO_BIO_BY_MODE),
        ("Sessantaquattro", C.SESSANTAQUATTRO_BIO_BY_NCH),
    ],
)
def test_channel_labels_match_the_geometry_they_select(prefix, constant):
    """A dropdown reading "192 ch" must actually configure 192 channels."""
    dev = next(d for d in OTB_DEVICES if d.label.startswith(prefix))
    opt = next(o for o in dev.options if o.kwarg == "nch_mode")
    for shown, nch_mode in opt.choices.items():
        assert constant[nch_mode] == int(shown), shown


def test_every_otb_device_can_be_asked_for_its_accessory_channels():
    """A force transducer is wired to an AUX input, and the UI is the only way in.

    An OTB entry without this row hides its accessory block completely — the
    source supports it, but nothing in the app can ask for it.
    """
    for dev in OTB_DEVICES:
        assert any(o.kwarg == "include_aux" for o in dev.options), dev.label


def test_including_aux_widens_the_source_beyond_the_biosignal_channels():
    """Selecting the aux choice must reach the wire, not just set a flag.

    Quattrocento resolves its output width in ``__init__``, so this is
    observable without hardware: aux off is the bio block, aux on is the whole
    wire — bio plus 16 AUX IN plus 8 accessory.
    """
    dev = next(d for d in OTB_DEVICES if d.label.startswith("Quattrocento"))
    opt = next(o for o in dev.options if o.kwarg == "include_aux")
    choices = dict(_default_choices(dev))
    values = list(opt.choices.values())
    nch_mode = _chosen_kwargs(dev, choices)["nch_mode"]

    widths = {}
    for value in values:
        choices["include_aux"] = values.index(value)
        widths[value] = len(dev.factory(**_chosen_kwargs(dev, choices))._select)

    assert widths[False] == C.QUATTRO_BIO_BY_MODE[nch_mode]
    assert widths[True] == C.QUATTRO_NCH_BY_MODE[nch_mode]
    assert widths[True] > widths[False]


def test_a_bool_option_does_not_match_an_int_default():
    """`True == 1`, so option lookup compares types before values."""

    def factory(flag: bool = False, level: int = 1):
        return (flag, level)

    dev = DeviceSpec("t", factory, (
        DeviceOption("flag", "Flag", {"on": True, "off": False}),
        DeviceOption("level", "Level", {"a": 0, "b": 1}),
    ))
    chosen = _chosen_kwargs(dev, _default_choices(dev))
    assert chosen == {"flag": False, "level": 1}


# --- swapping the source under a live stream --------------------------------
def test_swapping_a_source_closes_the_one_it_replaces():
    """The regression test for a leaked listening socket.

    `Stream.reconnect` only touches the *new* source, so without an explicit
    disconnect the old Muovi/Sessantaquattro server socket stays bound and the
    next Connect to that device cannot re-bind its fixed port.
    """
    first, second = _FakeSource(4), _FakeSource(8)
    stream = Stream("emg", source=first, window_ms=100)
    assert stream.reconnect()

    before = first.disconnects
    assert _swap_source(stream, second)

    assert first.disconnects == before + 1
    assert stream._source is second
    assert stream.info is not None
    assert stream.info.n_channels == 8


def test_a_failed_swap_reports_the_error_and_leaves_the_stream_detached():
    good, bad = _FakeSource(4), _UnreachableSource()
    stream = Stream("emg", source=good, window_ms=100)
    assert stream.reconnect()

    assert not _swap_source(stream, bad)
    assert "no device answered" in stream.last_error
    assert stream._connected is False


def test_reattaching_the_same_source_does_not_disconnect_it_first():
    """Reconnecting the current device is a retry, not a swap."""
    source = _FakeSource(4)
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()

    before = source.disconnects
    assert _swap_source(stream, source)
    # Exactly one, from `Stream.reconnect`'s own disconnect+connect — not two.
    assert source.disconnects == before + 1


# --- pressing Connect -------------------------------------------------------
def test_connect_builds_the_selected_configuration_and_attaches_it():
    """End to end: the dropdown choice is what the stream ends up running."""
    dev = DeviceSpec("fake", _FakeSource, (DeviceOption("n_channels", "Channels", {"4": 4, "9": 9}),))
    stream = Stream("emg", source=_FakeSource(1), window_ms=100)
    picker = DevicePicker("emg", devices=(dev,))
    picker._choices[0]["n_channels"] = 1  # the user picks "9"

    ctx = _FakeCtx({"emg": stream})
    picker._connect(ctx, stream, dev)
    _settled(picker)

    assert stream.info is not None
    assert stream.info.n_channels == 9


def test_an_unbuildable_configuration_is_logged_and_leaves_the_stream_alone():
    """The source is built *before* the swap, so a bad combination costs nothing.

    Otherwise a `ValueError` from a constructor would leave the stream holding a
    device that had already been disconnected.
    """

    def refuses(**kwargs):
        raise ValueError("nch_mode must be 0..3")

    original = _FakeSource(4)
    stream = Stream("emg", source=original, window_ms=100)
    assert stream.reconnect()
    picker = DevicePicker("emg", devices=(DeviceSpec("bad", refuses),))

    ctx = _FakeCtx({"emg": stream})
    picker._connect(ctx, stream, picker._devices[0])
    _settled(picker)

    assert stream._source is original
    assert any("nch_mode must be 0..3" in m for m in ctx.messages)


# --- live parameters ---------------------------------------------------------
class _TunableSource(_FakeSource):
    """A source with a knob that can be turned while it streams."""

    def __init__(self, n_channels: int = 4) -> None:
        super().__init__(n_channels)
        self.noise = 0.12


def _live_device() -> DeviceSpec:
    return DeviceSpec("tunable", _TunableSource, live=(DeviceParam("noise", "Noise", 0.0, 1.0),))


def test_a_live_slider_retunes_the_running_source_without_reconnecting():
    """The whole point: no `reconnect`, so the plot and any recording survive."""
    dev = _live_device()
    stream = Stream("emg", source=_TunableSource(), window_ms=100)
    picker = DevicePicker("emg", devices=(dev,))
    ctx = _FakeCtx({"emg": stream})
    picker._connect(ctx, stream, dev)
    _settled(picker)

    source = stream._source
    epoch, disconnects = stream.epoch, source.disconnects

    source.noise = 0.5  # what the slider writes, via setattr on the param name

    assert source.noise == 0.5
    assert stream.epoch == epoch, "buffers were reallocated — the plot would reset"
    assert source.disconnects == disconnects, "the source was dropped"


def test_live_sliders_are_hidden_until_their_own_device_is_the_connected_one():
    """They write to `stream._source`; showing them early retunes another device."""
    dev = _live_device()
    picker = DevicePicker("emg", devices=(dev, DeviceSpec("other", _FakeSource)))

    assert picker._connected_from is None  # nothing attached: nothing to tune

    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    ctx = _FakeCtx({"emg": stream})
    picker._connect(ctx, stream, dev)
    _settled(picker)
    assert picker._connected_from == 0

    picker._selected = 1  # user browses to another device without connecting
    assert picker._selected != picker._connected_from


def test_a_failed_connect_leaves_nothing_marked_as_attached():
    def refuses(**kwargs):
        raise ValueError("nope")

    picker = DevicePicker("emg", devices=(DeviceSpec("bad", refuses),))
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    ctx = _FakeCtx({"emg": stream})
    picker._connect(ctx, stream, picker._devices[0])
    _settled(picker)

    assert picker._connected_from is None


def test_the_synthetic_devices_live_knobs_exist_on_the_source_it_builds():
    """A DeviceParam naming an attribute the source lacks is a silent dead slider."""
    source = SYNTHETIC_DEVICE.factory()
    for param in SYNTHETIC_DEVICE.live:
        assert isinstance(getattr(source, param.attr), int | float), param.attr


def test_the_synthetic_source_honours_a_live_noise_change():
    """Turning noise off makes the signal deterministic — measurable, not asserted by faith."""
    import numpy as np

    from myogestic.sources import SyntheticSource

    source = SyntheticSource(n_channels=2, fs=500.0, noise=0.0, hum=0.0)
    source.connect()
    quiet, _ = source.read()

    source.noise = 5.0
    loud, _ = source.read()

    assert np.std(loud) > np.std(quiet) * 3


# --- aborting a connect ------------------------------------------------------
class _StalledSource(_FakeSource):
    """A device that never answers, the way an OTB probe left switched off does.

    ``connect`` parks until something closes the socket — which is exactly what
    `DevicePicker._abort` does, and why it works at all.
    """

    def __init__(self) -> None:
        super().__init__(4)
        self.entered = threading.Event()
        self._released = threading.Event()

    def connect(self) -> StreamInfo:
        self.entered.set()
        self._released.wait(timeout=5.0)
        raise OSError("accept: socket closed")

    def disconnect(self) -> None:
        super().disconnect()
        # Only a socket already parked in accept() is unblocked by closing it.
        # `Stream.reconnect` disconnects before it connects, so releasing
        # unconditionally would let the stall finish before it ever started.
        if self.entered.is_set():
            self._released.set()


def test_aborting_a_stalled_connect_frees_the_ui_at_once():
    """The point: a 30 s `accept_timeout` must not hold the panel hostage."""
    stalled = _StalledSource()
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    picker = DevicePicker("emg", devices=(DeviceSpec("stalled", lambda: stalled),))
    ctx = _FakeCtx({"emg": stream})

    picker._connect(ctx, stream, picker._devices[0])
    assert stalled.entered.wait(timeout=2.0), "worker never reached connect()"
    assert picker._connecting is True

    picker._abort(ctx, stream)

    assert picker._connecting is False, "the button would still be an Abort"
    assert stalled.disconnects >= 1, "the socket was never closed, so accept still blocks"
    _settled(picker)


def test_an_aborted_connect_is_not_reported_as_a_failure():
    """Giving up is a decision, not a device fault — the panel must not go red."""
    stalled = _StalledSource()
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    picker = DevicePicker("emg", devices=(DeviceSpec("stalled", lambda: stalled),))
    ctx = _FakeCtx({"emg": stream})

    picker._connect(ctx, stream, picker._devices[0])
    assert stalled.entered.wait(timeout=2.0)
    picker._abort(ctx, stream)

    deadline = time.monotonic() + 3.0
    while stream.last_error and time.monotonic() < deadline:
        time.sleep(0.01)

    assert stream.last_error == "", f"left an error behind: {stream.last_error!r}"
    assert picker._connected_from is None
    assert not any("connect failed" in m for m in ctx.messages)
    assert any("aborted" in m for m in ctx.messages)


def test_a_second_attempt_while_one_is_in_flight_is_ignored():
    """Not merely refused — never started.

    `Stream.reconnect` would refuse it anyway, but only after `_swap_source` had
    already put the new source on the stream. The first attempt would then be
    connecting one object while the stream pointed at another, and neither would
    end up attached.
    """
    stalled = _StalledSource()
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    picker = DevicePicker("emg", devices=(DeviceSpec("stalled", lambda: stalled),))
    ctx = _FakeCtx({"emg": stream})

    picker._connect(ctx, stream, picker._devices[0])
    assert stalled.entered.wait(timeout=2.0)
    generation = picker._connect_gen

    picker._connect(ctx, stream, picker._devices[0])  # the ignored one

    assert picker._connect_gen == generation, "a second attempt was started"
    assert sum("connecting to" in m for m in ctx.messages) == 1
    picker._abort(ctx, stream)
    _settled(picker)


# --- disconnecting -----------------------------------------------------------
def test_disconnecting_detaches_the_stream_without_stopping_its_loop():
    """`Stream.disconnect`, not `stop`.

    `App.run` starts the acquire thread once and owns it; stopping it here would
    leave Connect unable to bring the stream back.
    """
    source = _FakeSource(4)
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()
    stream._running = True  # as `App.run` leaves it

    picker = DevicePicker("emg", devices=(DeviceSpec("d", _FakeSource),))
    ctx = _FakeCtx({"emg": stream})
    picker._connected_from = 0

    picker._disconnect(ctx, stream)

    assert stream._connected is False
    assert stream.info is None, "a deliberate detach must not look like a lost connection"
    assert stream.status == "disconnected"
    assert stream._running is True, "the acquire loop was stopped and cannot be restarted"
    assert source.disconnects >= 1
    assert picker._connected_from is None, "live sliders would still target a closed device"
    assert any("disconnected" in m for m in ctx.messages)


def test_a_disconnected_stream_can_be_connected_again():
    source = _FakeSource(4)
    stream = Stream("emg", source=source, window_ms=100)
    assert stream.reconnect()
    stream.disconnect()

    assert stream.reconnect() is True
    assert stream.info is not None
    assert stream.info.n_channels == 4


def test_disconnect_leaves_no_error_behind():
    """Closing a device on purpose is not a fault; the panel must not go red."""
    stream = Stream("emg", source=_UnreachableSource(), window_ms=100)
    assert stream.reconnect() is False
    assert stream.last_error

    stream.disconnect()

    assert stream.last_error == ""


# --- one picker, several streams ---------------------------------------------
def _two_stream_ctx() -> tuple[object, Stream, Stream]:
    emg = Stream("emg", source=_FakeSource(4), window_ms=100)
    force = Stream("force", source=_FakeSource(1), window_ms=100)
    return _FakeCtx({"emg": emg, "force": force}), emg, force


def test_each_stream_keeps_its_own_device_choice():
    """A `selectable` picker serves several streams, and the device is a fact
    about the stream — not about the panel.

    Held once for the widget, switching streams showed the previous one's
    device: a dropdown naming something the new stream was never attached to.
    """
    picker = DevicePicker(
        "emg",
        devices=(DeviceSpec("a", _FakeSource), DeviceSpec("b", _FakeSource)),
        selectable=True,
    )
    picker._selected = 1  # emg is set to device "b"

    picker._stream_name = "force"

    assert picker._selected == 0, "force inherited emg's device"
    picker._stream_name = "emg"
    assert picker._selected == 1, "emg lost its own choice"


def test_connecting_one_stream_does_not_mark_another_as_connected():
    """The report that started this: connecting emg appeared to connect force."""
    picker = DevicePicker(
        "emg", devices=(DeviceSpec("d", _FakeSource),), selectable=True
    )
    ctx, emg, _ = _two_stream_ctx()

    picker._connect(ctx, emg, picker._devices[0])
    _settled(picker)
    assert picker._connected_from == 0

    picker._stream_name = "force"
    assert picker._connected_from is None, "force reported as attached to emg's device"
    assert picker._connecting is False


def test_option_choices_do_not_leak_between_streams():
    """Two streams may want different geometries of the same device model."""
    dev = DeviceSpec("d", _FakeSource, (DeviceOption("n_channels", "Channels", {"4": 4, "9": 9}),))
    picker = DevicePicker("emg", devices=(dev,), selectable=True)

    picker._choices[0]["n_channels"] = 1  # emg picks "9"
    picker._stream_name = "force"

    assert picker._choices[0]["n_channels"] == 0, "force inherited emg's option"


def test_a_scan_result_belongs_to_the_stream_it_was_run_for():
    picker = DevicePicker("emg", devices=(DeviceSpec("d", _FakeSource, scan=True),), selectable=True)
    picker._targets = [{"name": "outlet-A", "info": ""}]

    picker._stream_name = "force"

    assert picker._targets == [], "another stream's scan results carried over"


def test_a_scan_in_flight_delivers_to_the_stream_it_was_started_for():
    """The worker writes results after the operator may already have moved the panel.

    Going through the `_targets` / `_scanned_for` properties resolves the stream at
    *write* time, on the worker, so the outlets land wherever the panel happens to be
    showing. The scanned stream is then left with an empty list and `scanned_for`
    already set — "nothing found", and permanently, because the auto-rescan guard in
    `_scan_ui` only fires while `scanned_for` disagrees with the selection.
    """
    released = threading.Event()

    class _SlowDiscovery(_FakeSource):
        def discover(self):
            assert released.wait(timeout=5.0)
            return [{"name": "outlet-for-emg", "info": "8 ch"}]

    picker = DevicePicker(
        "emg", devices=(DeviceSpec("d", _SlowDiscovery, scan=True),), selectable=True
    )
    picker._start_scan(picker._devices[0])
    picker._select_stream("force")
    released.set()
    deadline = time.monotonic() + 5.0
    while picker._scanning and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not picker._scanning, "scan thread never finished"

    assert picker._targets == [], "force was handed a scan it never ran"
    assert picker._scanned_for is None, "force would now suppress its own auto-scan"
    picker._select_stream("emg")
    assert picker._targets == [{"name": "outlet-for-emg", "info": "8 ch"}], "emg lost its scan"
    assert picker._scanned_for == 0


def test_an_attempt_in_flight_stays_with_its_own_stream():
    """Switching the panel mid-connect must not compare generations across streams.

    Going through the property would let a superseded attempt on one stream
    report as current against another's generation counter.
    """
    stalled = _StalledSource()
    ctx, emg, _ = _two_stream_ctx()
    picker = DevicePicker(
        "emg", devices=(DeviceSpec("stalled", lambda: stalled),), selectable=True
    )

    picker._connect(ctx, emg, picker._devices[0])
    assert stalled.entered.wait(timeout=2.0)
    assert picker._connecting is True

    picker._stream_name = "force"
    assert picker._connecting is False, "force showed emg's attempt as its own"

    picker._stream_name = "emg"
    assert picker._connecting is True, "emg lost track of its own attempt"
    picker._abort(ctx, emg)
    _settled(picker)


def test_a_stream_owned_by_another_widget_is_not_offered():
    """A `TrackingTask`'s target is its own output, not a device stream.

    Offered here, one Connect replaces the `TargetSource` the task is driving —
    leaving the task writing to a source attached to nothing, and the recording
    holding a device's data under the name "target".
    """
    picker = DevicePicker(
        "emg", devices=(DeviceSpec("d", _FakeSource),), selectable=True, exclude=("target",)
    )
    ctx = _FakeCtx(
        {
            "emg": Stream("emg", source=_FakeSource(), window_ms=100),
            "target": Stream("target", source=_FakeSource(), window_ms=100),
            "force": Stream("force", source=_FakeSource(), window_ms=100),
        }
    )

    offered = sorted(n for n in ctx.streams if n not in picker._excluded)

    assert offered == ["emg", "force"]
    assert "target" not in offered


def test_a_stream_added_at_runtime_is_offered_unless_it_was_named():
    """`exclude` is a set of names, not a snapshot — new streams still appear."""
    picker = DevicePicker(
        "emg", devices=(DeviceSpec("d", _FakeSource),), selectable=True, exclude=("target",)
    )
    ctx = _FakeCtx({"emg": Stream("emg", source=_FakeSource(), window_ms=100)})
    ctx.streams["aux"] = Stream("aux", source=_FakeSource(), window_ms=100)

    offered = sorted(n for n in ctx.streams if n not in picker._excluded)
    assert offered == ["aux", "emg"]


# --- switching the panel between streams, through the real transition ---------
# The isolation tests above assign `_stream_name` directly, which exercises the state
# container but never the switch itself. These go through `_select_stream`, which is
# what the Stream dropdown calls.
def test_returning_to_a_stream_keeps_it_marked_as_attached():
    """The report: configure the force source, come back to emg, and emg's live
    sliders are gone until it is connected again.

    `_select_stream` rebinds which `_StreamState` the properties address, so clearing
    `_connected_from` after the rebind cleared it for the stream being *switched to*.
    Leaving emg wiped emg on the way back in.
    """
    ctx, emg, _force = _two_stream_ctx()
    picker = DevicePicker("emg", devices=(DeviceSpec("d", _FakeSource),), selectable=True)

    picker._connect(ctx, emg, picker._devices[0])
    _settled(picker)
    assert picker._connected_from == 0

    picker._select_stream("force")
    picker._select_stream("emg")

    assert picker._connected_from == 0, "emg forgot it was attached after a round trip"


def test_returning_to_a_stream_keeps_the_scan_it_already_ran():
    """Same cause, and it cost a network scan rather than a reconnect."""
    picker = DevicePicker(
        "emg", devices=(DeviceSpec("d", _FakeSource, scan=True),), selectable=True
    )
    picker._targets = [{"name": "outlet-A", "info": ""}]
    picker._scanned_for = 0

    picker._select_stream("force")
    assert picker._targets == [], "force showed emg's scan"
    picker._select_stream("emg")

    assert picker._targets == [{"name": "outlet-A", "info": ""}], "emg lost its own scan"
    assert picker._scanned_for == 0


def test_switching_streams_changes_only_which_stream_is_shown():
    """The whole invariant, stated once: no stream's state moves because the panel
    looked at another one."""
    picker = DevicePicker(
        "emg",
        devices=(DeviceSpec("a", _FakeSource), DeviceSpec("b", _FakeSource)),
        selectable=True,
    )
    picker._selected = 1
    picker._connected_from = 1
    picker._select_stream("force")
    picker._selected = 0
    picker._connected_from = 0
    picker._select_stream("emg")
    # Both, not just the one being left: the clears this replaces ran *after* the
    # rebind, so they only ever damaged the stream being switched to.
    before = {name: dict(state.__dict__) for name, state in picker._per_stream.items()}

    picker._select_stream("force")

    assert picker._stream_name == "force"
    after = {name: dict(state.__dict__) for name, state in picker._per_stream.items()}
    assert after == before, "showing one stream disturbed another"


def test_live_sliders_go_away_when_the_stream_is_detached_by_anything_else():
    """`_connected_from` is this panel's record of its own last connect. A stream
    removed by a `StreamManager`, or an acquire loop that gave up, leaves it standing —
    and a slider still on screen would be retuning a source that is not running."""
    ctx, emg, _force = _two_stream_ctx()
    picker = DevicePicker("emg", devices=(DeviceSpec("d", _FakeSource),), selectable=True)

    picker._connect(ctx, emg, picker._devices[0])
    _settled(picker)
    assert emg.info is not None

    emg.disconnect()  # somebody else detached it

    assert picker._connected_from == 0, "the panel's own mark is not what changed"
    assert emg.info is None, "the stream is what says whether a source is attached"


def test_the_synthetic_device_can_be_contracted():
    """A fixed-amplitude fake signal makes every gesture the same waveform, so a model
    trained on it separates nothing and a prediction demo proves nothing.

    `activation` is what gives the synthetic source a state worth classifying. Noise and
    hum are deliberately NOT scaled — an electrode picks those up whether or not the
    muscle is working, and scaling them would hand a classifier a signal-to-noise cue no
    real recording has.
    """
    import numpy as np

    from myogestic.sources import SyntheticSource

    source = SyntheticSource(n_channels=4, fs=1000.0, noise=0.05, hum=0.0)
    source.connect()

    def rms(level: float) -> float:
        source.activation = level
        data, _ts = source.read()
        return float(np.sqrt((data.astype(np.float64) ** 2).mean()))

    rest, half, full = rms(0.0), rms(0.5), rms(1.0)

    assert rest < half < full, f"activation does not move the signal: {rest, half, full}"
    assert rest == pytest.approx(0.05, abs=0.02), "rest is not just the noise floor"
    # The default has to be the old behaviour, or every existing app changes amplitude.
    assert SyntheticSource().activation == 1.0


def test_the_synthetic_device_offers_activation_as_a_live_slider():
    """It must be reachable without a reconnect — a knob you can only set at construction
    cannot cue a subject mid-recording."""
    live = {p.attr for p in SYNTHETIC_DEVICE.live}
    assert "activation" in live, f"activation is not tunable while streaming: {live}"


@pytest.fixture
def picker_buttons(monkeypatch):
    """Observe real ImGui items and inject one enabled button click by its ID."""
    from imgui_bundle import imgui

    seen = []
    click = {"id": None}
    original = imgui.button

    def button(label, *args):
        result = original(label, *args)
        disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
        seen.append((label, disabled))
        return result or (label.endswith(click["id"]) and not disabled if click["id"] else False)

    monkeypatch.setattr(imgui, "button", button)
    return seen, click


def test_stream_chip_selects_without_losing_per_stream_state(imgui_frame, picker_buttons):
    seen, click = picker_buttons
    ctx = _FakeCtx({name: Stream(name, source=_FakeSource(), window_ms=100) for name in ("emg", "force", "target")})
    picker = DevicePicker("emg", selectable=True, exclude=("target",))
    picker._choices[0]["emg"] = 1
    click["id"] = "##dp_stream_force"
    imgui_frame(lambda: picker.ui(ctx))
    assert picker._stream_name == "force"
    assert not any("dp_stream_target" in label for label, _ in seen)
    click["id"] = "##dp_stream_emg"
    imgui_frame(lambda: picker.ui(ctx))
    assert picker._choices[0]["emg"] == 1


def test_add_chip_submits_cleaned_name(imgui_frame, picker_buttons, monkeypatch):
    from imgui_bundle import imgui

    seen, click = picker_buttons
    added = []
    ctx = _FakeCtx({"emg": Stream("emg", source=_FakeSource(), window_ms=100)})
    picker = DevicePicker("emg", selectable=True, on_add=added.append)
    click["id"] = "##dp_add_open"
    imgui_frame(lambda: picker.ui(ctx))
    monkeypatch.setattr(imgui, "input_text_with_hint", lambda *args: (True, "  F/o.rce-é_2  "))
    click["id"] = "##dp_add"
    imgui_frame(lambda: picker.ui(ctx))
    assert added == ["force-_2"]


@pytest.mark.parametrize("recording", [False, True])
def test_remove_chip_keeps_last_stream_and_blocks_recording(imgui_frame, picker_buttons, recording):
    seen, click = picker_buttons
    ctx = _FakeCtx({"emg": Stream("emg", source=_FakeSource(), window_ms=100)})
    removed = []

    def remove(name):
        removed.append(name)
        ctx.streams.pop(name)

    picker = DevicePicker("emg", selectable=True, on_remove=remove)
    click["id"] = "##dp_remove_emg"
    imgui_frame(lambda: picker.ui(ctx))
    assert not any("##dp_remove" in label for label, _ in seen)
    ctx.streams["force"] = Stream("force", source=_FakeSource(), window_ms=100)
    ctx.state = "recording" if recording else "idle"
    ctx.recording = recording
    seen.clear()
    imgui_frame(lambda: picker.ui(ctx))
    assert [disabled for label, disabled in seen if "##dp_remove_emg" in label] == [recording]
    assert removed == ([] if recording else ["emg"])
    assert picker._stream_name == ("emg" if recording else "force")


def test_removed_selected_stream_falls_back_to_remaining_chip(imgui_frame):
    ctx = _FakeCtx({"force": Stream("force", source=_FakeSource(), window_ms=100)})
    picker = DevicePicker("emg", selectable=True)
    imgui_frame(lambda: picker.ui(ctx))
    assert picker._stream_name == "force"


@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("recording", [False, True])
def test_action_area_matches_attachment_and_recording(imgui_frame, picker_buttons, connected, recording):
    from imgui_bundle import icons_fontawesome_6 as fa

    seen, _ = picker_buttons
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    if connected:
        assert stream.reconnect()
        stream.status = "connected"  # acquire loop marks this on the first sample
    ctx = _FakeCtx({"emg": stream})
    ctx.state = "recording" if recording else "idle"
    ctx.recording = recording
    picker = DevicePicker("emg")
    imgui_frame(lambda: picker.ui(ctx))
    actions = [(label, disabled) for label, disabled in seen if "##dp_connect" in label or "##dp_disconnect" in label]
    expected = ([f"{fa.ICON_FA_ARROWS_ROTATE}##dp_connect", f"{fa.ICON_FA_PLUG_CIRCLE_XMARK}##dp_disconnect"]
                if connected else [f"{fa.ICON_FA_PLUG}  Connect##dp_connect"])
    assert actions == [(label, recording) for label in expected]


@pytest.mark.parametrize("scale,width", [(1.0, 400), (1.0, 220), (2.0, 800), (2.0, 400)])
@pytest.mark.parametrize("state", ["idle", "connected", "connecting"])
def test_compact_controls_stay_inside_the_card(imgui_frame, monkeypatch, scale, width, state):
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    ctx = _FakeCtx({"emg": stream, "long_stream_name_to_wrap": stream, "force": stream})
    picker = DevicePicker("emg", selectable=True, on_add=lambda name: None, on_remove=lambda name: None)
    if state == "connected":
        assert stream.reconnect()
        stream.status = "connected"
    if state == "connecting":
        picker._connecting = True
        picker._connect_started = time.monotonic()
    items = []
    for name in ("button", "combo"):
        original = getattr(imgui, name)

        def tracked(label, *args, original=original):
            result = original(label, *args)
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            origin, size = imgui.get_window_pos(), imgui.get_window_size()
            items.append((label, lo.x >= origin.x, hi.x <= origin.x + size.x))
            return result

        monkeypatch.setattr(imgui, name, tracked)

    def draw():
        imgui.begin_child("card", imgui.ImVec2(width, 450))
        picker.ui(ctx)
        imgui.end_child()

    imgui_frame(draw)
    assert items and all(left and right for _, left, right in items), items


@pytest.mark.parametrize("typed", ["...", " EMG "])
def test_add_refuses_empty_and_duplicate_names(imgui_frame, picker_buttons, monkeypatch, typed):
    from imgui_bundle import imgui

    seen, click = picker_buttons
    added = []
    ctx = _FakeCtx({"emg": Stream("emg", source=_FakeSource(), window_ms=100)})
    picker = DevicePicker("emg", selectable=True, on_add=added.append)
    picker._adding = True
    monkeypatch.setattr(imgui, "input_text_with_hint", lambda *args: (True, typed))
    click["id"] = "##dp_add"
    imgui_frame(lambda: picker.ui(ctx))
    assert added == []
    assert ("Add##dp_add", True) in seen


def test_recording_blocks_add_and_explains_every_device_action(imgui_frame, picker_buttons, monkeypatch):
    from imgui_bundle import imgui

    seen, click = picker_buttons
    tooltips = []
    monkeypatch.setattr(imgui, "is_item_hovered", lambda *args: True)
    monkeypatch.setattr(imgui, "set_tooltip", tooltips.append)
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    assert stream.reconnect()
    stream.status = "connected"
    ctx = _FakeCtx({"emg": stream, "force": stream})
    ctx.state = "recording"
    ctx.recording = True
    picker = DevicePicker("emg", selectable=True, on_add=lambda name: pytest.fail(name), on_remove=lambda name: pytest.fail(name))
    click["id"] = "##dp_add_open"
    imgui_frame(lambda: picker.ui(ctx))
    assert not picker._adding
    assert all(disabled for label, disabled in seen if any(key in label for key in ("dp_add", "dp_remove", "dp_connect", "dp_disconnect")))
    assert "Stop the recording before adding a stream." in tooltips
    assert "Stop the recording before removing a stream." in tooltips
    assert tooltips.count("Stop the recording before changing device.") == 2


def test_connecting_detail_leaves_room_for_abort(imgui_frame, monkeypatch):
    from imgui_bundle import imgui

    from myogestic.widgets.signals import device_picker as module

    picker = DevicePicker("emg")
    picker._connecting = True
    picker._connect_started = time.monotonic() - 12
    stream = Stream("emg", source=_FakeSource(), window_ms=100)
    ctx = _FakeCtx({"emg": stream})
    rects = {}
    mono_text, button = module.mono_text, imgui.button

    def text(label, *args):
        mono_text(label, *args)
        rects["detail_right"] = imgui.get_item_rect_max().x

    def action(label, *args):
        result = button(label, *args)
        if "dp_abort" in label:
            rects["abort_left"] = imgui.get_item_rect_min().x
        return result

    monkeypatch.setattr(module, "mono_text", text)
    monkeypatch.setattr(imgui, "button", action)

    def draw():
        imgui.begin_child("narrow-connecting", imgui.ImVec2(180, 350))
        picker.ui(ctx)
        imgui.end_child()

    imgui_frame(draw)
    assert rects["detail_right"] < rects["abort_left"]


@pytest.mark.parametrize("width,columns", [(400, 2), (180, 1)])
def test_option_grid_stacks_when_cells_are_too_narrow(imgui_frame, monkeypatch, width, columns):
    from imgui_bundle import imgui

    positions = {}
    button = imgui.button

    def tracked(label, *args):
        result = button(label, *args)
        if label.startswith(("EMG##", "Off##")):
            positions[label.split("##")[0]] = imgui.get_item_rect_min().y
        return result

    monkeypatch.setattr(imgui, "button", tracked)
    picker = DevicePicker("emg")
    ctx = _FakeCtx({"emg": Stream("emg", source=_FakeSource(), window_ms=100)})

    def draw():
        imgui.begin_child("options-grid", imgui.ImVec2(width, 350))
        picker.ui(ctx)
        imgui.end_child()

    imgui_frame(draw)
    assert (positions["EMG"] == positions["Off"]) == (columns == 2)
