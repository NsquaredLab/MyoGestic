"""Runtime-tunable filter widget for prediction-output vectors.

Pick one filter from an **extensible** palette, tune it live, and use the
holder as a callable in your ``@pipeline.predict`` body. ``FilterProcessor``
is the general widget; ``PostProcessor`` is the ready-made preset for
smoothing the model's output before it's sent out::

    from myogestic.widgets import PostProcessor

    output_filter = PostProcessor(hz=32)          # three built-in filters

    @pipeline.predict
    def predict(model, features):
        pred = model.predict(features.reshape(1, -1))[0]
        pred = output_filter(pred)                # uses the selected filter
        outlet.push(pred)

    @app.ui
    def ui(ctx):
        output_filter.ui()                        # compact row and settings popover

Register your own filters by passing ``FilterSpec``s to ``FilterProcessor``
(want a *chain* of filters as one entry? compose them with
[`myogestic.outputs.chain`][])::

    from myogestic.outputs import GaussianFilter, chain
    from myogestic.widgets import FilterProcessor, FilterSpec, FilterParam, BUILTIN_FILTERS

    my = FilterSpec(
        key="my", name="My filter",
        build=lambda *, hz, gain: GaussianFilter(int(gain)),
        params=(FilterParam("gain", "gain", 1, 10, 3, kind="int"),),
        description="A custom smoother.",
    )
    proc = FilterProcessor([*BUILTIN_FILTERS, my], hz=32)
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.outputs.filters import OneEuroFilter, VectorFilter, make_filter
from myogestic.widgets.common import (
    _truncate_to_width,
    mono_text,
    muted,
    panel_header_button,
    pop_selected,
    push_selected,
    ui_px,
)

Scalar = float | int

@dataclass(frozen=True, slots=True)
class FilterParam:
    """One tunable slider for a [`FilterSpec`][].

    Parameters
    ----------
    key
        Keyword name passed to the spec's ``build`` / ``reconfigure``.
    label
        Slider label shown in the panel.
    min, max, default
        Slider bounds and initial value. ``min <= default <= max``.
    kind
        ``"int"`` (uses an integer slider) or ``"float"``.
    fmt
        ImGui display format; a sensible default is used per ``kind``.
    log
        Logarithmic slider (float only) — handy for wide ranges like ``beta``.

    Examples
    --------
    >>> from myogestic.widgets import FilterParam
    >>> parameter = FilterParam("sigma", "sigma", 0.1, 10.0, 1.0)
    """

    key: str
    label: str
    min: float
    max: float
    default: float
    kind: Literal["int", "float"] = "float"
    fmt: str = ""
    log: bool = False


@dataclass(frozen=True, slots=True)
class FilterSpec:
    """One selectable filter in a [`FilterProcessor`][] palette.

    Parameters
    ----------
    key
        Stable identifier (e.g. ``"one_euro"``) — used for ``default=``
        selection and ImGui id scoping. Distinct from the display ``name``.
    name
        Button label shown in the panel (e.g. ``"One Euro"``).
    build
        Factory ``build(*, hz, **params) -> VectorFilter`` — constructs the
        filter from the current parameter values.
    params
        Tunable sliders. Empty for a fixed filter (e.g. identity).
    description
        Muted description shown above the parameter controls.
    reconfigure
        Optional in-place update ``reconfigure(current, *, hz, params) ->
        VectorFilter``. When set, live tuning mutates the existing filter
        (preserving its smoothing history) instead of rebuilding it. Return
        the same object (or a replacement). ``None`` -> rebuild via ``build``.
    delay
        Optional ``delay(hz, params) -> float`` returning the filter's
        latency estimate in **milliseconds** — shown live in monospace.
        ``None`` (e.g. a passthrough) displays zero delay.

    Examples
    --------
    >>> from myogestic.outputs.filters import IdentityFilter
    >>> from myogestic.widgets import FilterSpec
    >>> spec = FilterSpec(key="identity", name="Identity", build=lambda **_: IdentityFilter())
    """

    key: str
    name: str
    build: Callable[..., VectorFilter]
    params: tuple[FilterParam, ...] = ()
    description: str = ""
    reconfigure: Callable[..., VectorFilter] | None = None
    delay: Callable[[float, Mapping[str, Any]], float] | None = None


# --- Built-in filters ------------------------------------------------------


def _reconfigure_one_euro(
    current: VectorFilter, *, hz: float, params: Mapping[str, Any]
) -> VectorFilter:
    # Mutate in place so live tuning keeps the filter's smoothing history —
    # rebuilding would pass the next sample straight through (a visible jump).
    assert isinstance(current, OneEuroFilter)
    current.min_cutoff_hz = params["min_cutoff_hz"]
    current.beta = params["beta"]
    current.derivative_cutoff_hz = params["derivative_cutoff_hz"]
    return current


def _gaussian_delay(hz: float, params: Mapping[str, Any]) -> float:
    # Group delay of the rolling average (ms) — half the window.
    return (params["n_vectors"] / 2.0) * (1000.0 / hz)


def _one_euro_delay(hz: float, params: Mapping[str, Any]) -> float:
    # Low-pass time constant at rest (ms); lag shrinks as motion speeds up.
    return 1000.0 / (2.0 * math.pi * params["min_cutoff_hz"])


def _format_delay(ms: float) -> str:
    """Delay as ``ms`` under 1000, else seconds."""
    return f"{ms:.0f} ms" if ms < 1000.0 else f"{ms / 1000.0:.1f} s"


#: The three filters shipped with MyoGestic — pass to ``FilterProcessor`` and
#: extend, or use the ``PostProcessor`` preset which selects these.
BUILTIN_FILTERS: tuple[FilterSpec, ...] = (
    FilterSpec(
        key="identity",
        name="Identity",
        build=partial(make_filter, "identity"),
        description="Passthrough — no smoothing.",
    ),
    FilterSpec(
        key="gaussian",
        name="Gaussian",
        build=partial(make_filter, "gaussian"),
        params=(
            FilterParam("n_vectors", "window (samples)", 1, 30, 5, kind="int"),
            FilterParam("sigma", "sigma", 0.1, 10.0, 1.0, fmt="%.2f"),
        ),
        description="Window sets averaging length; sigma sets how broadly samples are weighted.",
        delay=_gaussian_delay,
    ),
    FilterSpec(
        key="one_euro",
        name="One Euro",
        build=partial(make_filter, "one_euro"),
        params=(
            FilterParam("min_cutoff_hz", "min cutoff", 0.01, 10.0, 1.0, fmt="%.2f Hz"),
            FilterParam("beta", "beta", 0.0, 1.0, 0.02, fmt="%.3f", log=True),
            FilterParam("derivative_cutoff_hz", "d cutoff", 0.01, 10.0, 1.0, fmt="%.2f Hz"),
        ),
        description="Min cutoff smooths rest; beta follows fast moves; d cutoff smooths velocity.",
        reconfigure=_reconfigure_one_euro,
        delay=_one_euro_delay,
    ),
)


# --- The widget ------------------------------------------------------------


class FilterProcessor:
    """Pick-one-and-tune filter widget over an extensible palette.

    Construct once with the filters it offers, call it on a vector inside
    ``@pipeline.predict``, and render it each frame with [`ui`][]. The
    active filter is applied by `__call__`; parameter values are cached
    per filter across selection changes (switching away and back builds a
    fresh filter — no stale history). The full panel has an icon-only Reset,
    a mono delay readout, and captioned sliders with right-aligned mono values.
    Parameter controls use two columns when space permits and one in narrow cells.

    Parameters
    ----------
    filters
        Ordered palette of [`FilterSpec`][]. Defaults to the three
        built-ins (`BUILTIN_FILTERS`).
    hz
        Sample rate forwarded to filters that need it (e.g. one_euro).
    default
        ``key`` of the filter selected on start. ``None`` selects the first.
    title
        Panel header text.
    widget_id
        ImGui id scope — give each instance a unique value if you render more
        than one.

    Examples
    --------
    >>> from myogestic.widgets import FilterProcessor
    >>> processor = FilterProcessor(default="identity")
    >>> processor.ui()
    """

    def __init__(
        self,
        filters: Sequence[FilterSpec] = BUILTIN_FILTERS,
        *,
        hz: float = 50.0,
        default: str | None = None,
        title: str = "FILTER",
        widget_id: str = "filter",
    ) -> None:
        specs = tuple(filters)
        if not specs:
            raise ValueError("FilterProcessor needs at least one filter")
        keys = [s.key for s in specs]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate filter keys: {keys}")
        for s in specs:
            pkeys = [p.key for p in s.params]
            if len(set(pkeys)) != len(pkeys):
                raise ValueError(f"filter {s.key!r} has duplicate param keys: {pkeys}")
            for p in s.params:
                if not (p.min <= p.default <= p.max):
                    raise ValueError(
                        f"{s.key}.{p.key}: default {p.default} out of [{p.min}, {p.max}]"
                    )
        self._specs = specs
        self._by_key = {s.key: s for s in specs}
        self._hz = hz
        self._title = title
        self._widget_id = widget_id
        self._lock = threading.Lock()
        # Live parameter values, per filter, cached across selection changes.
        self._values: dict[str, dict[str, Scalar]] = {
            s.key: {
                p.key: (int(p.default) if p.kind == "int" else float(p.default)) for p in s.params
            }
            for s in specs
        }
        if default is None:
            self._selected = specs[0].key
        elif default in self._by_key:
            self._selected = default
        else:
            raise ValueError(f"default {default!r} not one of {keys}")
        self._filter: VectorFilter = self._build_selected()

    # -- Domain API ---------------------------------------------------------

    @property
    def name(self) -> str:
        """``key`` of the currently selected filter."""
        return self._selected

    @property
    def filter(self) -> VectorFilter:
        """The live filter instance.

        Read-only handle for inspection; mutating or calling it directly
        bypasses the processor's lock and parameter tracking.
        """
        return self._filter

    def __call__(self, x: np.ndarray, timestamp: float | None = None) -> np.ndarray:
        """Apply the selected filter to vector ``x`` at ``timestamp``."""
        with self._lock:
            return self._filter(x, timestamp)

    def reset(self) -> None:
        """Clear the active filter's smoothing history."""
        with self._lock:
            self._filter.reset()

    def _build_selected(self) -> VectorFilter:
        spec = self._by_key[self._selected]
        return spec.build(hz=self._hz, **self._values[self._selected])

    def _select(self, key: str) -> None:
        with self._lock:
            self._selected = key
            self._filter = self._build_selected()

    def _apply_param(self, key: str, value: Scalar) -> None:
        spec = self._by_key[self._selected]
        with self._lock:
            self._values[self._selected][key] = value
            if spec.reconfigure is not None:
                self._filter = spec.reconfigure(
                    self._filter, hz=self._hz, params=self._values[self._selected]
                )
            else:
                self._filter = self._build_selected()

    # -- UI -----------------------------------------------------------------

    def ui(self) -> None:
        """Render the full panel. Call once per frame inside ``@app.ui``."""
        imgui.push_id(self._widget_id)
        try:
            self._render()
        finally:
            imgui.pop_id()

    def _render(self) -> None:
        if panel_header_button(
            self._title, fa.ICON_FA_WAVE_SQUARE, fa.ICON_FA_ROTATE_LEFT,
            tooltip="Clear smoothing history (e.g. on a new session).",
        ):
            self.reset()
        self._render_combo()
        spec = self._by_key[self._selected]
        delay = spec.delay(self._hz, self._values[self._selected]) if spec.delay else 0.0
        mono_text(_format_delay(delay), muted())
        self._render_description()
        self._render_params()

    def _render_description(self) -> None:
        spec = self._by_key[self._selected]
        if spec.description:
            imgui.push_text_wrap_pos(0.0)
            imgui.text_colored(muted(), spec.description)
            imgui.pop_text_wrap_pos()

    def _render_combo(self) -> None:
        names = [s.name for s in self._specs]
        current = next(i for i, s in enumerate(self._specs) if s.key == self._selected)
        imgui.push_item_width(-1)
        changed, idx = imgui.combo("##filter_select", current, names)
        imgui.pop_item_width()
        if changed and self._specs[idx].key != self._selected:
            self._select(self._specs[idx].key)

    def _render_params(self) -> None:
        # Fetch spec + values together: the combo may have switched selection
        # this frame, pairing an earlier spec with another filter's values.
        spec = self._by_key[self._selected]
        if not spec.params:
            return
        values = self._values[self._selected]
        columns = 2 if imgui.get_content_region_avail().x >= ui_px(420) else 1
        if not imgui.begin_table("##parameters", columns, imgui.TableFlags_.sizing_stretch_same):
            return
        try:
            for p in spec.params:
                imgui.table_next_column()
                v = values[p.key]
                fmt = p.fmt or ("%d" if p.kind == "int" else "%.2f")
                value = fmt % v
                style = imgui.get_style()
                imgui.push_font(mono_font(), style.font_size_base)
                value_w = imgui.calc_text_size(value).x
                imgui.pop_font()
                left = imgui.get_cursor_pos_x()
                width = imgui.get_content_region_avail().x
                budget = max(0.0, width - value_w - style.item_spacing.x)
                caption = p.label
                if imgui.calc_text_size(caption).x > budget:
                    caption = _truncate_to_width(
                        caption, budget - imgui.calc_text_size("…").x,
                    ) + "…"
                imgui.text_unformatted(caption)
                imgui.set_item_tooltip(p.label)
                imgui.same_line()
                imgui.set_cursor_pos_x(left + max(0.0, width - value_w))
                mono_text(value, muted())
                imgui.set_next_item_width(-1.0)
                if p.kind == "int":
                    changed, nv = imgui.slider_int(
                        f"##{p.key}", int(v), int(p.min), int(p.max), "",
                    )
                else:
                    flags = imgui.SliderFlags_.logarithmic if p.log else 0
                    changed, nv = imgui.slider_float(
                        f"##{p.key}", float(v), p.min, p.max, "", flags,
                    )
                if changed:
                    self._apply_param(p.key, nv)
        finally:
            imgui.end_table()


class PostProcessor(FilterProcessor):
    """Preset [`FilterProcessor`][] for post-prediction output smoothing.

    The three built-in filters and ``one_euro`` selected by default, shown as
    a compact Smoothing row. Settings opens the filter description, captioned
    sliders with mono values, and Reset. For a custom palette, use
    [`FilterProcessor`][] directly.

    Parameters
    ----------
    hz
        Sample rate forwarded to filters that need it (e.g. ``one_euro``). Set
        it to the rate your predictions actually arrive at, or the smoothing is
        tuned for the wrong timebase.
    widget_id
        ImGui id scope — give each instance a unique value if you render more
        than one.
    compact
        ``True`` (the default) shows Smoothing, the filter, mono latency and
        a settings popover for parameters and Reset. In narrow cells the combo
        takes its own row. ``False`` shows the full POST-PROCESSING panel.

    Examples
    --------
    >>> from myogestic.widgets import PostProcessor
    >>> processor = PostProcessor(hz=20.0)
    >>> processor.ui()
    """

    def __init__(
        self, hz: float = 50.0, *, widget_id: str = "output_filter", compact: bool = True
    ) -> None:
        self._compact = compact
        super().__init__(
            BUILTIN_FILTERS,
            hz=hz,
            default="one_euro",
            title="POST-PROCESSING",
            widget_id=widget_id,
        )

    def ui(self) -> None:
        """Render the full panel or the compact Smoothing row and settings popover."""
        super().ui()

    def _render(self) -> None:
        if not self._compact:
            super()._render()
            return
        style = imgui.get_style()
        gap = style.item_spacing.x
        spec = self._by_key[self._selected]
        imgui.push_font(mono_font(), style.font_size_base)
        # Reserve every selectable delay so a combo change cannot push Settings
        # out of the row on the very frame a longer value first appears.
        delay_w = max(imgui.calc_text_size(
            _format_delay(s.delay(self._hz, self._values[s.key])) if s.delay else "0 ms"
        ).x for s in self._specs)
        imgui.pop_font()
        settings = f"{fa.ICON_FA_SLIDERS}##settings"
        settings_w = imgui.calc_text_size(fa.ICON_FA_SLIDERS).x + 2 * style.frame_padding.x
        label_w = imgui.calc_text_size("Smoothing").x
        inline = imgui.get_content_region_avail().x >= (
            label_w + ui_px(90) + delay_w + settings_w + 3 * gap
        )
        imgui.align_text_to_frame_padding()
        imgui.text_unformatted("Smoothing")
        if inline:
            imgui.same_line()
            imgui.push_item_width(
                imgui.get_content_region_avail().x - delay_w - settings_w - 2 * gap,
            )
            names = [s.name for s in self._specs]
            current = next(i for i, s in enumerate(self._specs) if s.key == self._selected)
            changed, idx = imgui.combo("##filter_select", current, names)
            imgui.pop_item_width()
            if changed and self._specs[idx].key != self._selected:
                self._select(self._specs[idx].key)
        spec = self._by_key[self._selected]
        delay = _format_delay(spec.delay(self._hz, self._values[self._selected])) if spec.delay else "0 ms"
        imgui.same_line()
        # At very small widths even the caption yields to Settings.
        if imgui.get_content_region_avail().x >= delay_w + settings_w + gap:
            mono_text(delay, muted())
            imgui.same_line()
        if imgui.get_content_region_avail().x < settings_w:
            imgui.new_line()
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(
            0.0, imgui.get_content_region_avail().x - settings_w,
        ))
        opened = imgui.is_popup_open("settings")
        if opened:
            push_selected()
        clicked = imgui.small_button(settings)
        if opened:
            pop_selected()
        imgui.set_item_tooltip("Smoothing settings")
        if clicked:
            imgui.open_popup("settings")
        if not inline:
            self._render_combo()
            spec = self._by_key[self._selected]
        imgui.set_next_window_size(imgui.ImVec2(ui_px(340), 0))
        if imgui.begin_popup("settings"):
            if panel_header_button(spec.name, fa.ICON_FA_WAVE_SQUARE, fa.ICON_FA_ROTATE_LEFT,
                                   tooltip="Clear smoothing history (e.g. on a new session)."):
                self.reset()
            self._render_description()
            self._render_params()
            imgui.end_popup()


__all__ = [
    "BUILTIN_FILTERS",
    "FilterParam",
    "FilterProcessor",
    "FilterSpec",
    "PostProcessor",
]
