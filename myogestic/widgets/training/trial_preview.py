"""Stacked-channel waveform with optional shaded band overlay.

Generic trial / template / segment preview widget. Renders multi-channel
biosignal data as stacked traces (per-channel offsets), optionally with
a colored band marking a region of interest (e.g. an extracted
template, a labeled gesture, a chosen training window).

Reusable from any example that wants a recorded-trial review surface.

Design notes:
- Channels-first (default) or samples-first via ``data_layout``. Live
  ``Stream.get_window()`` is channels-first; ``Recording.data`` from
  ``Session.get_trials()`` is samples-first — pass `"samples_first"`
  there instead of transposing at the call site.
- Auto-gain (lane = ``data_range * 1.2``) like ``signal_viewer``'s Auto
  mode, so channels with different amplitudes stay visible. Manual mode
  pins lane to ``y_range``.
- Display filters are explicit kwargs (``rectify`` / ``dc_removal`` /
  ``rms_env`` / ``none``), not coupled to a live viewer's state — the
  caller decides what to mirror.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from myogestic.widgets.signals.transforms import apply_display_filter


def trial_preview(
    widget_id: str,
    data: np.ndarray,
    fs: float,
    *,
    data_layout: Literal["channels_first", "samples_first"] = "channels_first",
    title: str | None = None,
    size: tuple[float, float] = (-1.0, 240.0),
    channel_names: list[str] | None = None,
    band: tuple[float, float] | None = None,
    band_color: tuple[float, float, float, float] | None = None,
    gain: float = 1.0,
    display_filter: Literal["none", "rectify", "dc_removal", "rms_env"] = "none",
    scale_mode: Literal["auto", "manual"] = "auto",
    y_range: tuple[float, float] = (-1.0, 1.0),
    as_window: bool = False,
) -> None:
    """Render stacked multi-channel waveform with optional band overlay.

    Parameters
    ----------
    widget_id
        Stable identity string for ImPlot (combined into plot ids so
        two ``trial_preview`` calls in the same frame don't collide).
    data
        Multi-channel signal. Shape ``(n_channels, n_samples)`` if
        ``data_layout == "channels_first"`` (default) or
        ``(n_samples, n_channels)`` if ``"samples_first"``.
    fs
        Sampling rate in Hz, used for the x-axis labels in seconds.
    title
        Optional header line shown above the plot.
    size
        ImPlot size as ``(width, height)``. ``-1`` width fills the
        available content region.
    channel_names
        Optional per-channel labels. When omitted, channels
        are shown as ``ch0..chN-1``.
    band
        Optional ``(t_start_s, t_end_s)`` shaded band drawn behind
        the traces — useful for marking an extracted template,
        highlighting a labeled segment, etc.
    band_color
        RGBA in ``[0,1]``. Defaults to a soft cyan.
    gain
        Multiplier applied to each channel before plotting. Match
        this to your live viewer's gain knob if you want the preview
        to look like what was on screen.
    display_filter
        Visual-only transform applied to a copy of
        ``data`` before plotting. Same vocabulary as
        ``signal_viewer``'s display dropdown.
    scale_mode
        ``"auto"`` (default) computes the per-lane height
        from the signal's global min/max with 20% padding;
        ``"manual"`` uses ``y_range`` directly.
    y_range
        ``(y_min, y_max)`` used in manual scale mode.
    as_window
        When ``True``, the widget wraps itself in a free-floating
        ImGui window with title ``title``. When ``False`` (default),
        it draws inline at the current cursor position.
    """
    from imgui_bundle import imgui, implot

    # Normalise to channels-first internally.
    if data_layout == "samples_first":
        arr = np.ascontiguousarray(data.T, dtype=np.float64)
    else:
        arr = np.asarray(data, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
        if as_window:
            return
        imgui.text_disabled("(no data)")
        return
    n_ch, n_samp = arr.shape

    # Apply display filter on a samples-first view (apply_display_filter
    # contract). Round-trip back to channels-first.
    if display_filter != "none":
        arr = apply_display_filter(
            arr.T.astype(np.float32, copy=False), display_filter, fs
        ).T.astype(np.float64)

    if as_window:
        imgui.set_next_window_size(imgui.ImVec2(960, 480), imgui.Cond_.first_use_ever)
        title_id = (title or "Trial Preview") + f"###trial_preview_{widget_id}"
        opened, _is_open = imgui.begin(title_id, True)
        if not opened:
            imgui.end()
            return

    if title is not None and not as_window:
        imgui.text(title)

    # `lane` = per-channel vertical spacing. In manual mode it's the user-
    # provided y_range height; in auto mode it's the global data range with
    # 20 % padding (matches signal_viewer's auto behaviour).
    if scale_mode == "manual":
        lane = max(float(y_range[1]) - float(y_range[0]), 1e-9)
    else:
        finite = arr[np.isfinite(arr)]
        if finite.size:
            d_lo = float(finite.min())
            d_hi = float(finite.max())
            lane = max(d_hi - d_lo, 1e-9) * 1.2
        else:
            lane = 1.0
    # The y-axis extent always spans all channels with a half-lane pad on
    # top and bottom — without this, manual mode would show only channel 0
    # and clip channels 1..n_ch-1 below the visible y range.
    y_hi = lane * 0.6
    y_lo = -lane * (n_ch - 1) - lane * 0.6

    xs = np.arange(n_samp, dtype=np.float64) / fs

    flags = implot.Flags_.no_legend | implot.Flags_.no_title
    if implot.begin_plot(
        f"trial_preview##{widget_id}",
        imgui.ImVec2(size[0], size[1]),
        flags=flags,
    ):
        implot.setup_axis(implot.ImAxis_.x1, "time (s)")
        implot.setup_axis_limits(implot.ImAxis_.x1, 0.0, n_samp / fs, implot.Cond_.always)  # type: ignore[attr-defined]
        implot.setup_axis(implot.ImAxis_.y1, flags=implot.AxisFlags_.no_tick_labels)
        implot.setup_axis_limits(implot.ImAxis_.y1, y_lo, y_hi, implot.Cond_.always)  # type: ignore[attr-defined]

        # Band overlay below the traces.
        if band is not None:
            bc = band_color if band_color is not None else (0.4, 0.7, 1.0, 1.0)
            spec = implot.Spec()
            spec.fill_color = imgui.ImVec4(bc[0], bc[1], bc[2], 1.0)
            spec.fill_alpha = bc[3] if len(bc) >= 4 else 0.22
            implot.plot_shaded(
                f"band##{widget_id}",
                np.array([float(band[0]), float(band[1])], dtype=np.float64),
                np.array([y_hi, y_hi], dtype=np.float64),
                np.array([y_lo, y_lo], dtype=np.float64),
                spec,
            )

        for ch in range(n_ch):
            ys = np.ascontiguousarray(arr[ch] * gain - ch * lane, dtype=np.float64)
            label = channel_names[ch] if channel_names and ch < len(channel_names) else f"ch{ch}"
            implot.plot_line(f"{label}##{widget_id}", xs, ys)
        implot.end_plot()

    if as_window:
        imgui.end()
