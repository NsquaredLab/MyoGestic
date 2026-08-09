"""Device selection panel — choose a device, configure it, connect.

Every acquisition example hardcodes its source at import time, so moving from a
Muovi to a Quattrocento, or from 2000 Hz to 500 Hz, means editing Python.
[`DevicePicker`][] moves that choice into the running UI: pick a device from a
dropdown, set the handful of knobs that device actually has, press Connect.

The device list is data — a sequence of [`DeviceSpec`][] entries passed in code — so
an app offers exactly the hardware it supports. [`DEFAULT_DEVICES`][] covers the
OTB family plus any LSL outlet on the network.
"""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.sources.lsl import LSLSource
from myogestic.sources.otb import MuoviSource, QuattrocentoSource
from myogestic.sources.synthetic import SyntheticSource
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    format_age,
    label_column,
    mono_text,
    muted,
    panel_header,
    segmented,
)

# Same subpackage, and the age read is subtle enough (it takes the stream lock,
# because `reconnect` reallocates the display buffers under it) that a second
# copy would be a second thing to get wrong.
from myogestic.widgets.signals.stream_panel import _last_ts_age

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.stream import Source, Stream


@dataclass(frozen=True)
class DeviceOption:
    """One labelled row of choices in a [`DeviceSpec`][]'s configuration.

    Parameters
    ----------
    kwarg
        Constructor keyword the chosen value is passed as.
    label
        Row label, spelled out in the unit the operator thinks in —
        ``"Channels"``, ``"Sample rate"``, not ``"nch_mode"``. Only the device
        entry knows what its own constructor keywords mean.
    choices
        ``{shown: value}``, in the order they should appear. Shown text is
        drawn as a segmented control when the row is wide enough for every
        option at once, so keep it short — the ``label`` carries the unit.
    """

    kwarg: str
    label: str
    choices: Mapping[str, Any]


@dataclass(frozen=True)
class DeviceParam:
    """One slider that tunes a **connected** source while it streams.

    Where an [`DeviceOption`][] is a constructor argument — fixed when Connect builds
    the source — a `DeviceParam` writes straight to an attribute of the source
    that is already running. The next chunk follows; nothing reconnects, the
    plot does not reset, and a recording in progress keeps its geometry.

    The source must therefore expose that attribute publicly and read it fresh
    each chunk. Assigning a float is atomic under the GIL, so no lock is needed
    between the UI thread and the acquire thread.

    Parameters
    ----------
    attr
        Public attribute on the source to read and write.
    label
        Row label, spelled out in the unit the operator thinks in.
    lo, hi
        Slider range.
    fmt
        ``printf`` format for the value shown on the slider.

    Examples
    --------
    >>> DeviceParam("noise", "Noise", 0.0, 1.0).attr
    'noise'
    """

    attr: str
    label: str
    lo: float
    hi: float
    fmt: str = "%.2f"


@dataclass(frozen=True)
class DeviceSpec:
    """One selectable entry in a [`DevicePicker`][] dropdown.

    Parameters
    ----------
    label
        Shown in the dropdown, e.g. ``"Quattrocento"``.
    factory
        Builds the source when Connect is pressed — a source class, or a
        ``functools.partial`` of one. Called with the chosen options as keyword
        arguments, and *only* on Connect: selecting a device costs nothing.
    options
        The [`DeviceOption`][] rows to draw, in order. Their chosen values are passed
        to ``factory`` as keyword arguments. Each row starts on whichever choice
        matches the factory's *own* default, so leaving them all alone
        reproduces ``factory()`` exactly.
    scan
        ``True`` for a source whose target is discovered at runtime rather than
        configured — LSL, serial. Draws a target list fed by ``discover()``
        instead of the option rows, and hands the choice to
        `Stream.reconnect`. This is *declared*, not detected: a source can
        implement ``discover()`` and still be configured statically, and some
        do.
    live
        [`DeviceParam`][] sliders, shown only once this device is the connected
        one. They tune the running source in place — use them for anything worth
        changing without dropping the stream.
    hint
        One line on what this device *is*, or how it connects. Shown behind an
        **ⓘ** button beside the dropdown rather than on the panel: it is read
        once, when the hardware is first wired up. No hint and no steps, no
        button.
    steps
        The setup procedure, one instruction per entry, rendered as a numbered
        list under the hint. Setup is a sequence of physical acts — hold this,
        join that, then press Connect — and a paragraph makes the reader
        re-derive the order every time they come back to it.

    Examples
    --------
    >>> from functools import partial
    >>> from myogestic.sources.otb import MuoviSource
    >>> DeviceSpec(
    ...     "Muovi+ — 64 ch",
    ...     partial(MuoviSource, plus=True),
    ...     (DeviceOption("emg", "Signal", {"EMG": True, "EEG": False}),),
    ...     hint="Join the probe's Wi-Fi network, then Connect.",
    ... ).label
    'Muovi+ — 64 ch'
    """

    label: str
    factory: Callable[..., Any]
    options: Sequence[DeviceOption] = field(default_factory=tuple)
    scan: bool = False
    live: Sequence[DeviceParam] = field(default_factory=tuple)
    hint: str = ""
    steps: Sequence[str] = field(default_factory=tuple)


_MUOVI_HINT = "This PC is the server; the probe connects in over Wi-Fi."
_MUOVI_STEPS = (
    "Hold the probe's button for about 5 seconds, until it becomes a Wi-Fi access point.",
    "Join its MVxxx-ID network from this PC.",
    "Press Connect.",
)
_QUATTROCENTO_HINT = "The amplifier is the server at 169.254.1.10; this PC connects to it."
_QUATTROCENTO_STEPS = (
    "Connect the amplifier to this PC over Ethernet.",
    "Give this PC a 169.254.x.x address on that segment.",
    "Press Connect.",
)
_MUOVI_SIGNAL = DeviceOption("emg", "Signal", {"EMG": True, "EEG": False})
_DETECTION = {"Monopolar": "monopolar", "Differential": "differential", "Bipolar": "bipolar"}
#: Each device names its accessory block after what is actually in it — the Muovi
#: has no analogue input, so it must not advertise one. Appended unscaled, hence
#: off by default: they are raw counts, not volts, and would wreck a shared plot
#: range. Turning this on is how a force transducer wired to an AUX input becomes
#: reachable at all.
_MUOVI_AUX = DeviceOption("include_aux", "IMU + counters", {"Off": False, "On": True})
_QUATTROCENTO_AUX = DeviceOption("include_aux", "AUX IN + accessory", {"Off": False, "On": True})

#: The OT Bioelettronica family.
OTB_DEVICES: tuple[DeviceSpec, ...] = (
    DeviceSpec(
        "Muovi — 32 ch",
        MuoviSource,
        (_MUOVI_SIGNAL, _MUOVI_AUX),
        hint=_MUOVI_HINT,
        steps=_MUOVI_STEPS,
    ),
    DeviceSpec(
        "Muovi+ — 64 ch",
        partial(MuoviSource, plus=True),
        (_MUOVI_SIGNAL, _MUOVI_AUX),
        hint=_MUOVI_HINT,
        steps=_MUOVI_STEPS,
    ),
    DeviceSpec(
        "Quattrocento",
        QuattrocentoSource,
        (
            DeviceOption("nch_mode", "Channels", {"96": 0, "192": 1, "288": 2, "384": 3}),
            DeviceOption("fs_mode", "Sample rate", {"512": 0, "2048": 1, "5120": 2, "10240": 3}),
            DeviceOption("detection", "Detection", _DETECTION),
            _QUATTROCENTO_AUX,
        ),
        hint=_QUATTROCENTO_HINT,
        steps=_QUATTROCENTO_STEPS,
    ),
)

#: Any Lab Streaming Layer outlet advertised on the network. The outlet is
#: chosen by scanning, so the entry carries no options of its own.
LSL_DEVICE = DeviceSpec(
    "LSL stream",
    lambda: LSLSource(""),
    scan=True,
    hint="Any Lab Streaming Layer outlet advertised on this network.",
    steps=("Press Scan.", "Pick the outlet from the list.", "Press Connect."),
)

#: A fake amplifier, so an app is usable before the hardware arrives — and so a
#: bug report can be reproduced without it. Listed last, and labelled as a test
#: signal, because a take recorded from it is not data.
SYNTHETIC_DEVICE = DeviceSpec(
    "Synthetic (no hardware)",
    SyntheticSource,
    (
        DeviceOption("n_channels", "Channels", {"8": 8, "16": 16, "32": 32, "64": 64}),
        DeviceOption("fs", "Sample rate", {"512": 512.0, "1000": 1000.0, "2048": 2048.0}),
    ),
    live=(
        DeviceParam("activation", "Activation", 0.0, 1.0),
        DeviceParam("direction", "Direction", -1.0, 1.0),
        DeviceParam("noise", "Noise", 0.0, 1.0),
        DeviceParam("hum", "Hum", 0.0, 1.0),
        DeviceParam("hum_hz", "Hum (Hz)", 50.0, 60.0, "%.0f Hz"),
    ),
    hint="In-process sine waves and mains hum. A test signal, not data.",
    steps=(
        "Pick a channel count and sample rate.",
        "Press Connect — nothing has to be plugged in.",
        "Drag Activation to contract the imaginary muscle; you are the subject.",
        "Direction steers that effort between the first and second half of the "
        "channels, so a two-way gesture reads differently each way.",
        "Noise, Hum and Hum (Hz) retune the signal live, without a reconnect.",
    ),
)

#: What [`DevicePicker`][] offers when no list is passed.
DEFAULT_DEVICES: tuple[DeviceSpec, ...] = (*OTB_DEVICES, LSL_DEVICE, SYNTHETIC_DEVICE)


def _default_choices(dev: DeviceSpec) -> dict[str, int]:
    """Index each of ``dev``'s option rows at the factory's *own* default.

    So the panel opens showing exactly what ``dev.factory()`` would do unaided,
    and there is no second table of defaults to drift out of step with the
    source constructors. Falls back to the first choice for anything that
    cannot be resolved.
    """
    try:
        params = inspect.signature(dev.factory).parameters
    except (TypeError, ValueError):  # a builtin or C callable has no signature
        params = {}  # type: ignore

    choices: dict[str, int] = {}
    for opt in dev.options:
        param = params.get(opt.kwarg)
        default = param.default if param is not None else inspect.Parameter.empty
        items = list(opt.choices.values())
        # Compare type first: `True == 1`, so a bool default must not silently
        # match an int option (nor a `0`/`False` pair the other way round).
        choices[opt.kwarg] = next(
            (i for i, v in enumerate(items) if type(v) is type(default) and v == default),
            0,
        )
    return choices


def _chosen_kwargs(dev: DeviceSpec, choices: Mapping[str, int]) -> dict[str, Any]:
    """Resolve per-row selected indices into keyword arguments for the factory."""
    kwargs: dict[str, Any] = {}
    for opt in dev.options:
        items = list(opt.choices.values())
        if items:
            kwargs[opt.kwarg] = items[min(max(choices.get(opt.kwarg, 0), 0), len(items) - 1)]
    return kwargs


#: Setup instructions live behind a button rather than on screen: they are read
#: once, when the hardware is first wired up, and cost two permanent lines after.
_HINT_POPUP = "Setup##dp_hint"
_HINT_WRAP = 340.0


def _row_labels(dev: DeviceSpec) -> tuple[str, ...]:
    """Every row label in the panel, so one column width serves all of them."""
    target = ("Stream",) if dev.scan else ()
    return (
        "Device",
        *target,
        *(o.label for o in dev.options),
        *(p.label for p in dev.live),
    )


def _fits_segmented(labels: Sequence[str], avail: float) -> bool:
    """Whether every choice can be shown at once in ``avail`` pixels.

    A segmented control beats a dropdown when it fits — one click instead of
    two, and the alternatives stay visible — but it cannot wrap or truncate, so
    a narrow panel or a device with wordy choices falls back to a combo.
    """
    style = imgui.get_style()
    per = style.frame_padding.x * 2.0 + 2.0  # `segmented` overrides item spacing to 2 px
    return sum(imgui.calc_text_size(t).x + per for t in labels) <= avail


def _swap_source(stream: Stream, source: Source, target: str | None = None) -> bool:
    """Attach ``source`` to ``stream``, closing whatever was attached before.

    `Stream.reconnect` only ever (re)connects ``stream._source``, which by the
    time it runs is already the *new* object — so a picker that assigns the
    attribute and stops there never disconnects the source it replaced. For
    Muovi and Sessantaquattro that leaks the **listening** server socket, which
    only their ``disconnect()`` override closes, and the next Connect to the
    same device then fails to bind its fixed port. ``SO_REUSEADDR`` is set on
    both but does not permit binding over a live listener.

    The swap itself is a bare attribute assignment, which is safe against the
    running acquire thread: a freshly constructed source holds no socket and its
    ``read()`` returns ``(None, None)``, and `Stream.reconnect` clears
    ``_connected`` under the stream lock immediately afterwards. Stopping and
    restarting the stream would be worse — `App.run` owns that thread, and
    calling ``start()`` again would spawn a second one.

    Returns
    -------
    bool
        What `Stream.reconnect` returned: ``False`` leaves the error in
        ``stream.last_error`` and the stream detached.
    """
    old = stream._source
    if old is not source:
        stream._source = source
        try:
            old.disconnect()
        except Exception:
            pass  # already gone, or never connected in the first place
    return stream.reconnect(target)


@dataclass
class _StreamState:
    """One stream's worth of a `DevicePicker`'s state.

    Split out because a ``selectable`` picker drives several streams and none of
    this describes the panel — it describes whichever stream the panel is
    currently showing.
    """

    #: Index into the picker's device list.
    selected: int = 0
    #: Per device, per option kwarg: the chosen index.
    choices: list[dict[str, int]] = field(default_factory=list)
    connecting: bool = False
    connect_started: float = 0.0
    #: Bumped on every connect *and* on every abort. A worker whose generation
    #: no longer matches has been superseded or given up on, and must not
    #: report, log, or leave its error behind.
    connect_gen: int = 0
    #: Which device index the attached source came from. Live sliders write to a
    #: *running* source, so they must never render for a device that merely
    #: happens to be picked in the dropdown.
    connected_from: int | None = None
    #: discover() results for `scan` devices, plus which device index they belong
    #: to (None = never scanned, so "nothing found" stays quiet).
    targets: list[dict[str, str]] = field(default_factory=list)
    target_selected: int = 0
    scanned_for: int | None = None


class DevicePicker:
    """Pick a device, configure it, and connect the stream to it.

    Replaces `StreamPanel` for the one stream it names: the panel header's dot
    carries the connection state, and the Connect button is what binds the
    stream to hardware. Nothing connects on its own, and changing the controls
    does nothing until Connect is pressed — so the plot never swaps out from
    under a recording.

    Parameters
    ----------
    stream
        Name of the stream to attach to, as registered with ``app.streams``.
    devices
        What the dropdown offers. Defaults to [`DEFAULT_DEVICES`][] (the OTB
        family plus LSL); pass a narrower list for an app that supports one
        amplifier, or add your own [`DeviceSpec`][] entries.
    widget_id
        ImGui id scope and state key. Defaults to the stream name. Give each
        instance its own when an app renders more than one: ImGui derives a
        control's identity from its label plus the enclosing scope, and a
        `Grid` cell is a single child window — so two of these in one cell
        share every slider, popup and plot until they are told apart.
    selectable
        Add a **Stream** row naming which stream this panel configures, chosen
        from ``ctx.streams``. For an app where streams come and go at runtime —
        one picker follows whichever you are setting up, instead of one panel
        per stream. Off by default: with a single declared stream the row is a
        dropdown of one.
    exclude
        Stream names this panel must not offer. For a stream whose source
        belongs to another widget — a `TrackingTask`'s target, a replay — where
        a Connect would replace that source and leave its owner writing to
        nothing, with the recording holding a device's data under the wrong
        name. A frozen set, so streams added at runtime are offered unless they
        are named here.
    show_header
        Render the standard ``panel_header``. Turning it off also removes the
        status dot, so the panel loses its state cue — leave it on unless the
        surrounding layout already says which device this is.

    Examples
    --------
    >>> from myogestic.widgets import DevicePicker, OTB_DEVICES
    >>> picker = DevicePicker("emg", devices=OTB_DEVICES)
    >>> picker.ui(ctx)
    """

    def __init__(
        self,
        stream: str,
        *,
        devices: Sequence[DeviceSpec] = DEFAULT_DEVICES,
        show_header: bool = True,
        selectable: bool = False,
        exclude: Iterable[str] = (),
        widget_id: str | None = None,
    ) -> None:
        self._stream_name = stream
        self._widget_id = widget_id or self._stream_name
        self._devices = tuple(devices)
        self._show_header = show_header
        self._selectable = selectable
        self._excluded = frozenset(exclude)
        self._scanning = False
        # One entry per stream this panel has been pointed at. Every field on
        # `_StreamState` is a fact about a *stream* — which device it is set to,
        # which attempt is in flight, what a scan found — so with `selectable`
        # holding them once for the widget made switching streams show the
        # previous one's configuration: a device dropdown naming something the
        # new stream was never attached to, beside a green dot belonging to it.
        self._per_stream: dict[str, _StreamState] = {}

    # --- per-stream state ----------------------------------------------------
    def _state_for(self, name: str) -> _StreamState:
        """State belonging to ``name``, seeded on first sight of it."""
        state = self._per_stream.get(name)
        if state is None:
            state = _StreamState(choices=[_default_choices(d) for d in self._devices])
            self._per_stream[name] = state
        return state

    @property
    def _selected(self) -> int:
        return self._state_for(self._stream_name).selected

    @_selected.setter
    def _selected(self, value: int) -> None:
        self._state_for(self._stream_name).selected = value

    @property
    def _choices(self) -> list[dict[str, int]]:
        return self._state_for(self._stream_name).choices

    @_choices.setter
    def _choices(self, value: list[dict[str, int]]) -> None:
        self._state_for(self._stream_name).choices = value

    @property
    def _connecting(self) -> bool:
        return self._state_for(self._stream_name).connecting

    @_connecting.setter
    def _connecting(self, value: bool) -> None:
        self._state_for(self._stream_name).connecting = value

    @property
    def _connect_started(self) -> float:
        return self._state_for(self._stream_name).connect_started

    @_connect_started.setter
    def _connect_started(self, value: float) -> None:
        self._state_for(self._stream_name).connect_started = value

    @property
    def _connect_gen(self) -> int:
        return self._state_for(self._stream_name).connect_gen

    @_connect_gen.setter
    def _connect_gen(self, value: int) -> None:
        self._state_for(self._stream_name).connect_gen = value

    @property
    def _connected_from(self) -> int | None:
        return self._state_for(self._stream_name).connected_from

    @_connected_from.setter
    def _connected_from(self, value: int | None) -> None:
        self._state_for(self._stream_name).connected_from = value

    @property
    def _targets(self) -> list[dict[str, str]]:
        return self._state_for(self._stream_name).targets

    @_targets.setter
    def _targets(self, value: list[dict[str, str]]) -> None:
        self._state_for(self._stream_name).targets = value

    @property
    def _target_selected(self) -> int:
        return self._state_for(self._stream_name).target_selected

    @_target_selected.setter
    def _target_selected(self, value: int) -> None:
        self._state_for(self._stream_name).target_selected = value

    @property
    def _scanned_for(self) -> int | None:
        return self._state_for(self._stream_name).scanned_for

    @_scanned_for.setter
    def _scanned_for(self, value: int | None) -> None:
        self._state_for(self._stream_name).scanned_for = value

    def ui(self, ctx: Context) -> None:
        """Render the picker. Call once per frame.

        Everything below is drawn inside an ImGui id scope named by
        ``widget_id``. ImGui derives a control's identity from its label plus the
        enclosing scope, and a `Grid` cell is one child window — so without this,
        two of these panels in a single cell would share every control. Pushed
        around the whole body rather than prefixed onto each label, because a
        prefix has to be remembered at every site and this cannot be forgotten.
        """
        imgui.push_id(self._widget_id)
        try:
            stream = ctx.streams.get(self._stream_name)
            tone, detail = self._state(stream)

            if self._show_header:
                # No tooltip on the dot. Colour alone is not a readable answer, so
                # the state has to live somewhere else — but this panel already
                # prints it in words below the buttons, and a tooltip repeating that
                # is a second copy to keep in step for no gain. Panels with no
                # visible read-out (`process_launcher`) do still carry one.
                panel_header("Source", fa.ICON_FA_MICROCHIP, status=tone)

            if stream is None:
                imgui.text_colored(muted(), f"(no stream named {self._stream_name!r})")
                return
            if not self._devices:
                imgui.text_colored(muted(), "(no devices configured)")
                return

            if self._selectable:
                self._stream_row(ctx)
                stream = ctx.streams.get(self._stream_name)
                if stream is None:
                    imgui.text_colored(muted(), "(no stream selected)")
                    return

            self._selected = min(self._selected, len(self._devices) - 1)
            dev = self._devices[self._selected]
            # One column width for every row, so the fields line up as a block
            # rather than reading as four unrelated controls.
            among = _row_labels(dev)

            style = imgui.get_style()
            info_w = (
                imgui.calc_text_size(fa.ICON_FA_CIRCLE_INFO).x
                + style.frame_padding.x * 2.0
                + style.item_spacing.x
                if dev.hint or dev.steps
                else 0.0
            )
            label_column("Device", among, reserve=info_w)
            changed, idx = imgui.combo(
                "##dp_device", self._selected, [d.label for d in self._devices]
            )
            if changed:
                self._selected = idx
                self._targets = []
                self._scanned_for = None
                dev = self._devices[idx]
                among = _row_labels(dev)
            anchor = None
            if info_w:
                imgui.same_line()
                if imgui.button(f"{fa.ICON_FA_CIRCLE_INFO}##dp_hint_open"):
                    imgui.open_popup(_HINT_POPUP)
                imgui.set_item_tooltip("How to set this device up")
                # Read while the button is still the current item: the popup anchors
                # to it rather than to wherever ImGui would default to.
                rect_max = imgui.get_item_rect_max()
                anchor = imgui.ImVec2(rect_max.x, rect_max.y + style.item_spacing.y)
            self._hint_popup(dev, anchor)

            if dev.scan:
                self._scan_ui(dev, among)
            else:
                self._option_ui(dev, among)

            imgui.spacing()
            self._connect_ui(ctx, stream, dev)
            mono_text(detail, DANGER if tone is DANGER else muted())
            self._live_ui(stream, dev, among)
        finally:
            imgui.pop_id()

    def _stream_row(self, ctx: Context) -> None:
        """Which stream this panel configures."""
        names = sorted(n for n in ctx.streams if n not in self._excluded)
        label_column("Stream", ("Stream", "Device"))
        if not names:
            imgui.text_colored(muted(), "(none)")
            return
        current = names.index(self._stream_name) if self._stream_name in names else -1
        changed, idx = imgui.combo("##dp_stream", current, names)
        if changed and 0 <= idx < len(names):
            self._select_stream(names[idx])

    def _select_stream(self, name: str) -> None:
        """Point the panel at another stream. Changes nothing but which one is shown.

        Every field the panel reads lives in that stream's own `_StreamState`, so the
        incoming stream's device, scan results and attachment mark are already its own
        and were right when it was last shown. There is nothing to clear.

        This used to clear ``_connected_from``, ``_targets`` and ``_scanned_for``, from
        when they were held once for the whole widget. Past the per-stream split those
        clears did not merely become unnecessary — the assignment below rebinds which
        state the properties address, so every one of them landed on the **incoming**
        stream. Switching away and back therefore wiped the stream you returned to: its
        live sliders vanished until it was connected again, and a scan it had already
        run was thrown away.
        """
        self._stream_name = name

    def _hint_popup(self, dev: DeviceSpec, anchor: imgui.ImVec2 | None) -> None:
        """The device's setup instructions, on demand.

        A dismissable popup rather than a tooltip: the OTB hints are two or three
        sentences describing a physical procedure, and a tooltip vanishes the
        moment you move the pointer towards the thing it told you to do.

        Positioned under its own button, hanging left (pivot on the right edge)
        so it opens over the panel instead of off the side of the window.
        Without this ImGui places it wherever the popup was opened from, which
        for a panel redrawn every frame is not reliably next to the button.
        """
        if anchor is not None:
            imgui.set_next_window_pos(anchor, imgui.Cond_.always, imgui.ImVec2(1.0, 0.0))
        if not imgui.begin_popup(_HINT_POPUP):
            return
        try:
            imgui.text_colored(muted(), dev.label.upper())
            imgui.separator()
            if dev.hint:
                imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + _HINT_WRAP)
                imgui.text_unformatted(dev.hint)
                imgui.pop_text_wrap_pos()
            if dev.hint and dev.steps:
                imgui.spacing()
            # Hanging indent: the number sits in its own gutter and the step's
            # own wrapped lines stay flush with its first, so the list reads as
            # a column of instructions rather than as text with digits in it.
            gutter = imgui.calc_text_size("00.").x + imgui.get_style().item_spacing.x
            for number, step in enumerate(dev.steps, start=1):
                # `same_line(offset)` measures from the window edge, not from the
                # item, so it collapses the gutter inside a popup. Set the column
                # explicitly instead.
                left = imgui.get_cursor_pos_x()
                imgui.text_colored(muted(), f"{number}.")
                imgui.same_line()
                imgui.set_cursor_pos_x(left + gutter)
                imgui.push_text_wrap_pos(left + gutter + _HINT_WRAP)
                imgui.text_unformatted(step)
                imgui.pop_text_wrap_pos()
                imgui.spacing()
        finally:
            imgui.end_popup()

    # --- configuration ------------------------------------------------------
    def _option_ui(self, dev: DeviceSpec, among: Sequence[str]) -> None:
        """One labelled row per option — segmented where it fits, else a combo."""
        choices = self._choices[self._selected]
        for opt in dev.options:
            labels = list(opt.choices)
            if not labels:
                continue
            current = min(max(choices.get(opt.kwarg, 0), 0), len(labels) - 1)
            width = label_column(opt.label, among)
            if _fits_segmented(labels, width):
                choices[opt.kwarg] = segmented(f"dp_{opt.kwarg}", labels, current)
            else:
                changed, idx = imgui.combo(f"##dp_opt_{opt.kwarg}", current, labels)
                if changed:
                    choices[opt.kwarg] = idx

    def _scan_ui(self, dev: DeviceSpec, among: Sequence[str]) -> None:
        """A labelled target row fed by ``discover()``, with a rescan button."""
        # Auto-scan once per selection, so the list is already there without
        # the user knowing to press Scan first.
        if self._scanned_for != self._selected and not self._scanning:
            self._start_scan(dev)

        style = imgui.get_style()
        rescan_w = (
            imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x
            + style.frame_padding.x * 2.0
            + style.item_spacing.x
        )
        label_column("Stream", among, reserve=rescan_w)

        if self._scanning:
            imgui.text_colored(muted(), "scanning…")
            return

        if not self._targets:
            imgui.text_colored(muted(), "nothing found" if self._scanned_for is not None else "—")
        else:
            labels = [f"{t.get('name', '?')} ({t.get('info', '')})" for t in self._targets]
            self._target_selected = min(self._target_selected, len(labels) - 1)
            changed, idx = imgui.combo("##dp_target", self._target_selected, labels)
            if changed:
                self._target_selected = idx

        imgui.same_line()
        if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##dp_scan"):
            self._start_scan(dev)
        imgui.set_item_tooltip("Rescan for outlets")

    def _start_scan(self, dev: DeviceSpec) -> None:
        """Run ``discover()`` off-thread on a throwaway source.

        The probe is never connected — ``discover()`` on both shipped
        scan-capable sources is a network query, not a session — so it needs no
        teardown and cannot disturb the stream's current source.
        """
        if self._scanning:
            return
        self._scanning = True
        # Held, not re-resolved — the same reason `_connect` holds it. The operator can
        # switch the panel to another stream while `discover()` is still out, and the
        # `_targets` / `_scanned_for` properties resolve `self._stream_name` at *write*
        # time: the results would land on whichever stream is showing when the worker
        # returns, leaving the stream that was actually scanned with an empty list and
        # `scanned_for` already set — which is "nothing found", permanently, because the
        # auto-rescan guard in `_scan_ui` never fires again.
        state = self._state_for(self._stream_name)
        state.scanned_for = state.selected
        kwargs = _chosen_kwargs(dev, self._choices[state.selected])

        def run() -> None:
            try:
                probe = dev.factory(**kwargs)
                state.targets = list(probe.discover())
                state.target_selected = 0
            except Exception:
                state.targets = []
            finally:
                self._scanning = False

        threading.Thread(target=run, daemon=True).start()

    def _live_ui(self, stream: Stream, dev: DeviceSpec, among: Sequence[str]) -> None:
        """Sliders that retune the running source, with no reconnect.

        Rendered only while *this* device is the attached one: the sliders write
        straight to ``stream._source``, so showing them for a device the user has
        merely selected would silently retune a different device.

        Attachment is read off the stream rather than trusted to ``_connected_from``.
        That mark is this panel's record of its own last connect, and anything else
        that detaches the stream — a `StreamManager` removing it, an acquire loop that
        gave up — leaves it standing, which would leave sliders on screen retuning a
        source that is no longer running.
        """
        if not dev.live or self._selected != self._connected_from or stream.info is None:
            return
        source = stream._source
        imgui.spacing()
        for param in dev.live:
            value = getattr(source, param.attr, None)
            if not isinstance(value, int | float):
                continue  # the attached source does not carry this knob
            label_column(param.label, among)
            changed, new = imgui.slider_float(
                f"##dp_live_{param.attr}", float(value), param.lo, param.hi, param.fmt
            )
            if changed:
                setattr(source, param.attr, new)

    # --- connect ------------------------------------------------------------
    def _connect_ui(self, ctx: Context, stream: Stream, dev: DeviceSpec) -> None:
        """Full-width primary action, disabled with the reason in its tooltip.

        While a connect is in flight the button becomes **Abort** rather than a
        greyed-out "Connecting…". An OTB source waits ``accept_timeout`` — 30 s
        by default — for a device to dial in, and a device that was never
        switched on never will. Without a way out the panel is dead for half a
        minute and the operator cannot even pick a different device.
        """
        full = imgui.ImVec2(-1, 0)
        if self._connecting:
            # `STOP` already means "halt what is running" on the record button.
            if imgui.button(f"{fa.ICON_FA_STOP}  Abort##dp_abort", full):
                self._abort(ctx, stream)
            imgui.set_item_tooltip("Stop waiting for the device.")
            return

        recording = getattr(ctx, "state", "") == "recording"
        reason = ""
        if recording:
            # `reconnect` does not detach the session, so the acquire loop would
            # keep appending to the same zarr key at a new channel width.
            reason = "Stop the recording before changing device."
        elif dev.scan and not self._targets:
            reason = "No target to connect to yet."

        # The glyph shows what clicking will do: plug in, or re-fetch live state.
        attached = stream.status == "connected" and stream.info is not None
        blocked = bool(reason)
        if blocked:
            imgui.begin_disabled()

        if attached:
            # Two actions, so the row splits. Reconnect leads: re-reading a
            # device that has gone quiet is the common one, and detaching is
            # something you do at the end of a session.
            style = imgui.get_style()
            half = (imgui.get_content_region_avail().x - style.item_spacing.x) * 0.5
            if imgui.button(
                f"{fa.ICON_FA_ARROWS_ROTATE}  Reconnect##dp_connect", imgui.ImVec2(half, 0)
            ):
                self._connect(ctx, stream, dev)
            self._action_tooltip(reason, "Build this device again and re-attach the stream.")
            imgui.same_line()
            if imgui.button(f"{fa.ICON_FA_PLUG_CIRCLE_XMARK}  Disconnect##dp_disconnect", full):
                self._disconnect(ctx, stream)
            self._action_tooltip(reason, "Close the device and leave the stream detached.")
        else:
            if imgui.button(f"{fa.ICON_FA_PLUG}  Connect##dp_connect", full):
                self._connect(ctx, stream, dev)
            self._action_tooltip(reason, "Build this device and attach the stream to it.")

        if blocked:
            imgui.end_disabled()

    @staticmethod
    def _action_tooltip(reason: str, otherwise: str) -> None:
        """Why the action is unavailable, or what it does. Works while disabled."""
        if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip(reason or otherwise)

    def _disconnect(self, ctx: Context, stream: Stream) -> None:
        """Close the device and leave the stream detached but running.

        `Stream.disconnect`, not `stop`: the acquire loop belongs to `App.run`
        and is started once, so stopping it here would make Connect unable to
        bring the stream back.
        """
        self._connected_from = None
        stream.disconnect()
        ctx.log(f"{self._stream_name}: disconnected")

    def _abort(self, ctx: Context, stream: Stream) -> None:
        """Give up on the connect in flight.

        Closing the source's socket is what actually ends it: the worker is
        parked in a blocking ``accept()`` (or ``connect()``), and closing the
        descriptor from here makes that call raise at once instead of running
        out its timeout. Bumping the generation first means the worker treats
        the resulting error as the abort it is rather than reporting a failure.
        """
        self._connect_gen += 1
        self._connecting = False
        try:
            stream._source.disconnect()
        except Exception:
            pass  # never connected far enough to hold anything
        ctx.log(f"{self._stream_name}: connect aborted")

    def _connect(self, ctx: Context, stream: Stream, dev: DeviceSpec) -> None:
        """Build the configured source and attach it, off the UI thread.

        Off-thread because ``accept_timeout`` on the OTB sources defaults to
        30 s: a device that never dials in would otherwise freeze the app.
        """
        if self._connecting:
            # The button reads Abort while an attempt is in flight, so the UI
            # cannot produce this — but a second attempt would swap the source
            # out from under the first and then be refused by `Stream.reconnect`,
            # leaving nothing connected at all. Refuse it here instead.
            return

        kwargs = _chosen_kwargs(dev, self._choices[self._selected])
        target = (
            self._targets[self._target_selected].get("name")
            if dev.scan and self._targets
            else None
        )
        index = self._selected
        # Held, not re-resolved: the operator can switch the panel to another
        # stream while this attempt is in flight, and going through the property
        # would then compare this worker's generation against a different
        # stream's — letting a superseded attempt report as if it were current.
        state = self._state_for(self._stream_name)
        state.connect_gen += 1
        generation = state.connect_gen
        state.connecting = True
        state.connect_started = time.monotonic()
        ctx.log(f"{self._stream_name}: connecting to {dev.label}…")

        def run() -> None:
            try:
                # Build first: a bad option combination raises here, with the
                # stream still attached to whatever was working before.
                source = dev.factory(**kwargs)
                ok = _swap_source(stream, source, target)
                if generation != state.connect_gen:
                    # Aborted, or superseded by a later attempt. Whatever this
                    # one produced is stale — and an abort is a decision, not a
                    # device failure, so it must not leave an error behind for
                    # the status line to show in red.
                    stream.last_error = ""
                    return
                if ok:
                    state.connected_from = index
                    info = stream.info
                    detail = f" — {info.fs:.0f} Hz · {info.n_channels} ch" if info else ""
                    ctx.log(f"{self._stream_name}: connected to {dev.label}{detail}")
                else:
                    state.connected_from = None
                    ctx.log(f"{self._stream_name}: connect failed — {stream.last_error}")
            except Exception as exc:
                if generation != state.connect_gen:
                    stream.last_error = ""
                    return
                state.connected_from = None
                ctx.log(f"{self._stream_name}: connect failed — {exc}")
            finally:
                if generation == state.connect_gen:
                    state.connecting = False

        threading.Thread(target=run, daemon=True).start()

    # --- status -------------------------------------------------------------
    def _state(self, stream: Stream | None) -> tuple[imgui.ImVec4, str]:
        """State tone and its one-line detail.

        A stream nobody has connected yet is `IDLE`, not `DANGER`: never having
        been asked to attach is not a failure, and a panel that opens red reads
        as a broken app.
        """
        if stream is None:
            return IDLE, "no such stream"
        if self._connecting:
            waited = time.monotonic() - self._connect_started
            return IDLE, f"connecting… {waited:.0f} s"
        info = stream.info
        if stream.status == "connected" and info is not None:
            age = format_age(_last_ts_age(stream))
            return SUCCESS, f"{info.fs:.0f} Hz · {info.n_channels} ch · {age}"
        if stream.last_error:
            return DANGER, stream.last_error
        return IDLE, "not connected"


__all__ = [
    "DEFAULT_DEVICES",
    "LSL_DEVICE",
    "OTB_DEVICES",
    "SYNTHETIC_DEVICE",
    "DeviceSpec",
    "DevicePicker",
    "DeviceParam",
    "DeviceOption",
]
