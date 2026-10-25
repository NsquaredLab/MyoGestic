"""Isometric force tracking — match a trapezoidal target with a live force channel.

The task OT Bioelettronica's own software runs: a trapezoid is drawn as a target, the
subject squeezes a transducer wired to an auxiliary channel, and the two traces are read
against each other on one pair of axes.

The shape and the arithmetic are `myogestic.tracking`; this module is only the surface —
which stream and channel the force comes from, the two calibration captures that make a
percentage mean anything, and the plot. Nothing here is stored per stream: the widget
holds the operator's choices, so a device that drops out and comes back is still the same
task with the same settings.
"""

from __future__ import annotations

import time
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui, implot

from myogestic.tracking import Calibration, Trapezoid
from myogestic.widgets.common import (
    IDLE,
    PALETTE,
    SUCCESS,
    WARNING,
    ensure_implot_style,
    hairline,
    mono_font,
    mono_text,
    muted,
    panel_header,
    plot_legend,
    primary,
    primary_button,
    tinted_row,
    ui_px,
)

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.sources.target import TargetSource
    from myogestic.stream import Stream

#: Editable trapezoid segments, in the order they happen.
_SEGMENT_ROWS: tuple[tuple[str, str], ...] = (
    ("rest_s", "Rest"),
    ("ramp_up_s", "Ramp up"),
    ("hold_s", "Hold"),
    ("ramp_down_s", "Ramp down"),
    ("recover_s", "Recover"),
)

#: One rep is at most ten minutes; the drag rows clamp to it so a fat-fingered
#: entry cannot produce a block nobody will sit through.
_MAX_SEGMENT_S = 600.0
#: Preserve the block-length cap when Reps is edited in the settings popover.
_MAX_REPS = 200
#: A jump larger than this between consecutive trace samples means the panel was not
#: being rendered — a hidden tab, a collapsed cell — not that the force did nothing.
_TRACE_GAP_S = 0.5

#: Finer than this the plot cannot show, and a long block at 240 fps would grow
#: the trace without bound.
_TRACE_MIN_DT = 0.01


def _rep_corners(trap: Trapezoid) -> tuple[list[float], list[float]]:
    """One repetition as a polyline — its corners, not a resampling of it.

    Sampling `Trapezoid.value_at` on a fixed grid rounds every corner and can miss a
    short hold entirely. The six corners are exact at any zoom, and a zero-length
    segment collapses to two points at the same x, which draws as the step it
    actually is.
    """
    steps = (
        (0.0, 0.0),
        (trap.rest_s, 0.0),
        (trap.ramp_up_s, trap.level_pct),
        (trap.hold_s, trap.level_pct),
        (trap.ramp_down_s, 0.0),
        (trap.recover_s, 0.0),
    )
    xs: list[float] = []
    ys: list[float] = []
    t = 0.0
    for dt, level in steps:
        t += dt
        xs.append(t)
        ys.append(level)
    return xs, ys


def _target_curve(trap: Trapezoid, upto: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """One repetition's target, optionally cut ``upto`` seconds into it.

    The cut is the look-ahead: the subject sees the trajectory only as far as it
    is about to be, not the whole shape in advance. A block whose ending is
    visible from the start is one the subject can plan around instead of track,
    which is the opposite of what the task measures.

    Parameters
    ----------
    trap
        The target shape. Only one repetition is drawn — the plot reframes on
        each rep so a five-rep block does not squeeze five trapezoids onto one
        axis, where none of them can be read.
    upto
        Seconds into the repetition to stop drawing at. ``None`` draws all of it.
    """
    xs, ys = _rep_corners(trap)
    if upto is None:
        return np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64)

    cut = max(0.0, min(upto, trap.duration))
    kept_x = [x for x in xs if x <= cut]
    kept_y = ys[: len(kept_x)]
    # The cut almost never lands on a corner, so the line needs its own endpoint —
    # without it the target visibly snaps between corners instead of creeping.
    if not kept_x or kept_x[-1] < cut:
        kept_x.append(cut)
        kept_y.append(trap.value_at(cut))
    return np.array(kept_x, dtype=np.float64), np.array(kept_y, dtype=np.float64)


def _segment_spans(trap: Trapezoid) -> list[tuple[float, float]]:
    """Each segment's ``(start, end)`` inside one repetition, in `_SEGMENT_ROWS` order.

    Read off `_rep_corners`, so the sketch's hover label follows its actual geometry.
    """
    xs, _ = _rep_corners(trap)
    return list(zip(xs[:-1], xs[1:], strict=True))


def _block_note(trap: Trapezoid) -> str:
    """How long the block takes — arithmetic over six fields that nobody does."""
    if trap.reps <= 1:
        return f"{trap.duration:.1f} s"
    return f"{trap.reps} x {trap.duration:.1f} s = {trap.total_duration:.1f} s"


def _sketch(trap: Trapezoid, size: imgui.ImVec2) -> None:
    """Draw one exact repetition as a small preview in the target row."""
    origin = imgui.get_cursor_screen_pos()
    imgui.invisible_button("##tt_sketch", size)
    xs, ys = _rep_corners(trap)
    pad = ui_px(3)
    base = origin.y + size.y - pad
    height = max(size.y - 2 * pad, 0.0)
    points = [
        imgui.ImVec2(
            origin.x + x / max(trap.duration, 1e-9) * size.x,
            base - y / max(trap.level_pct, 1.0) * height,
        )
        for x, y in zip(xs, ys, strict=True)
    ]
    dl = imgui.get_window_draw_list()
    accent = _series_color(0)
    dl.add_line(
        imgui.ImVec2(origin.x, base), imgui.ImVec2(origin.x + size.x, base),
        imgui.get_color_u32(hairline()), thickness=ui_px(1),
    )
    polygon = _distinct(points)
    area = trap.level_pct * (trap.hold_s + (trap.ramp_up_s + trap.ramp_down_s) / 2)
    if len(polygon) >= 3 and area > 0:
        fill = imgui.ImVec4(accent.x, accent.y, accent.z, 0.16)
        dl.add_concave_poly_filled(polygon, imgui.get_color_u32(fill))  # type: ignore
    dl.add_polyline(points, imgui.get_color_u32(accent), thickness=ui_px(1.5), flags=0)  # type: ignore
    if imgui.is_item_hovered() and size.x > 0:
        t = (imgui.get_mouse_pos().x - origin.x) / size.x * trap.duration
        for (start, end), (attr, label) in zip(_segment_spans(trap), _SEGMENT_ROWS, strict=True):
            if start <= t < end:
                imgui.set_tooltip(f"{label} · {getattr(trap, attr):g} s")
                break


def _distinct(points: list[imgui.ImVec2]) -> list[imgui.ImVec2]:
    """``points`` without consecutive repeats — a polygon an ear-clipper can fill."""
    kept: list[imgui.ImVec2] = []
    for point in points:
        if not kept or (point.x, point.y) != (kept[-1].x, kept[-1].y):
            kept.append(point)
    return kept


def _series_color(index: int) -> imgui.ImVec4:
    """`PALETTE` entry `index` as a plot colour — categorical identity, not a ramp."""
    c = PALETTE[index % len(PALETTE)]
    return imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), 1.0)


def _action_tooltip(reason: str, otherwise: str) -> None:
    """Why the action is unavailable, or what it does. Works while disabled."""
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip(reason or otherwise)


def _tracking_text(text: str, width: float, *, mono: bool = False) -> None:
    """Fit a tracking readout on one line and keep its full value in a tooltip."""
    font = mono_font() if mono else None
    if font is not None:
        imgui.push_font(font, imgui.get_style().font_size_base)
    shown = text
    if imgui.calc_text_size(shown).x > width:
        while shown and imgui.calc_text_size(shown + "…").x > width:
            shown = shown[:-1]
        shown = shown + "…" if imgui.calc_text_size("…").x <= width else ""
    if mono:
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, width - imgui.calc_text_size(shown).x))
    if font is not None:
        imgui.pop_font()
    if mono:
        mono_text(shown, primary())
    else:
        imgui.text_unformatted(shown)
    if shown != text:
        _action_tooltip("", text)


class TrackingTask:
    """Force-tracking task: follow a trapezoidal target on an auxiliary channel.

    Pick Stream and Channel, then capture a resting `Calibration.zero` and a maximum
    `Calibration.mvc` in the calibration row. Its warning names the next step and its
    countdown stays beside the capture buttons. The target row previews one repetition;
    its settings icon opens the five durations, Level, Reps and Look ahead. Press Start.
    The target and the subject's normalised force are then drawn on one pair of
    axes — x is task time in seconds, y is percent of MVC — because a following error is
    only readable when both traces share a range. Target and Force chips toggle trace
    visibility. A mono summary below the plot states the total block duration.

    While running, setup is dimmed and locked. The status row shows the repetition,
    phase, current force and signed error (force minus target), with Stop beside it.
    Captions sit above controls in two columns, stacking in narrow cells; long row
    readouts ellipsize and expose their full text on hover.

    The live force is the mean of the last `tail_ms` of the chosen channel, not one
    sample: a single raw sample from a load cell is noise with a force in it.

    Nothing is stored per stream. The stream *name* and the channel *index* are what the
    widget holds, and the index is clamped only where it is used — so an amplifier that
    reconnects at a different channel count does not silently rewrite the operator's
    choice.

    Parameters
    ----------
    stream
        Stream name to start on, as registered with ``app.streams``. May be ``""``: the
        panel offers every stream in ``ctx.streams`` and the choice is made at runtime.
    channel
        Channel index within that stream carrying the force signal.
    trapezoid
        Initial target shape. Every segment is editable in the settings popover; this is only
        where it starts. Defaults to `Trapezoid`'s own defaults.
    target
        Optional `myogestic.sources.target.TargetSource` to drive, so the trajectory is
        *recorded* beside the EMG instead of being reconstructed afterwards from a start
        time and a copy of these settings. The app owns it — register it as a `Stream`
        and pass it here; the task never builds one. Start, Stop and every shape edit
        are forwarded, so what is drawn and what is recorded cannot diverge.
    tail_ms
        How much of the window the live reading averages over. Long enough to be steady,
        short enough that the trace still follows the subject.
    mvc_capture_s
        How long the MVC action watches for a peak after it is pressed.
    widget_id
        ImGui id scope and state key. Defaults to the stream name. Give each
        instance its own when an app renders more than one — two transducers in
        one study is the obvious case: ImGui derives a control's identity from
        its label plus the enclosing scope, and a `Grid` cell is a single child
        window, so two of these in one cell share every slider and both plots
        until they are told apart.
    look_ahead_s
        How far past "now" the target is drawn, in seconds. The subject sees the
        trajectory only as far as it is about to be: a block whose ending is
        visible from the start is one they can plan around instead of track.
    plot_height
        Plot height in pixels at UI scale 1.0; follows the current UI scale.

    Examples
    --------
    >>> from myogestic.tracking import Trapezoid
    >>> from myogestic.widgets import TrackingTask
    >>> task = TrackingTask("emg", channel=64, trapezoid=Trapezoid(level_pct=20.0))
    >>> task.ui(ctx)
    """

    def __init__(
        self,
        stream: str = "",
        *,
        channel: int = 0,
        trapezoid: Trapezoid | None = None,
        target: TargetSource | None = None,
        tail_ms: float = 100.0,
        mvc_capture_s: float = 3.0,
        plot_height: float = 220.0,
        look_ahead_s: float = 4.0,
        widget_id: str | None = None,
    ) -> None:
        self._stream_name = stream
        self._widget_id = widget_id or self._stream_name
        self._channel = max(channel, 0)
        self._target = target
        self._trap = trapezoid if trapezoid is not None else Trapezoid()
        self._set_trap(self._trap)  # so a passed-in target starts on the same shape
        self._tail_s = max(tail_ms, 1.0) / 1000.0
        self._mvc_capture_s = max(mvc_capture_s, 0.0)
        self._plot_height = plot_height
        # Raw signal units, both of them — `Calibration` is what turns them into a
        # percentage, and until both exist there is no percentage to speak of.
        self._zero: float | None = None
        self._mvc: float | None = None
        # An MVC capture in flight: when it ends, and the best seen so far.
        self._mvc_until: float | None = None
        self._mvc_peak: float | None = None
        self._started: float | None = None
        self._look_ahead_s = max(look_ahead_s, 0.0)
        # Which repetition `_trace_t` belongs to. The plot frames one rep at a
        # time, so the trace is kept in rep-local seconds and cleared when the
        # block rolls into the next one.
        self._trace_rep = 0
        self._trace_t: list[float] = []
        self._trace_y: list[float] = []
        self._show_target = True
        self._show_force = True

    # --- logic (no imgui) ----------------------------------------------------
    @property
    def _calibration(self) -> Calibration | None:
        """The two captures as a `Calibration`, or ``None`` until both exist."""
        if self._zero is None or self._mvc is None:
            return None
        return Calibration(zero=self._zero, mvc=self._mvc)

    def _resolve_channel(self, n_channels: int) -> int:
        """Which channel index to actually read, given how many the stream has now.

        Clamped for *use* only. ``self._channel`` keeps the operator's pick, so an
        amplifier that reconnects at 8 channels and then at 64 again comes back to the
        channel they chose rather than to whatever the narrow moment allowed.

        Parameters
        ----------
        n_channels
            Channel count the stream currently reports.
        """
        if n_channels <= 0:
            return 0
        return min(self._channel, n_channels - 1)

    def _mean_tail(self, data: np.ndarray, fs: float) -> float | None:
        """Mean of the last `tail_ms` of the chosen channel of `data`.

        Returns ``None`` when there is nothing to read — no samples, no channels, or a
        rate that cannot size a tail — so callers distinguish "no reading" from a
        reading that happens to be zero.

        Parameters
        ----------
        data
            Channels-first window, as `Stream.get_window` returns it.
        fs
            Sample rate in Hz.
        """
        if data.ndim != 2 or data.shape[0] == 0 or data.shape[1] == 0 or fs <= 0.0:
            return None
        n = min(data.shape[1], max(1, int(fs * self._tail_s)))
        return float(np.mean(data[self._resolve_channel(data.shape[0]), -n:]))

    def _read(self, stream: Stream | None) -> float | None:
        """The current raw force reading, or ``None`` when there is nothing to read."""
        if stream is None:
            return None
        # Bound once: a reconnect on the acquire thread can swap `info` between reads,
        # and a rate belonging to a different buffer would size the wrong tail.
        info = stream.info
        if info is None:
            return None
        data, _ts = stream.get_window()
        return self._mean_tail(data, info.fs)

    def _start_reason(self, stream: Stream | None) -> str:
        """Why Start is unavailable, or ``""`` when it is available.

        Parameters
        ----------
        stream
            The currently selected stream, or ``None`` if there is none.
        """
        if stream is None:
            return "Pick a stream carrying the force channel."
        if self._mvc_until is not None:
            return "Wait for the MVC capture to finish."
        if self._trap.duration <= 0:
            return "Set at least one target duration above zero."
        if self._calibration is None:
            return "Capture Zero and MVC first — the target is a percentage of MVC."
        return ""

    def _set_trap(self, trap: Trapezoid) -> None:
        """Adopt a target shape, and hand it to the recorded target stream.

        The one choke point for every edit path, so the shape on screen is never a
        different shape from the one being written into the recording.
        """
        self._trap = trap
        if self._target is not None:
            self._target.trajectory = trap

    def _start(self, session: object | None = None) -> None:
        """Begin a block, discarding the previous trace.

        Parameters
        ----------
        session
            The recording in progress, if any. The block's calibration and the
            channel it was measured on are written into it here — the force is
            recorded in raw device counts and the target in %MVC, so without the
            two numbers that relate them the tracking error, which is the whole
            point of the task, cannot be recovered from the session later.
        """
        self._note_block(session)
        self._trace_rep = 0
        self._trace_t.clear()
        self._trace_y.clear()
        self._started = time.monotonic()
        if self._target is not None:
            # Its own clock, started in the same frame. The plot is drawn against the
            # widget's; the recording is aligned by the target stream's timestamps, so
            # a frame of skew between the two costs the analysis nothing.
            self._target.start()

    def _note_block(self, session: object | None) -> None:
        """Record what this block was measured against, into the live session.

        Appended rather than overwritten: an operator may recalibrate between
        blocks inside one recording, and a single last-write-wins entry would
        silently misdescribe every block but the last.
        """
        extras = getattr(session, "extras", None)
        if extras is None:
            return  # not recording — the block is not in the data either
        from mne_lsl.lsl import local_clock

        extras.setdefault("force_tracking", []).append(
            {
                "started": float(local_clock()),
                "stream": self._stream_name,
                "channel": self._channel,
                "zero": self._zero,
                "mvc": self._mvc,
                "trapezoid": asdict(self._trap),
            }
        )

    def _stop(self) -> None:
        """End the block. The trace stays on the plot for review."""
        self._started = None
        if self._target is not None:
            self._target.stop()

    def _rep_at(self, task_t: float) -> tuple[int, float]:
        """Which repetition ``task_t`` falls in, and how far into it.

        Reps roll straight on — the recover segment is the rest between them —
        so the block is one continuous recording and only the *plot* reframes.
        """
        span = self._trap.duration
        if span <= 0.0:
            return 0, 0.0
        rep = min(int(task_t // span), max(self._trap.reps - 1, 0))
        return rep, task_t - rep * span

    def _forget_calibration(self) -> None:
        """Drop the calibration, because it no longer describes what is measured.

        Zero and MVC are properties of one channel of one transducer. Carrying
        them across a change of stream or channel would express the new signal's
        raw counts as a percentage of the old one's span — a number that looks
        entirely plausible and is meaningless.
        """
        self._zero = None
        self._mvc = None
        self._mvc_until = None
        self._mvc_peak = None

    def _capture_zero(self, value: float | None) -> None:
        """Take `value` as the resting baseline. A missing reading changes nothing."""
        if value is not None:
            self._zero = value

    def _capture_mvc(self, now: float) -> None:
        """Start watching for a peak, for `mvc_capture_s` seconds from `now`."""
        self._mvc_until = now + self._mvc_capture_s
        self._mvc_peak = None

    def _tick(self, now: float, value: float | None) -> None:
        """Advance the MVC capture and the running trace by one frame.

        Parameters
        ----------
        now
            A monotonic clock reading, in seconds.
        value
            The current raw force reading, or ``None`` if the stream had none.
        """
        if self._mvc_until is not None:
            if value is not None:
                self._mvc_peak = value if self._mvc_peak is None else max(self._mvc_peak, value)
            if now >= self._mvc_until:
                # A capture that saw no sample at all leaves the old MVC alone rather
                # than replacing it with a number nothing measured.
                if self._mvc_peak is not None:
                    self._mvc = self._mvc_peak
                self._mvc_until = None

        if self._started is None:
            return
        t = now - self._started
        if t >= self._trap.total_duration:
            self._stop()  # the block ending is the same event as pressing Stop
            return
        cal = self._calibration
        if value is None or cal is None:
            return
        rep, t = self._rep_at(t)
        if rep != self._trace_rep:
            # A new repetition gets a clean plot. Carrying the last one over
            # would draw two attempts on one axis with nothing telling them
            # apart, which is the squeeze this framing exists to avoid.
            self._trace_rep = rep
            self._trace_t.clear()
            self._trace_y.clear()
        if self._trace_t and t - self._trace_t[-1] < _TRACE_MIN_DT:
            return
        if self._trace_t and t - self._trace_t[-1] > _TRACE_GAP_S:
            # The trace only accumulates while this panel is rendered, and it
            # shares a tab. Joining the two sides of a gap would draw a straight
            # line the subject never produced; a non-finite point breaks the
            # polyline so the hole reads as a hole.
            self._trace_t.append(t)
            self._trace_y.append(float("nan"))
        self._trace_t.append(t)
        self._trace_y.append(cal.normalise(value))

    def _detail(self, now: float, value: float | None) -> str:
        """Current normalised force and signed error, without substituting for lost data."""
        if value is None:
            return "No force reading · reconnect the stream"
        cal = self._calibration
        if cal is None:
            return "Capture zero, then MVC"
        force = cal.normalise(value)
        if self._started is None:
            return f"{force:.0f} % MVC"
        target = self._trap.value_at(now - self._started)
        return f"{force:.0f} % MVC · error {force - target:+.0f} %"

    # --- render --------------------------------------------------------------
    def ui(self, ctx: Context) -> None:
        """Render one card, with setup rows, target settings and a shared-range plot.

        Call once per frame. Every control and popup is scoped by ``widget_id``;
        source selection, calibration, target settings and legend choices belong
        to this instance even when another task shows the same stream.
        """
        imgui.push_id(self._widget_id)
        try:
            now = time.monotonic()
            signal = self._stream_name, self._channel
            stream = ctx.streams.get(self._stream_name)
            value = self._read(stream)
            self._tick(now, value)
            running = self._started is not None
            status = SUCCESS if running else IDLE
            if not running and value is not None and (
                self._calibration is None or self._mvc_until is not None
            ):
                status = WARNING
            panel_header("Force tracking", fa.ICON_FA_ARROW_TREND_UP, status=status)

            imgui.begin_disabled(running)
            try:
                self._source_ui(ctx)
                # A source edit invalidates the captures; the buttons must use the
                # new channel's reading even on the frame the combo changes it.
                if signal != (self._stream_name, self._channel):
                    stream = ctx.streams.get(self._stream_name)
                    value = self._read(stream)
                self._calibration_ui(now, value)
                self._trapezoid_ui()
            finally:
                imgui.end_disabled()

            self._run_ui(ctx, stream, now, value)
            self._legend_ui()
            self._plot_ui(now)
            _tracking_text(_block_note(self._trap), imgui.get_content_region_avail().x, mono=True)
        finally:
            imgui.pop_id()

    def _source_ui(self, ctx: Context) -> None:
        """Place source captions above their controls, stacking in narrow cells."""
        names = sorted(ctx.streams)
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(360) else 1
        if not imgui.begin_table("##tt_source_fields", columns, imgui.TableFlags_.sizing_stretch_same):
            return
        try:
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Stream")
            imgui.set_next_item_width(-1)
            current = names.index(self._stream_name) if self._stream_name in names else -1
            imgui.begin_disabled(not names or self._mvc_until is not None)
            changed, idx = imgui.combo("##tt_stream", current, names or ["Register a force stream"])
            imgui.end_disabled()
            if changed and 0 <= idx < len(names):
                self._stream_name = names[idx]
                self._forget_calibration()

            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Channel")
            stream = ctx.streams.get(self._stream_name)
            info = stream.info if stream is not None else None
            n_channels = info.n_channels if info is not None else 0
            supplied = info.channel_names if info is not None else None
            labels = [
                supplied[i] if supplied is not None and i < len(supplied) else f"ch {i}"
                for i in range(n_channels)
            ]
            imgui.set_next_item_width(-1)
            imgui.begin_disabled(n_channels <= 0 or self._mvc_until is not None)
            changed, idx = imgui.combo(
                "##tt_channel", self._resolve_channel(n_channels), labels or ["Connect the stream"],
            )
            imgui.end_disabled()
            if changed and 0 <= idx < n_channels:
                self._channel = idx
                self._forget_calibration()
        finally:
            imgui.end_table()

    def _calibration_ui(self, now: float, value: float | None) -> None:
        """Keep captures, their values and the MVC countdown in one utility row."""
        capturing = self._mvc_until is not None
        warning = capturing or self._calibration is None
        if capturing:
            note = f"MVC capture… {max(0.0, self._mvc_until - now):.1f} s"
        elif self._calibration is None:
            note = "Capture zero, then MVC"
        else:
            note = f"zero {self._zero:.2f} · MVC {self._mvc:.2f}"
        style = imgui.get_style()
        zero_w = imgui.calc_text_size("Zero").x + 2 * style.frame_padding.x
        mvc_w = imgui.calc_text_size("MVC").x + 2 * style.frame_padding.x
        actions = zero_w + mvc_w + style.item_spacing.x
        with tinted_row(WARNING if warning else None) as width:
            left = imgui.get_cursor_pos_x()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(WARNING if warning else IDLE, fa.ICON_FA_CIRCLE)
            imgui.same_line()
            room = left + width - actions - style.item_spacing.x - imgui.get_cursor_pos_x()
            _tracking_text(note, max(0.0, room), mono=not warning or capturing)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + width - actions)
            imgui.begin_disabled(value is None or capturing)
            if imgui.button("Zero##tt_zero"):
                self._capture_zero(value)
            _action_tooltip(
                "Wait for MVC to finish." if capturing else
                "Connect the force stream first." if value is None else "",
                "Capture the resting reading with the subject relaxed.",
            )
            imgui.same_line()
            if imgui.button("MVC##tt_mvc"):
                self._capture_mvc(now)
            _action_tooltip(
                "Capture in progress." if capturing else
                "Connect the force stream first." if value is None else "",
                f"Push as hard as possible for {self._mvc_capture_s:.0f} s; the peak is kept.",
            )
            imgui.end_disabled()

    def _trapezoid_ui(self) -> None:
        """Summarise the target, with its detailed settings behind a single icon."""
        style = imgui.get_style()
        popup_width = min(imgui.get_content_region_avail().x, ui_px(420))
        durations = "·".join(f"{getattr(self._trap, attr):g}" for attr, _ in _SEGMENT_ROWS)
        note = f"{durations} s · {self._trap.level_pct:g} % · {self._trap.reps} reps"
        with tinted_row() as width:
            left = imgui.get_cursor_pos_x()
            button_w = imgui.get_frame_height()
            sketch_w = min(ui_px(48), width * 0.18)
            _sketch(self._trap, imgui.ImVec2(sketch_w, imgui.get_frame_height()))
            imgui.same_line()
            imgui.align_text_to_frame_padding()
            room = left + width - button_w - style.item_spacing.x - imgui.get_cursor_pos_x()
            _tracking_text(note, max(0.0, room), mono=True)
            imgui.same_line()
            imgui.set_cursor_pos_x(left + width - button_w)
            if imgui.button(f"{fa.ICON_FA_GEAR}##tt_settings", imgui.ImVec2(button_w, 0)):
                imgui.open_popup("##tt_target_settings")
            _action_tooltip("", "Target settings")
        imgui.set_next_window_size(imgui.ImVec2(popup_width, 0))
        if imgui.begin_popup("##tt_target_settings"):
            try:
                imgui.begin_disabled(self._started is not None)
                self._settings_ui()
                imgui.end_disabled()
            finally:
                imgui.end_popup()

    def _settings_ui(self) -> None:
        """Edit the target and look-ahead in a responsive caption-above grid."""
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(360) else 1
        if not imgui.begin_table("##tt_target_fields", columns, imgui.TableFlags_.sizing_stretch_same):
            return
        try:
            for attr, label in _SEGMENT_ROWS:
                imgui.table_next_column()
                imgui.align_text_to_frame_padding()
                imgui.text_colored(muted(), label)
                imgui.set_next_item_width(-1)
                changed, seconds = imgui.drag_float(
                    f"##tt_{attr}", getattr(self._trap, attr), 0.1, 0.0, _MAX_SEGMENT_S,
                    "%.1f s", imgui.SliderFlags_.always_clamp,
                )
                if changed:
                    self._set_trap(replace(self._trap, **{attr: seconds}))
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Level")
            imgui.set_next_item_width(-1)
            changed, level = imgui.slider_float(
                "##tt_level", self._trap.level_pct, 0.0, 100.0,
                "%.0f %% MVC", imgui.SliderFlags_.always_clamp,
            )
            if changed:
                self._set_trap(replace(self._trap, level_pct=level))
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Reps")
            imgui.set_next_item_width(-1)
            changed, reps = imgui.input_int("##tt_reps", self._trap.reps)
            if changed:
                self._set_trap(replace(self._trap, reps=min(max(reps, 1), _MAX_REPS)))
            imgui.table_next_column()
            imgui.align_text_to_frame_padding()
            imgui.text_colored(muted(), "Look ahead")
            imgui.set_next_item_width(-1)
            changed, ahead = imgui.slider_float(
                "##tt_ahead", self._look_ahead_s, 0.0, 15.0, "%.1f s", imgui.SliderFlags_.always_clamp,
            )
            if changed:
                self._look_ahead_s = ahead
            imgui.set_item_tooltip("How far past now the target is drawn; zero hides the future.")
        finally:
            imgui.end_table()

    def _run_ui(self, ctx: Context, stream: Stream | None, now: float, value: float | None) -> None:
        """Show one primary Start, or a running status, error and reachable Stop."""
        if self._started is not None:
            t = now - self._started
            rep, _ = self._rep_at(t)
            phase = self._trap.phase_at(t).replace("_", " ")
            style = imgui.get_style()
            stop_w = imgui.calc_text_size("Stop").x + 2 * style.frame_padding.x
            height = 2 * imgui.get_text_line_height_with_spacing() + 2 * ui_px(4)
            with tinted_row(SUCCESS, height=height) as width:
                left, top = imgui.get_cursor_pos_x(), imgui.get_cursor_pos_y()
                text_w = width - stop_w - style.item_spacing.x
                _tracking_text(f"Rep {rep + 1} of {self._trap.reps} · {phase}", text_w)
                _tracking_text(self._detail(now, value), text_w, mono=True)
                imgui.same_line()
                imgui.set_cursor_pos(imgui.ImVec2(
                    left + width - stop_w, top + (height - 2 * ui_px(4) - imgui.get_frame_height()) / 2,
                ))
                if imgui.button("Stop##tt_stop"):
                    self._stop()
                imgui.set_item_tooltip("End the block. The trace stays on the plot.")
            return

        reason = self._start_reason(stream)
        if not ctx.streams:
            reason = "Register a force stream to begin."
        elif stream is not None and value is None:
            reason = "Connect the force stream to begin."
        if reason and (stream is None or value is None or self._trap.duration <= 0):
            with tinted_row(IDLE if stream is None or value is None else WARNING) as width:
                _tracking_text(reason, width)
        imgui.begin_disabled(bool(reason))
        if primary_button("Start##tt_start", (-1, 0)):
            self._start(getattr(ctx, "session", None))
        _action_tooltip(reason, "Run the block from the top, discarding the last trace.")
        imgui.end_disabled()

    def _legend_ui(self) -> None:
        """Toggle the two categorical traces without changing the captured data."""
        selected = {i for i, show in enumerate((self._show_target, self._show_force)) if show}
        plot_legend([(0, "Target"), (1, "Force")], selected=selected)
        self._show_target, self._show_force = 0 in selected, 1 in selected

    def _plot_ui(self, now: float) -> None:
        """Target and actual on one pair of axes — the only way to read the error.

        Frames **one repetition**: with five reps on one axis none of them can be
        read, and the point of the plot is the gap between two lines. The target
        is drawn only as far as ``look_ahead_s`` past the moment, so the subject
        tracks it rather than planning around a shape they can already see whole.

        The y range is fixed to the target rather than autoscaled: with per-frame
        autoscaling a subject who is 5 % off and one who is 50 % off draw the same
        picture, which is precisely the thing this plot exists to distinguish.
        """
        ensure_implot_style()
        # A degenerate block (every segment zero) is legal; ImPlot needs a
        # non-empty axis anyway.
        span = max(self._trap.duration, 1.0)
        y_hi = max(self._trap.level_pct * 1.4, 10.0)
        if not implot.begin_plot(
            "force tracking##tt_plot",
            imgui.ImVec2(-1, ui_px(self._plot_height)),
            flags=implot.Flags_.no_title | implot.Flags_.no_legend,
        ):
            return
        try:
            implot.setup_axis(implot.ImAxis_.x1, "rep time (s)")
            implot.setup_axis(implot.ImAxis_.y1, "% MVC")
            implot.setup_axis_limits(implot.ImAxis_.x1, 0.0, span, implot.Cond_.always)  # type: ignore
            implot.setup_axis_limits(implot.ImAxis_.y1, -0.08 * y_hi, y_hi, implot.Cond_.always)  # type: ignore

            # Stopped, the whole shape is shown: there is no "now" to be ahead of,
            # and the operator is setting the block up rather than tracking it.
            upto: float | None = None
            if self._started is not None:
                _, rep_t = self._rep_at(now - self._started)
                upto = rep_t + self._look_ahead_s

            spec = implot.Spec()
            spec.line_color = _series_color(0)
            xs, ys = _target_curve(self._trap, upto)
            if self._show_target:
                implot.plot_line("target##tt_target", xs, ys, spec)

            if self._show_force and self._trace_t:
                spec = implot.Spec()
                spec.line_color = _series_color(1)
                spec.line_weight = ui_px(2)
                implot.plot_line(
                    "force##tt_force",
                    np.array(self._trace_t, dtype=np.float64),
                    np.array(self._trace_y, dtype=np.float64),
                    spec,
                )
        finally:
            implot.end_plot()


__all__ = ["TrackingTask"]
