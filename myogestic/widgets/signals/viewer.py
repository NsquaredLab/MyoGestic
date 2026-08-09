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

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import panel_header, panel_header_button
from myogestic.widgets.signals._channel_grid import resolve_scope
from myogestic.widgets.signals._controls import (
    render_channel_controls,
    render_controls,
)
from myogestic.widgets.signals._plot import (
    render_footer,
    render_plot,
    robust_channel_ranges,
)
from myogestic.widgets.signals._scan import _disconnected_ui
from myogestic.widgets.signals._state import (
    build_signal_frame,
    get_viewer_state,
    resolve_enabled,
    select_stream,
)

if TYPE_CHECKING:
    from myogestic.core import Context
    from myogestic.widgets.signals._state import ViewerState


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
        Whether the panel's chrome — control menu, channel bar and footer —
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
        chrome *below* the header: ``show_title=False, show_controls=True`` is
        an untitled viewer with its full control menu, channel bar and footer.
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
        stream = ctx.streams.get(active_stream)

        # The toggle collapses the chrome — control menu, channel bar and footer
        # — leaving the plot and its title, which is what a small tiled panel
        # wants. The title stays either way: it names the panel, and a header
        # that disappears takes the toggle's position with it.
        #
        # Dropping the title is `show_title`'s job, and it takes the whole row —
        # including the ⌃⌃ toggle, the only UI route to `v.show_controls`, so the
        # chrome then stays as constructed. Deliberate, not an oversight: this is
        # for a viewer in a tab, where the label already names the panel and the
        # chrome is the container's decision rather than the user's.
        if self._show_title:
            self._render_header(ctx, v, active_stream)
        if stream is None:
            imgui.text(f"{active_stream}: not found")
            return
        if stream.status != "connected" or stream.info is None:
            _disconnected_ui(active_stream, stream, show_connect=self._show_connect)
            return

        # Resolved before the controls, not after: the channel bar is drawn
        # inline in the control rows, and the frame's column slice plus the plot
        # loop's per-channel decimation must only ever touch enabled columns.
        # Both resolvers are pure functions of `stream.info` and this viewer's
        # own configuration, so nothing here depends on the controls first.
        n_channels = stream.info.n_channels
        # The scope is positional (column indices), so it applies to whichever
        # stream is shown, clamped to that stream's width — never silently
        # relaxed, which would break the "may ever show" contract.
        scope = resolve_scope(self._channel_scope, n_channels)
        if not scope:
            imgui.text_disabled(
                f"{active_stream}: no channels in scope (stream has {n_channels})"
            )
            return
        enabled = resolve_enabled(v, active_stream, n_channels, self._initial_channels, scope)

        # The bar reads/mutates `v.channels` (the same set `enabled` points at)
        # and the grid window reports hover — all applied this frame, so channel
        # toggles and the hover highlight take effect immediately instead of a
        # frame late. Hidden with the rest of the chrome; nothing can be hovered
        # then, so the highlight resets to -1.
        hovered_ch = -1
        if v.show_controls:
            render_controls(
                ctx, wid, active_stream, stream, v, self._selectable, enabled, scope
            )
            _, _, hovered_ch = render_channel_controls(wid, stream, v, n_channels, scope)
        v.last_hovered = hovered_ch

        frame = build_signal_frame(stream, v, enabled)
        if frame is None:
            imgui.text_disabled(f"{active_stream}: no data")
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
            render_footer(
                stream_name=wid,
                stream=stream,
                v=v,
                frame=frame,
                enabled=enabled,
                ch_names=ch_names,
                show_diagnostics=self._show_diagnostics,
            )

    def _render_header(self, ctx: Context, v: ViewerState, active_stream: str) -> None:
        """Draw the header row: title, optional stream arrows, chrome toggle.

        The row reads ``SIGNAL · EMG .......... ‹ › ⌃⌃``. The arrows appear only
        for a ``selectable`` viewer with more than one stream to offer: every
        single-stream app would otherwise carry a pair of arrows that cycle back
        to where they started, which is worse than no arrows at all.

        Parameters
        ----------
        ctx
            The live context, for the streams the arrows cycle through.
        v
            This viewer's state — the arrows and the toggle both write to it.
        active_stream
            The stream currently shown, which names the panel by default.
        """
        collapsed = not v.show_controls
        # The glyph shows what clicking does: fold the chrome away, or unfold it.
        # Collapsing keeps the title — a panel that loses its name is a panel you
        # cannot identify at a glance, and the toggle stays in the same place so
        # it is where you left it.
        chrome = fa.ICON_FA_ANGLES_DOWN if collapsed else fa.ICON_FA_ANGLES_UP
        chrome_tip = (
            "Show controls, channel bar and footer"
            if collapsed
            else "Hide controls, channel bar and footer"
        )
        title = self._title or f"SIGNAL · {active_stream}"
        names = list(ctx.streams) if self._selectable else []
        if len(names) < 2:
            if panel_header_button(title, fa.ICON_FA_CHART_LINE, chrome, tooltip=chrome_tip):
                v.show_controls = not v.show_controls
            return

        # Two groups, not one cluster: the arrows change *which stream the title names*
        # and belong against it, while the chrome toggle acts on the whole panel and
        # stays pinned to the right edge — the same x a viewer with no arrows puts it
        # at, so it does not move when a second stream is registered.
        #
        # `panel_header_button` right-aligns exactly one action, so the arithmetic is
        # repeated here. `small_button` drops only the *vertical* frame padding, so its
        # width is still text + 2 * padding.
        style = imgui.get_style()
        sp = style.item_spacing.x
        pad = style.frame_padding.x * 2
        arrows = (fa.ICON_FA_CHEVRON_LEFT, fa.ICON_FA_CHEVRON_RIGHT)
        arrows_w = sum(imgui.calc_text_size(i).x + pad for i in arrows) + sp
        chrome_w = imgui.calc_text_size(chrome).x + pad
        icon_w = imgui.calc_text_size(fa.ICON_FA_CHART_LINE).x
        inline = imgui.get_content_region_avail().x >= icon_w + sp + arrows_w + sp + chrome_w
        # `reserve` is what makes the *title* yield: it truncates rather than pushing
        # the buttons — or `panel_header`'s right-inset status dot — off the row.
        panel_header(
            title,
            fa.ICON_FA_CHART_LINE,
            reserve=(arrows_w + sp + chrome_w + sp) if inline else 0.0,
        )

        wid = self._widget_id or self._stream_name
        step = 0
        if inline:
            imgui.same_line()  # straight after the title, which is what they act on
        # else: the arrows wrap to their own line, left-aligned under the title.
        if imgui.small_button(f"{arrows[0]}##{wid}_prev_stream"):
            step = -1
        imgui.set_item_tooltip("Previous stream")
        imgui.same_line()
        if imgui.small_button(f"{arrows[1]}##{wid}_next_stream"):
            step = 1
        imgui.set_item_tooltip("Next stream")

        # Right-aligned in both cases, so the toggle is where it was left whether or
        # not the row had to wrap.
        imgui.same_line()
        avail = imgui.get_content_region_avail().x
        if avail > chrome_w:
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + (avail - chrome_w))
        if imgui.small_button(f"{chrome}##{wid}_chrome"):
            v.show_controls = not v.show_controls
        imgui.set_item_tooltip(chrome_tip)
        if step:
            # Wraps, so two buttons reach every stream however many there are. A
            # selection pointing at a stream that has since been unregistered
            # restarts from the first rather than raising.
            cur = names.index(active_stream) if active_stream in names else 0
            select_stream(v, names[(cur + step) % len(names)])


__all__ = ["SignalViewer"]
