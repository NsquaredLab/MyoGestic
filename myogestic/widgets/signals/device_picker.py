"""Device selection and connection in the running app.

[`DevicePicker`][] lets operators switch between devices such as Muovi and
Quattrocento or rates such as 2000 Hz and 500 Hz. Configure the device, then
press Connect.

Pass [`DeviceSpec`][] entries to choose the offered hardware.
[`DEFAULT_DEVICES`][] covers the OTB family and network LSL outlets.
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

from myogestic._theme import mono_font
from myogestic.sources.lsl import LSLSource
from myogestic.sources.otb import MuoviSource, QuattrocentoSource, SessantaquattroSource
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
    primary_button,
    segmented,
    stream_chip,
    tinted_row,
    ui_px,
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
        Row label with the operator's unit, such as ``"Channels"`` or
        ``"Sample rate"`` for ``"nch_mode"``.
    choices
        ``{shown: value}``, in the order they should appear. Shown text is
        drawn as a segmented control when the row is wide enough for every
        option at once. Keep it short; ``label`` carries the unit.
    """

    kwarg: str
    label: str
    choices: Mapping[str, Any]


@dataclass(frozen=True)
class DeviceParam:
    """One slider that tunes a connected source while it streams.

    A [`DeviceOption`][] sets a constructor argument on Connect.
    A `DeviceParam` writes a live source attribute for the next chunk,
    preserving the connection, plot history and recording geometry.

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
        Source class or ``functools.partial``, called on Connect with the
        selected options as keyword arguments. Selecting a device leaves the
        running source unchanged.
    options
        The [`DeviceOption`][] rows to draw, in order. Their chosen values are passed
        to ``factory`` as keyword arguments. Each row starts on whichever choice
        matches the factory's *own* default, so leaving them all alone
        reproduces ``factory()`` exactly.
    scan
        ``True`` to discover LSL or serial targets at runtime. Draws a list
        from ``discover()`` and passes the choice to `Stream.reconnect`. Set
        this explicitly; sources with discovery can also use static options.
    live
        [`DeviceParam`][] sliders, shown only once this device is the connected
        one. Use them to tune the running source without disconnecting.
    hint
        One line on what this device *is*, or how it connects. Shown behind an
        ⓘ button beside the dropdown. The button is hidden if both hint
        and steps are empty.
    steps
        The setup procedure, one instruction per entry, rendered as a numbered
        list under the hint.

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
_SESSANTAQUATTRO_HINT = "This PC is the server on port 45454; the device dials in."
_SESSANTAQUATTRO_STEPS = (
    "Join the device's Wi-Fi access point — or set this PC's IP as \"Server IP address\" "
    "on the device's own web page.",
    "Power the device on and wait for it to reach the network.",
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
_SESSANTAQUATTRO_AUX = DeviceOption(
    "include_aux", "AUX + IMU + counters", {"Off": False, "On": True}
)
_QUATTROCENTO_AUX = DeviceOption("include_aux", "AUX IN + accessory", {"Off": False, "On": True})

#: The OT Bioelettronica family. One Sessantaquattro entry covers both it and
#: the ``+``: the accessory-channel count is probed from the ramp counter, not
#: configured, so the two are the same to set up.
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
        "Sessantaquattro / +",
        SessantaquattroSource,
        (
            DeviceOption("nch_mode", "Channels", {"8": 0, "16": 1, "32": 2, "64": 3}),
            DeviceOption("fs_mode", "Sample rate", {"500": 0, "1000": 1, "2000": 2, "4000": 3}),
            DeviceOption("mode", "Detection", _DETECTION),
            _SESSANTAQUATTRO_AUX,
        ),
        hint=_SESSANTAQUATTRO_HINT,
        steps=_SESSANTAQUATTRO_STEPS,
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

    A segmented control keeps alternatives visible and takes one click.
    A narrow panel or long choices use a two-click combo because segments
    cannot wrap or truncate.
    """
    style = imgui.get_style()
    per = style.frame_padding.x * 2.0 + 2.0  # `segmented` overrides item spacing to 2 px
    return sum(imgui.calc_text_size(t).x + per for t in labels) <= avail


def _swap_source(stream: Stream, source: Source, target: str | None = None) -> bool:
    """Attach ``source`` to ``stream``, closing whatever was attached before.

    `Stream.reconnect` only ever (re)connects ``stream._source``, which by the
    time it runs is the replacement object. Disconnect the previous source
    before assigning the replacement. Skipping this for Muovi and
    Sessantaquattro leaks the listening server socket, which
    only their ``disconnect()`` override closes, and the next Connect to the
    same device then fails to bind its fixed port. ``SO_REUSEADDR`` is set on
    both but does not permit binding over a live listener.

    The swap itself is a bare attribute assignment, which is safe against the
    running acquire thread: a freshly constructed source holds no socket and its
    ``read()`` returns ``(None, None)``, and `Stream.reconnect` clears
    ``_connected`` under the stream lock immediately afterwards. Stopping and
    restarting the stream would spawn a second thread; `App.run` owns
    the acquisition thread.

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

    A ``selectable`` picker stores this state separately for each stream.
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

    Use for a named stream in place of `StreamPanel`. The header dot shows
    connection state. Connect applies device settings and attaches hardware;
    changes stay pending until it is pressed.

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
        instance its own value. ImGui combines labels with the enclosing scope
        for control identity. Distinct values keep panels in one `Grid` cell
        from sharing controls.
    selectable
        Show sorted stream chips from ``ctx.streams``, each with a status dot.
        Clicking a chip changes only which stream this panel configures.
    on_add
        Optional callback receiving a cleaned stream name. With ``selectable``,
        adds a trailing plus chip and inline name field. Build a `Stream` and
        pass it to `App.add_stream`; the app owns its geometry.
    on_remove
        Optional callback receiving the selected stream's name; pass
        `App.remove_stream`. The last offered stream cannot be removed.
        Adding and removing are disabled during a recording.
    exclude
        Stream names to exclude. Use for sources owned by another widget, such
        as a `TrackingTask` target or replay. Connecting another source would
        detach its owner and record data under the wrong stream name. This
        frozen set allows streams added at runtime unless named here.
    show_header
        Render the standard ``panel_header``. Turn it off when the surrounding
        layout already names the card; chips and the action area still carry
        the selected stream's state.

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
        on_add: Callable[[str], object] | None = None,
        on_remove: Callable[[str], object] | None = None,
        exclude: Iterable[str] = (),
        widget_id: str | None = None,
    ) -> None:
        self._stream_name = stream
        self._widget_id = widget_id or self._stream_name
        self._devices = tuple(devices)
        self._show_header = show_header
        self._selectable = selectable
        self._on_add = on_add
        self._on_remove = on_remove
        self._adding = False
        self._typed = ""
        self._excluded = frozenset(exclude)
        self._scanning = False
        # Keep device selection, connection attempts and scan results per stream.
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

        Wraps all controls in the ``widget_id`` ImGui scope. Distinct scopes
        keep panels in one `Grid` cell from sharing control identity.
        """
        imgui.push_id(self._widget_id)
        try:
            if self._selectable:
                names = sorted(n for n in ctx.streams if n not in self._excluded)
                if names and self._stream_name not in names:
                    self._select_stream(names[0])
            stream = ctx.streams.get(self._stream_name)
            tone, detail = self._state(stream)

            if self._show_header:
                # Detached state has no separate status row; keep its explanation
                # on the header while live geometry stays in the action area.
                panel_header("Source", fa.ICON_FA_MICROCHIP, status=tone)
                imgui.set_item_tooltip(detail)

            if self._selectable:
                self._stream_row(ctx)
                stream = ctx.streams.get(self._stream_name)

            if stream is None:
                imgui.text_colored(muted(), f"(no stream named {self._stream_name!r})")
                return
            if not self._devices:
                imgui.text_colored(muted(), "(no devices configured)")
                return

            self._selected = min(self._selected, len(self._devices) - 1)
            dev = self._devices[self._selected]
            # Live sliders retain a shared label column below the compact card.
            among = _row_labels(dev)

            style = imgui.get_style()
            info_w = (
                imgui.calc_text_size(fa.ICON_FA_CIRCLE_INFO).x
                + style.frame_padding.x * 2.0
                + style.item_spacing.x
                if dev.hint or dev.steps
                else 0.0
            )
            imgui.set_next_item_width(max(1.0, imgui.get_content_region_avail().x - info_w))
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
            self._live_ui(stream, dev, among)
        finally:
            imgui.pop_id()

    def _stream_row(self, ctx: Context) -> None:
        """Stream chips, with inline add and selected-stream removal."""
        names = sorted(n for n in ctx.streams if n not in self._excluded)
        recording = bool(getattr(ctx, "recording", False))
        style = imgui.get_style()
        left = imgui.get_cursor_pos_x()
        right = left + imgui.get_content_region_avail().x
        remove = None
        for index, name in enumerate(names):
            stream = ctx.streams[name]
            tone = (
                SUCCESS
                if stream.status == "connected" and stream.info is not None
                else DANGER
                if stream.last_error
                else IDLE
            )
            selected = name == self._stream_name
            removable = selected and self._on_remove is not None and len(names) > 1
            clicked, removed = stream_chip(
                name,
                tone,
                selected=selected,
                prefix="dp",
                left=left,
                right=right,
                first=index == 0,
                removable=removable,
                recording=recording,
                detail=stream.last_error or stream.status,
            )
            if clicked:
                self._select_stream(name)
            if removed:
                remove = name
        if remove is not None:
            self._on_remove(remove)
            remaining = sorted(n for n in ctx.streams if n not in self._excluded)
            if remaining and self._stream_name not in remaining:
                self._select_stream(remaining[0])
        if self._on_add is not None:
            if names:
                imgui.same_line()
                plus_w = imgui.calc_text_size(fa.ICON_FA_PLUS).x + 2 * style.frame_padding.x
                if imgui.get_cursor_pos_x() + plus_w > right:
                    imgui.new_line()
            imgui.begin_disabled(recording)
            if imgui.button(f"{fa.ICON_FA_PLUS}##dp_add_open") and not recording:
                self._adding = True
            imgui.end_disabled()
            self._action_tooltip(
                "Stop the recording before adding a stream." if recording else "", "Add a stream."
            )
            if self._adding:
                self._add_row(ctx, recording=recording)

    def _add_row(self, ctx: Context, *, recording: bool) -> None:
        """Collect a name using StreamManager's cleaning and callback contract."""
        # Local to avoid the panels/signals package initialization cycle.
        from myogestic.widgets.panels.stream_manager import _NAME_MAX, _clean_name

        style = imgui.get_style()
        reserve = (
            imgui.calc_text_size("Add").x
            + imgui.calc_text_size(fa.ICON_FA_XMARK).x
            + 4 * style.frame_padding.x
            + 2 * style.item_spacing.x
        )
        imgui.set_next_item_width(max(1.0, imgui.get_content_region_avail().x - reserve))
        imgui.begin_disabled(recording)
        changed, typed = imgui.input_text_with_hint("##dp_new", "e.g. force", self._typed)
        if changed:
            self._typed = typed[:_NAME_MAX]
        imgui.end_disabled()
        cleaned = _clean_name(self._typed)
        if recording:
            reason = "Stop the recording before adding a stream."
        elif not cleaned:
            reason = "Type a name first."
        elif cleaned in ctx.streams:
            reason = f"A stream named {cleaned!r} already exists."
        else:
            reason = ""
        imgui.same_line()
        imgui.begin_disabled(bool(reason))
        if imgui.button("Add##dp_add") and not reason:
            self._on_add(cleaned)
            self._typed = ""
            self._adding = False
            if cleaned in ctx.streams:
                self._select_stream(cleaned)
        imgui.end_disabled()
        self._action_tooltip(reason, f"Add a stream named {cleaned!r}.")
        imgui.same_line()
        if imgui.button(f"{fa.ICON_FA_XMARK}##dp_add_cancel"):
            self._adding = False
            self._typed = ""
        imgui.set_item_tooltip("Cancel adding a stream.")

    def _select_stream(self, name: str) -> None:
        """Point the panel at another stream. Changes nothing but which one is shown.

        Each stream's `_StreamState` retains its selected device, connection
        and scan results when switching away and back.
        """
        self._stream_name = name

    def _hint_popup(self, dev: DeviceSpec, anchor: imgui.ImVec2 | None) -> None:
        """The device's setup instructions, on demand.

        A dismissable popup keeps the OTB procedure's two or three sentences
        visible while the operator follows them.

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
                imgui.push_text_wrap_pos(imgui.get_cursor_pos_x() + ui_px(_HINT_WRAP))
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
                imgui.push_text_wrap_pos(left + gutter + ui_px(_HINT_WRAP))
                imgui.text_unformatted(step)
                imgui.pop_text_wrap_pos()
                imgui.spacing()
        finally:
            imgui.end_popup()

    # --- configuration ------------------------------------------------------
    def _option_ui(self, dev: DeviceSpec, among: Sequence[str]) -> None:
        """Captioned controls in two columns, stacking when a combo cannot fit."""
        options = [opt for opt in dev.options if opt.choices]
        if not options:
            return
        style = imgui.get_style()
        width = imgui.get_content_region_avail().x
        cell = (width - style.item_spacing.x) * 0.5
        minimum = max(
            max(imgui.calc_text_size(label).x for label in opt.choices)
            + imgui.get_frame_height()
            + 2 * style.frame_padding.x
            for opt in options
        )
        columns = 2 if len(options) > 1 and cell >= max(ui_px(90), minimum) else 1
        flags = imgui.TableFlags_.sizing_stretch_same | imgui.TableFlags_.no_pad_outer_x
        if not imgui.begin_table("dp_options", columns, flags):
            return
        try:
            choices = self._choices[self._selected]
            for opt in options:
                imgui.table_next_column()
                imgui.align_text_to_frame_padding()
                imgui.text_colored(muted(), opt.label)
                labels = list(opt.choices)
                current = min(max(choices.get(opt.kwarg, 0), 0), len(labels) - 1)
                available = imgui.get_content_region_avail().x
                imgui.set_next_item_width(available)
                if _fits_segmented(labels, available):
                    choices[opt.kwarg] = segmented(f"dp_{opt.kwarg}", labels, current)
                else:
                    changed, idx = imgui.combo(f"##dp_opt_{opt.kwarg}", current, labels)
                    if changed:
                        choices[opt.kwarg] = idx
        finally:
            imgui.end_table()

    def _scan_ui(self, dev: DeviceSpec, among: Sequence[str]) -> None:
        """An Outlet caption above the target combo and its rescan action."""
        if self._scanned_for != self._selected and not self._scanning:
            self._start_scan(dev)
        imgui.text_colored(muted(), "Outlet")
        style = imgui.get_style()
        rescan_w = imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x + style.frame_padding.x * 2
        right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
        imgui.set_next_item_width(
            max(1.0, imgui.get_content_region_avail().x - rescan_w - style.item_spacing.x)
        )
        labels = [f"{t.get('name', '?')} ({t.get('info', '')})" for t in self._targets]
        if labels and not self._scanning:
            self._target_selected = min(self._target_selected, len(labels) - 1)
            changed, idx = imgui.combo("##dp_target", self._target_selected, labels)
            if changed:
                self._target_selected = idx
        else:
            imgui.begin_disabled()
            imgui.combo("##dp_target", 0, ["scanning…" if self._scanning else "nothing found"])
            imgui.end_disabled()
        imgui.same_line()
        imgui.set_cursor_pos_x(right - rescan_w)
        imgui.begin_disabled(self._scanning)
        if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##dp_scan"):
            self._start_scan(dev)
        imgui.end_disabled()
        self._action_tooltip(
            "Scanning for outlets…" if self._scanning else "", "Rescan for outlets"
        )

    def _start_scan(self, dev: DeviceSpec) -> None:
        """Run ``discover()`` off-thread on a throwaway source.

        Both shipped scan-capable sources use a network query for ``discover()``.
        The probe stays disconnected and needs no teardown, leaving the stream's
        source undisturbed.
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

        from myogestic._browser import IS_BROWSER

        if IS_BROWSER:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def _live_ui(self, stream: Stream, dev: DeviceSpec, among: Sequence[str]) -> None:
        """Sliders that retune the running source, with no reconnect.

        Rendered only while *this* device is the attached one: the sliders write
        straight to ``stream._source``, so showing them for a device the user has
        merely selected would silently retune a different device.

        Check attachment on the stream. ``_connected_from`` records this panel's
        last connection and can remain set when a `StreamManager` or acquisition
        loop detaches the source.
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
        """One compact action area for detached, connecting and connected states."""
        style = imgui.get_style()
        if self._connecting:
            right = imgui.get_cursor_pos_x() + imgui.get_content_region_avail().x
            imgui.align_text_to_frame_padding()
            imgui.text_colored(IDLE, fa.ICON_FA_CIRCLE)
            imgui.same_line()
            mono_text(self._state(stream)[1], muted())
            imgui.same_line()
            abort_w = imgui.calc_text_size("Abort").x + 2 * style.frame_padding.x
            imgui.set_cursor_pos_x(right - abort_w)
            if imgui.button("Abort##dp_abort"):
                self._abort(ctx, stream)
            imgui.set_item_tooltip("Stop waiting for the device.")
            return

        recording = bool(getattr(ctx, "recording", False))
        reason = "Stop the recording before changing device." if recording else ""
        connect_reason = reason or (
            "No target to connect to yet." if dev.scan and not self._targets else ""
        )
        attached = stream.status == "connected" and stream.info is not None
        if attached:
            with tinted_row(SUCCESS) as width:
                right = imgui.get_cursor_pos_x() + width
                reconnect_w = (
                    imgui.calc_text_size(fa.ICON_FA_ARROWS_ROTATE).x + 2 * style.frame_padding.x
                )
                disconnect_w = (
                    imgui.calc_text_size(fa.ICON_FA_PLUG_CIRCLE_XMARK).x + 2 * style.frame_padding.x
                )
                actions_x = right - reconnect_w - disconnect_w - style.item_spacing.x
                imgui.align_text_to_frame_padding()
                imgui.text_colored(SUCCESS, fa.ICON_FA_CIRCLE)
                imgui.same_line()
                detail = self._state(stream)[1]
                font = mono_font()
                if font is not None:
                    imgui.push_font(font, style.font_size_base)
                available = max(0.0, actions_x - imgui.get_cursor_pos_x() - style.item_spacing.x)
                shown = detail
                while shown and imgui.calc_text_size(shown + "…").x > available:
                    shown = shown[:-1]
                if shown != detail:
                    shown = shown + "…" if available >= imgui.calc_text_size("…").x else ""
                mono_text(shown)
                if font is not None:
                    imgui.pop_font()
                imgui.set_item_tooltip(detail)
                imgui.same_line()
                imgui.set_cursor_pos_x(actions_x)
                imgui.begin_disabled(bool(connect_reason))
                if imgui.button(f"{fa.ICON_FA_ARROWS_ROTATE}##dp_connect") and not connect_reason:
                    self._connect(ctx, stream, dev)
                imgui.end_disabled()
                self._action_tooltip(
                    connect_reason, "Reconnect: build this device again and re-attach the stream."
                )
                imgui.same_line()
                imgui.begin_disabled(bool(reason))
                if imgui.button(f"{fa.ICON_FA_PLUG_CIRCLE_XMARK}##dp_disconnect") and not reason:
                    self._disconnect(ctx, stream)
                imgui.end_disabled()
                self._action_tooltip(
                    reason, "Disconnect: close the device and leave the stream detached."
                )
        else:
            imgui.begin_disabled(bool(connect_reason))
            if (
                primary_button(f"{fa.ICON_FA_PLUG}  Connect##dp_connect", (-1, 0))
                and not connect_reason
            ):
                self._connect(ctx, stream, dev)
            imgui.end_disabled()
            self._action_tooltip(connect_reason, "Build this device and attach the stream to it.")
            if stream.last_error:
                mono_text(stream.last_error, DANGER)

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
        the resulting error as an abort without reporting a failure.
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
        Browser apps must offer non-blocking in-process sources; those run
        inline because Pyodide cannot start a worker thread.
        """
        if self._connecting:
            # The button reads Abort while an attempt is in flight, so the UI
            # cannot produce this — but a second attempt would swap the source
            # out from under the first and then be refused by `Stream.reconnect`,
            # leaving nothing connected at all. Refuse it here instead.
            return

        kwargs = _chosen_kwargs(dev, self._choices[self._selected])
        target = (
            self._targets[self._target_selected].get("name") if dev.scan and self._targets else None
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

        from myogestic._browser import IS_BROWSER

        if IS_BROWSER:
            # Browser apps offer in-process sources whose connect is immediate.
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    # --- status -------------------------------------------------------------
    def _state(self, stream: Stream | None) -> tuple[imgui.ImVec4, str]:
        """State tone and its one-line detail.

        Streams awaiting their first connection use `IDLE`. Failed connection
        attempts use `DANGER`.
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
