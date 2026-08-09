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
    ensure_implot_style,
    hairline,
    label_column,
    mono_text,
    muted,
    panel_header,
    primary,
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

#: Every row label in the panel, so one column width serves all of them and the
#: fields line up as a block rather than as eleven unrelated controls.
_ROWS: tuple[str, ...] = (
    "Stream",
    "Channel",
    "Zero",
    "MVC",
    *(label for _attr, label in _SEGMENT_ROWS),
    "Level",
    "Reps",
    "Look ahead",
)

#: One rep is at most ten minutes; the drag rows clamp to it so a fat-fingered
#: entry cannot produce a block nobody will sit through.
_MAX_SEGMENT_S = 600.0
#: Reps multiply every segment, and the target polyline is rebuilt each frame at six
#: points per rep. A fat-fingered extra zero here is what actually hangs the app — the
#: per-segment cap does not bound it, because this is the field that multiplies them.
_MAX_REPS = 200
#: A jump larger than this between consecutive trace samples means the panel was not
#: being rendered — a hidden tab, a collapsed cell — not that the force did nothing.
_TRACE_GAP_S = 0.5

#: Cap on a field, in frame heights so it follows `ui_scale` instead of pinning to
#: one display. A duration needs a few dozen pixels of drag travel; stretched across
#: a wide panel the rows stop reading as one shape's parameters and become a stack of
#: identical slabs. What the cap frees is where the sketch goes.
_FIELD_EM = 7.0

#: Below this the sketch is dropped rather than squashed — under about this width the
#: ramps are shorter than the line is thick and the shape stops being legible.
_SKETCH_MIN_EM = 4.0

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

    Read off `_rep_corners`, so a lit region cannot drift from the line above it.
    """
    xs, _ = _rep_corners(trap)
    return list(zip(xs[:-1], xs[1:], strict=True))


def _block_note(trap: Trapezoid) -> str:
    """How long the block takes — arithmetic over six fields that nobody does."""
    if trap.reps <= 1:
        return f"{trap.duration:.1f} s"
    return f"{trap.reps} x {trap.duration:.1f} s = {trap.total_duration:.1f} s"


def _sketch(trap: Trapezoid, size: imgui.ImVec2, *, active: int | None = None) -> None:
    """The whole block drawn beside the numbers that define it, and named.

    Every repetition, where the plot frames one, so the two are complementary rather
    than the same picture twice. Ticks under the baseline name the segments; a name is
    dropped when its segment is too narrow to hold one. Drawn from `_rep_corners`, the
    polyline the plot uses, so the preview cannot drift from what runs.

    Height is normalised — this shows the arrangement in *time*, which no field states,
    while Level already states the height. ``active`` is an index into `_SEGMENT_ROWS`
    to light up; pointing at the drawing picks one too.
    """
    style = imgui.get_style()
    dl = imgui.get_window_draw_list()
    origin = imgui.get_cursor_screen_pos()
    # An invisible button rather than a `dummy`: both reserve the rect, but `dummy`
    # registers with id 0 and does not reliably answer `is_item_hovered`, and pointing
    # at the drawing is half of what names a segment.
    imgui.invisible_button("##tt_sketch", size)
    hovering = imgui.is_item_hovered()

    xs, ys = _rep_corners(trap)
    spans = _segment_spans(trap)
    # A block of all-zero segments is legal, and it is what dragging a row to the floor
    # produces on the way somewhere else; both mappings below would divide by zero.
    one = xs[-1]
    span = (one * trap.reps) or 1.0
    peak = max(trap.level_pct, 1.0)
    width = max(size.x, 1.0)

    def at(t: float) -> float:
        """Seconds into the block to a screen x."""
        return origin.x + (t / span) * width

    left, right = origin.x, origin.x + size.x
    line_h = imgui.get_text_line_height()
    pad = style.frame_padding.y

    # Pointing at the drawing names a segment as well as hovering its row. Reduced into
    # the first repetition: every repetition is the same five parameters, so lighting
    # only the one under the pointer would claim they were separate.
    if hovering and one > 0.0:
        into = (((imgui.get_mouse_pos().x - left) / width) * span) % one
        active = next((i for i, (a, b) in enumerate(spans) if a <= into < b), active)

    labels: list[str | None] = []
    for (a, b), (_attr, text) in zip(spans, _SEGMENT_ROWS, strict=True):
        room = at(b) - at(a)
        labels.append(text if imgui.calc_text_size(text).x + style.item_spacing.x <= room else None)
    named = any(label is not None for label in labels)

    note = _block_note(trap)
    note_w = imgui.calc_text_size(note).x
    # The caption gets its own band rather than being laid over the drawing: at more
    # than one rep the top right corner is exactly where the last trapezoid's plateau
    # is, and the two overlapped.
    base = origin.y + size.y - pad - (line_h if named else 0.0)
    top = origin.y + pad + line_h

    accent = _series_color(0)
    fill = imgui.get_color_u32(imgui.ImVec4(accent.x, accent.y, accent.z, 0.16))
    lit = imgui.get_color_u32(imgui.ImVec4(accent.x, accent.y, accent.z, 0.38))
    stroke = imgui.get_color_u32(accent)
    faint = imgui.get_color_u32(hairline())

    dl.add_line(imgui.ImVec2(left, base), imgui.ImVec2(right, base), faint)

    for rep in range(trap.reps):
        offset = rep * one
        points = [
            imgui.ImVec2(at(x + offset), base - (y / peak) * (base - top))
            for x, y in zip(xs, ys, strict=True)
        ]
        # Concave, and de-duplicated: the flat rest and recover run along the
        # baseline so a convex fill wedges across the shape, and a repeated corner
        # (a zero-length segment) defeats the ear-clipper the same way. `points`
        # keeps its repeats — `_light` indexes it, so segment i stays corner i.
        # The ignores are the stub's invariance, not a real mismatch: it declares
        # `List[ImVec2Like]`, and `list` is invariant, so a `list[ImVec2]` is rejected
        # even though every element is an `ImVec2Like`. A `Sequence` in the stub would
        # accept it; we do not own the stub.
        dl.add_concave_poly_filled(_distinct(points), fill)  # type: ignore
        if active is not None:
            _light(dl, points, active, base, top, lit, faint)
        # Keywords, not positions: `add_polyline`'s last two parameters swapped order
        # between imgui_bundle 1.92.601 and 1.92.801, so a positional call is correct
        # on one and a TypeError on the other. The names did not change.
        dl.add_polyline(points, stroke, thickness=2.0, flags=0)  # type: ignore

    if named:
        for i, text in enumerate(labels):
            dl.add_line(
                imgui.ImVec2(at(spans[i][0]), base), imgui.ImVec2(at(spans[i][0]), base + pad), faint
            )
            if text is None:
                continue
            centre = (at(spans[i][0]) + at(spans[i][1])) * 0.5
            tone = primary() if i == active else muted()
            dl.add_text(
                imgui.ImVec2(centre - imgui.calc_text_size(text).x * 0.5, base + pad),
                imgui.get_color_u32(tone),
                text,
            )
        dl.add_line(imgui.ImVec2(at(one), base), imgui.ImVec2(at(one), base + pad), faint)

    read_w = 0.0
    if active is not None:
        attr, text = _SEGMENT_ROWS[active]
        read = f"{text}  {getattr(trap, attr):.1f} s"
        read_w = imgui.calc_text_size(read).x + style.item_spacing.x
        dl.add_text(imgui.ImVec2(left, origin.y), imgui.get_color_u32(primary()), read)
    if note_w + read_w <= size.x:
        dl.add_text(imgui.ImVec2(right - note_w, origin.y), imgui.get_color_u32(muted()), note)


def _distinct(points: list[imgui.ImVec2]) -> list[imgui.ImVec2]:
    """``points`` without consecutive repeats — a polygon an ear-clipper can fill."""
    kept: list[imgui.ImVec2] = []
    for point in points:
        if not kept or (point.x, point.y) != (kept[-1].x, kept[-1].y):
            kept.append(point)
    return kept


def _light(
    dl: imgui.ImDrawList,
    points: list[imgui.ImVec2],
    active: int,
    base: float,
    top: float,
    lit: int,
    faint: int,
) -> None:
    """Fill one segment of one repetition brighter, and rule its two edges.

    Segment ``i`` spans corners ``i`` and ``i + 1``, read off the points already placed
    so the highlight cannot land beside the segment it names. A zero-length one has no
    area, and its two rules land on each other — the boundary it collapsed to.
    """
    start, end = points[active], points[active + 1]
    if end.x > start.x:
        dl.add_concave_poly_filled(
            [imgui.ImVec2(start.x, base), start, end, imgui.ImVec2(end.x, base)], lit
        )
    for x in (start.x, end.x):
        dl.add_line(imgui.ImVec2(x, base), imgui.ImVec2(x, top), faint)


def _series_color(index: int) -> imgui.ImVec4:
    """`PALETTE` entry `index` as a plot colour — categorical identity, not a ramp."""
    c = PALETTE[index % len(PALETTE)]
    return imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), 1.0)


def _action_tooltip(reason: str, otherwise: str) -> None:
    """Why the action is unavailable, or what it does. Works while disabled."""
    if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
        imgui.set_tooltip(reason or otherwise)


class TrackingTask:
    """Force-tracking task: follow a trapezoidal target on an auxiliary channel.

    Pick the stream and the channel the force transducer is on, capture a resting
    `Calibration.zero` and a maximum `Calibration.mvc`, shape the `Trapezoid`, press
    Start. The target and the subject's normalised force are then drawn on one pair of
    axes — x is task time in seconds, y is percent of MVC — because a following error is
    only readable when both traces share a range.

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
        Initial target shape. Every segment stays editable in the panel; this is only
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
        Plot height in pixels.

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
        """The one status line under the buttons.

        Parameters
        ----------
        now
            A monotonic clock reading, in seconds.
        value
            The current raw force reading, or ``None`` if the stream had none.
        """
        if self._mvc_until is not None:
            return f"MVC capture… {max(0.0, self._mvc_until - now):4.1f} s"
        cal = self._calibration
        if cal is None:
            return "not calibrated — capture Zero and MVC"
        shown = f"{cal.normalise(value):5.1f}" if value is not None else "    —"
        if self._started is None:
            return f"ready · now {shown} %MVC"
        t = now - self._started
        target = self._trap.value_at(t)
        rep, rep_t = self._rep_at(t)
        counter = f"rep {rep + 1}/{self._trap.reps} · " if self._trap.reps > 1 else ""
        return (
            f"{counter}{self._trap.phase_at(t):9} · {rep_t:5.1f} s · "
            f"{shown} / {target:5.1f} %MVC"
        )

    # --- render --------------------------------------------------------------
    def ui(self, ctx: Context) -> None:
        """Render the task. Call once per frame.

        Everything below is drawn inside an ImGui id scope named by
        ``widget_id``. ImGui derives a control's identity from its label plus the
        enclosing scope, and a `Grid` cell is one child window — so without this,
        two of these panels in a single cell would share every control. Pushed
        around the whole body rather than prefixed onto each label, because a
        prefix has to be remembered at every site and this cannot be forgotten.
        """
        imgui.push_id(self._widget_id)
        try:
            names = sorted(ctx.streams)
            stream = ctx.streams.get(self._stream_name)
            now = time.monotonic()
            value = self._read(stream)
            self._tick(now, value)

            running = self._started is not None
            panel_header(
                "Force tracking",
                fa.ICON_FA_ARROW_TREND_UP,
                status=SUCCESS if running else IDLE,
            )
            if not names:
                imgui.text_colored(muted(), "(no streams registered)")
                return

            self._source_ui(names, stream)
            self._calibration_ui(now, value)
            self._trapezoid_ui()

            imgui.spacing()
            self._run_ui(stream, running, getattr(ctx, "session", None))
            mono_text(self._detail(now, value), muted())
            self._view_ui()
            self._plot_ui(now)
        finally:
            imgui.pop_id()

    def _source_ui(self, names: list[str], stream: Stream | None) -> None:
        """What channel of what stream the force is on — both picked at runtime."""
        imgui.separator_text("Source")
        field = imgui.get_frame_height() * _FIELD_EM
        label_column("Stream", _ROWS, max_width=field)
        # -1 when the chosen stream is gone: the name is kept, not reset, so the panel
        # reattaches by itself if the app registers it again.
        current = names.index(self._stream_name) if self._stream_name in names else -1
        changed, idx = imgui.combo("##tt_stream", current, names)
        if changed and 0 <= idx < len(names):
            self._stream_name = names[idx]
            self._forget_calibration()

        info = stream.info if stream is not None else None
        n_channels = info.n_channels if info is not None else 0
        label_column("Channel", _ROWS, max_width=field)
        if n_channels <= 0:
            imgui.text_colored(muted(), "not connected")
            return
        supplied = info.channel_names if info is not None else None
        labels = [
            supplied[i] if supplied is not None and i < len(supplied) else f"ch {i}"
            for i in range(n_channels)
        ]
        changed, idx = imgui.combo("##tt_channel", self._resolve_channel(n_channels), labels)
        if changed and 0 <= idx < n_channels:
            self._channel = idx
            self._forget_calibration()

    def _calibration_ui(self, now: float, value: float | None) -> None:
        """The two captures that give a percentage its meaning, each with its value.

        Locked while a block runs. Re-zeroing mid-block rescales only the points
        drawn *after* the click, leaving one polyline stitched from two
        normalisations with nothing marking the seam — a cliff the subject never
        produced, in the trace the whole task exists to measure.
        """
        locked = self._started is not None
        if locked:
            imgui.begin_disabled()
        try:
            self._capture_rows(now, value)
        finally:
            if locked:
                imgui.end_disabled()
        if locked and imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
            imgui.set_tooltip("Stop the block first — recalibrating mid-block breaks the trace.")

    def _capture_rows(self, now: float, value: float | None) -> None:
        """The Zero and MVC capture rows themselves."""
        imgui.separator_text("Calibration")
        field = imgui.get_frame_height() * _FIELD_EM
        width = label_column("Zero", _ROWS, max_width=field)
        button = imgui.ImVec2(width, 0)
        if imgui.button(f"{fa.ICON_FA_CROSSHAIRS}  Capture##tt_zero", button):
            self._capture_zero(value)
        imgui.set_item_tooltip("Take the resting reading, with the subject relaxed.")
        imgui.same_line()
        mono_text("—" if self._zero is None else f"{self._zero:+.4g}", muted())

        label_column("MVC", _ROWS, max_width=field)
        capturing = self._mvc_until is not None
        if capturing:
            imgui.begin_disabled()
        if imgui.button(f"{fa.ICON_FA_HAND_FIST}  Capture##tt_mvc", button):
            self._capture_mvc(now)
        _action_tooltip(
            "Capture in progress." if capturing else "",
            f"Push as hard as possible for {self._mvc_capture_s:.0f} s; the peak is kept.",
        )
        if capturing:
            imgui.end_disabled()
        imgui.same_line()
        mono_text("—" if self._mvc is None else f"{self._mvc:+.4g}", muted())

    def _trapezoid_ui(self) -> None:
        """Every segment of the target, plus its level and repetition count.

        `Trapezoid` is frozen and validates on construction, so each row clamps to the
        range that dataclass accepts — an edit can change the shape but never raise.
        """
        imgui.separator_text("Target")
        self._shape_ui()

        field = imgui.get_frame_height() * _FIELD_EM
        # A slider, where the durations are drags: this one is a proportion with both
        # ends meaningful, so the handle's position is itself the read-out. The
        # durations have no natural maximum and a handle would imply one.
        label_column("Level", _ROWS, max_width=field)
        changed, level = imgui.slider_float(
            "##tt_level",
            self._trap.level_pct,
            0.0,
            100.0,
            "%.0f %% MVC",
            imgui.SliderFlags_.always_clamp,
        )
        if changed:
            self._set_trap(replace(self._trap, level_pct=level))

        label_column("Reps", _ROWS, max_width=field)
        changed, reps = imgui.input_int("##tt_reps", self._trap.reps)
        if changed:
            self._set_trap(replace(self._trap, reps=min(max(reps, 1), _MAX_REPS)))

    def _shape_ui(self) -> None:
        """The five durations, with the shape they add up to drawn beside them.

        Grouped so the sketch can be given the group's exact height and sit against
        the rows it explains, rather than as a banner above them with no relation to
        any particular one.
        """
        field = imgui.get_frame_height() * _FIELD_EM
        # Which row the pointer is on, for the sketch to light up. Read as the rows are
        # drawn and used in the same frame — the sketch comes after them — so there is
        # no state to carry and the highlight cannot lag the pointer by a frame.
        active: int | None = None
        imgui.begin_group()
        for index, (attr, label) in enumerate(_SEGMENT_ROWS):
            label_column(label, _ROWS, max_width=field)
            changed, seconds = imgui.drag_float(
                f"##tt_{attr}",
                getattr(self._trap, attr),
                0.1,
                0.0,
                _MAX_SEGMENT_S,
                "%.1f s",
                imgui.SliderFlags_.always_clamp,
            )
            # `active` as well as hovered: a drag holds the row while the pointer runs
            # far off it, and that is exactly when watching the segment resize matters.
            if imgui.is_item_hovered() or imgui.is_item_active():
                active = index
            if changed:
                self._set_trap(replace(self._trap, **{attr: seconds}))
        imgui.end_group()

        # Measured off the group rather than after `same_line`: past the call the
        # cursor has already moved and the width read is the whole row, which is the
        # bug that puts a right-hand item off the panel edge.
        rows = imgui.get_item_rect_size()
        spacing = imgui.get_style().item_spacing.x
        room = imgui.get_content_region_avail().x - rows.x - spacing
        if room >= imgui.get_frame_height() * _SKETCH_MIN_EM:
            imgui.same_line()
            _sketch(self._trap, imgui.ImVec2(room, rows.y), active=active)

    def _view_ui(self) -> None:
        """How much of the target the subject can see coming.

        A display setting, not part of the trajectory — it changes what is on screen,
        not what is being asked for, so it does not belong on `Trapezoid` and is not
        recorded with the block. It sits with the plot it governs for the same reason.
        """
        label_column("Look ahead", _ROWS, max_width=imgui.get_frame_height() * _FIELD_EM)
        changed, ahead = imgui.slider_float(
            "##tt_ahead", self._look_ahead_s, 0.0, 15.0, "%.1f s", imgui.SliderFlags_.always_clamp
        )
        if changed:
            self._look_ahead_s = ahead
        imgui.set_item_tooltip(
            "How far past now the target is drawn. Zero shows only what has already "
            "happened; a full rep's worth shows the whole shape in advance."
        )

    def _run_ui(self, stream: Stream | None, running: bool, session: object | None) -> None:
        """Full-width primary action, disabled with the reason in its tooltip."""
        full = imgui.ImVec2(-1, 0)
        if running:
            if imgui.button(f"{fa.ICON_FA_STOP}  Stop##tt_stop", full):
                self._stop()
            imgui.set_item_tooltip("End the block. The trace stays on the plot.")
            return

        reason = self._start_reason(stream)
        blocked = bool(reason)
        if blocked:
            imgui.begin_disabled()
        if imgui.button(f"{fa.ICON_FA_PLAY}  Start##tt_start", full):
            self._start(session)
        _action_tooltip(reason, "Run the block from the top, discarding the last trace.")
        if blocked:
            imgui.end_disabled()

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
            imgui.ImVec2(-1, self._plot_height),
            flags=implot.Flags_.no_title,
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
            implot.plot_line("target##tt_target", xs, ys, spec)

            if self._trace_t:
                spec = implot.Spec()
                spec.line_color = _series_color(1)
                spec.line_weight = 2.0
                implot.plot_line(
                    "force##tt_force",
                    np.array(self._trace_t, dtype=np.float64),
                    np.array(self._trace_y, dtype=np.float64),
                    spec,
                )
        finally:
            implot.end_plot()


__all__ = ["TrackingTask"]
