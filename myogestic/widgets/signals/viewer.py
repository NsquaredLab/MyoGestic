"""Real-time signal viewer.

The public widget is intentionally short; plotting/control internals live in
`myogestic.widgets.signals` helper modules so opening this file gives the reader
the widget flow first.

    from myogestic.widgets import SignalViewer

    viewer = SignalViewer("emg")          # construct once

    @app.ui
    def my_ui(ctx):
        viewer.ui(ctx)                     # render each frame
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from imgui_bundle import imgui

from myogestic.widgets.common import muted
from myogestic.widgets.signals._channel_grid import resolve_scope
from myogestic.widgets.signals._controls import (
    render_channel_controls,
    render_controls,
    render_display_popup,
)
from myogestic.widgets.signals._plot import (
    render_plot,
    robust_channel_ranges,
)
from myogestic.widgets.signals._scan import _disconnected_ui
from myogestic.widgets.signals._state import (
    build_signal_frame,
    get_viewer_state,
    resolve_enabled,
)

if TYPE_CHECKING:
    from myogestic.core import Context


class SignalViewer:
    """Real-time multi-channel signal viewer.

    Construct once with the stable config, then call [`ui`][] with the
    live ``ctx`` each frame. Includes decimation, pause, auto/manual Y
    scale, visual-only display filters, channel toggles, stats, stream
    retargeting, and label markers.

    Parameters
    ----------
    stream_name
        The stable widget ID / stream to view. When ``selectable=True``,
        the user may switch the active stream from the UI — each stream's
        channel selection is tracked separately and restored when the user
        switches back.
    widget_id
        Explicit state / ImGui id scope. Defaults to ``stream_name``. Give each
        viewer its OWN id to show one stream through several panels (e.g. one
        per electrode grid) — otherwise they share a single state and render
        identically. Pair with ``channel_scope`` to give each its own channels,
        and prefer a stable, unique string (grid labels can repeat).
    exclude
        Stream names omitted from the selectable viewer, such as target feedback.
    channel_scope
        The columns this viewer may **ever** show — a hard restriction, unlike
        ``initial_channels`` (which only seeds the opening selection). All /
        None / Invert, the ``N/total`` count, the ``[Edit…]`` grid and
        shift-click ranges are all bounded by it, so a per-electrode-grid panel
        stays its own array however the user clicks. ``None`` (default) is
        unrestricted; an explicit scope that matches no valid column renders
        "no channels in scope" rather than quietly widening back to the whole
        stream. Positional, so with ``selectable=True`` it is re-applied
        (clamped) to whichever stream is shown. Note it also drives the default
        selection: a 64-channel scope opens on its first 16 unless you pass
        ``initial_channels`` too.
    title
        Panel header text. Defaults to ``"SIGNAL · <stream>"`` — set it per
        panel when several viewers share a stream, or every tile reads alike.
    show_connect
        Offer a Connect button in the empty state while the stream is detached.
        Turn it **off** in an app where another widget owns connecting — a
        `StreamPanel` or a `DevicePicker` — or the app ends up with two controls
        named Connect that do different things: this one attaches whatever
        source the stream already holds, a picker's builds a new one from its
        dropdown. They agree only until somebody changes the dropdown.

        Left on by default: an app that is just `App` + `Stream` + a viewer has
        no other way to attach, and nothing attaches on its own.
    show_controls
        Whether the panel's chrome — toolbar, popups and footer —
        starts expanded (default ``True``). The header's ``⌃⌃`` button toggles it
        at runtime and becomes ``⌄⌄`` to unfold it; the title and the toggle stay
        put either way, so a collapsed panel is still identifiable and there is
        always a way back. Pass ``False`` for small tiled panels that should be
        nearly all plot. Dropping the title itself is ``show_title``'s job.
    show_title
        Whether to draw the header row at all (default ``True``). Pass ``False``
        inside a tab or a titled container that already names the panel — a
        `panel_header` under a tab label is the title twice, and the row it
        costs is pure padding. Orthogonal to ``show_controls``, which folds the
        header controls and footer: ``show_title=False, show_controls=True`` is
        an untitled viewer with its full toolbar, popups and footer.
        Note the ``⌃⌃`` collapse toggle lives in that header and goes with it, so
        with no title the chrome is fixed at whatever ``show_controls`` was
        constructed with — intended for a tab, where the chrome is a layout
        decision rather than something the user folds away.
    n_pixels
        Optional hard cap on the points drawn per channel. ``None`` (default)
        means no cap — draw density tracks the plot width via the runtime
        "Detail" slider, which is the normal control. Set it only to force a
        ceiling (e.g. a slow machine with very high channel counts).
    scale_mode
        ``"auto"`` for ImPlot fitting, ``"manual"`` for the user-set
        ``y_range``.
    window_s
        The *initial* display window in seconds — the user can still drag
        the slider afterwards. Defaults to 5 s. The stream's ``buffer_ms``
        must be at least this large.
    initial_channels
        Which channels open enabled, e.g. ``range(16)`` for "the first
        16" — do not pass a bare ``int`` (ambiguous with a single channel
        index). It seeds only the very first selection this viewer resolves;
        a different stream later shown through a ``selectable`` viewer falls
        back to the ``None`` policy. Once a selection exists (here or
        restored from a prior visit), the user's own toggle edits are never
        overwritten. ``None`` (default) falls back to
        `resolve_initial`'s
        policy: every channel when ``n_channels <= 32``, else the first 16.

    Examples
    --------
    >>> from myogestic.widgets import SignalViewer
    >>> viewer = SignalViewer("emg", selectable=True)
    >>> viewer.ui(ctx)
    """

    def __init__(
        self,
        stream_name: str,
        *,
        size: tuple[float, float] = (-1, -1),
        n_pixels: int | None = None,
        channel_height: float = 0.0,
        show_diagnostics: bool = False,
        show_connect: bool = True,
        selectable: bool = False,
        exclude: Iterable[str] = (),
        scale_mode: str = "auto",
        y_range: tuple[float, float] = (-1.0, 1.0),
        show_markers: bool = False,
        window_s: float = 5.0,
        initial_channels: Iterable[int] | None = None,
        widget_id: str | None = None,
        title: str | None = None,
        show_controls: bool = True,
        show_title: bool = True,
        channel_scope: Iterable[int] | None = None,
    ) -> None:
        self._stream_name = stream_name
        # Snapshot the scope: `Iterable` admits a generator, and this is re-read
        # every frame — a lazy one would be exhausted after the first. Order is
        # kept because the default selection takes a prefix of it.
        self._channel_scope = None if channel_scope is None else tuple(channel_scope)
        self._widget_id = widget_id
        self._title = title
        self._show_controls = show_controls
        self._show_title = show_title
        self._show_connect = show_connect
        self._size = size
        self._n_pixels = n_pixels
        self._channel_height = channel_height
        self._show_diagnostics = show_diagnostics
        self._selectable = selectable
        self._excluded = frozenset(exclude)
        self._scale_mode = scale_mode
        self._y_range = y_range
        self._show_markers = show_markers
        self._window_s = window_s
        self._initial_channels = initial_channels

    def ui(self, ctx: Context) -> None:
        """Render the viewer. Call once per frame inside ``@app.ui``."""
        stream_name = self._stream_name
        # Everything below keys off `wid` (state dict + every ImGui id), while the
        # STREAM is looked up by `stream_name` — so N viewers can share one stream
        # (a panel per electrode grid) without sharing each other's state.
        wid = self._widget_id or stream_name
        v = get_viewer_state(
            ctx,
            wid,
            n_pixels=self._n_pixels,
            scale_mode=self._scale_mode,
            y_range=self._y_range,
            show_markers=self._show_markers,
            window_s=self._window_s,
            stream_name=stream_name,
            show_controls=self._show_controls,
        )
        active_stream = v.selected_stream or stream_name
        if active_stream in self._excluded:
            active_stream = stream_name
            v.selected_stream = stream_name
        stream = ctx.streams.get(active_stream)

        connected = stream is not None and stream.status == "connected" and stream.info is not None
        n_channels = stream.info.n_channels if connected else 0
        scope = resolve_scope(self._channel_scope, n_channels)
        enabled = (
            resolve_enabled(v, active_stream, n_channels, self._initial_channels, scope)
            if connected
            else set()
        )
        render_controls(
            ctx,
            wid,
            active_stream,
            stream,
            v,
            self._selectable,
            enabled,
            scope,
            title=self._title,
            show_title=self._show_title,
            exclude=self._excluded,
        )
        if stream is None:
            imgui.text(f"{active_stream}: not found")
            return
        if not connected:
            _disconnected_ui(active_stream, stream, show_connect=self._show_connect)
            return
        if not scope:
            imgui.text_disabled(f"{active_stream}: no channels in scope (stream has {n_channels})")
            if v.show_controls:
                render_display_popup(wid, stream, v, None, enabled, self._show_diagnostics)
            return

        hovered_ch = -1
        if v.show_controls:
            _, _, hovered_ch = render_channel_controls(wid, stream, v, n_channels, scope)
        v.last_hovered = hovered_ch

        frame = build_signal_frame(stream, v, enabled)
        if frame is None:
            imgui.text_disabled(f"{active_stream}: no data")
            if v.show_controls:
                render_display_popup(wid, stream, v, None, enabled, self._show_diagnostics)
            return

        ch_names = stream.info.channel_names

        # `render_plot` derives per-channel ranges from the drawn trace itself
        # (`resolve_channel_ranges`), so none need to be precomputed here.
        channel_ranges = None

        # Honour a "Rescale / Fit & lock" click: fit the current visible data and switch to Manual
        # so it holds. The BASIS carried on `rescale_pending` decides what gets fit — one shared
        # range, or each channel's own lane. Ranges are gained (`plot_channel` draws `data * gain`).
        if v.rescale_pending:
            basis = v.rescale_pending
            v.rescale_pending = None
            ranges = robust_channel_ranges(
                frame.data,
                frame.channel_map,
                v.transient_ms,
                v.window,
                v.display_filter,
                v.rms_window_ms,
                v.rms_hop_ms,
            )
            g = v.gain
            if basis == "per_channel":
                # Fit each enabled channel to its own visible range; replaces the frozen ranges.
                v.pc_ranges = {ch: (lo * g, hi * g) for ch, (lo, hi) in ranges.items()}
                v.scale_mode = "manual"
            elif ranges:
                # Fit one shared range across channels (the pre-existing behaviour).
                lo = min(lo for lo, _ in ranges.values()) * g
                hi = max(hi for _, hi in ranges.values()) * g
                if lo > hi:
                    lo, hi = hi, lo
                span = hi - lo
                pad = span * 0.1 if span > 0 else 1.0
                v.y_min = lo - pad
                v.y_max = hi + pad
                v.scale_mode = "manual"

        if enabled:
            render_plot(
                ctx=ctx,
                stream_name=wid,
                stream=stream,
                v=v,
                frame=frame,
                channel_ranges=channel_ranges,
                enabled=enabled,
                ch_names=ch_names,
                hovered_ch=hovered_ch,
                size=self._size,
                channel_height=self._channel_height,
            )
        else:
            imgui.text("No channels enabled")

        if v.show_controls:
            footer = f"{stream.info.fs:g} Hz · {imgui.get_io().framerate:.0f} fps"
            shift = imgui.get_content_region_avail().x - imgui.calc_text_size(footer).x
            if shift > 0:
                imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + shift)
            imgui.text_colored(muted(), footer)
            render_display_popup(wid, stream, v, frame, enabled, self._show_diagnostics)


__all__ = ["SignalViewer"]
