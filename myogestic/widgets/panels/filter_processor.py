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
        output_filter.ui()                        # full panel

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

from myogestic.outputs.filters import OneEuroFilter, VectorFilter, make_filter
from myogestic.widgets.common import panel_header

Scalar = float | int

# Below this inline slider width (px), the label stacks *above* a full-width
# slider instead of sitting beside it, so it stays usable in a narrow panel.
_MIN_SLIDER_W = 90.0


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
        One-line blurb shown under the buttons.
    reconfigure
        Optional in-place update ``reconfigure(current, *, hz, params) ->
        VectorFilter``. When set, live tuning mutates the existing filter
        (preserving its smoothing history) instead of rebuilding it. Return
        the same object (or a replacement). ``None`` -> rebuild via ``build``.
    delay
        Optional ``delay(hz, params) -> float`` returning the filter's
        latency estimate in **milliseconds** — shown live in the panel title.
        ``None`` (e.g. a passthrough) shows no delay.

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
        description="Rolling temporal average. Steady, predictable lag.",
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
        description="Adaptive low-pass. Fast moves cut through; slow moves smooth.",
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
    fresh filter — no stale history).

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
        muted = imgui.get_style().color_(imgui.Col_.text_disabled)
        spec = self._by_key[self._selected]

        # Header row: icon + title (truncates to an ellipsis, then icon-only)
        # and a right-aligned Reset. Reset is prioritized — if the row can't
        # fit even the icon + Reset side by side, Reset drops to its own line
        # below the (icon-only) header. The delay estimate is shown between
        # them only when it fits (its units stay lower-case, unlike the title).
        style = imgui.get_style()
        sp = style.item_spacing.x
        icon = fa.ICON_FA_WAVE_SQUARE
        reset_label = f"{fa.ICON_FA_ROTATE_LEFT}"
        reset_w = imgui.calc_text_size(reset_label).x + style.frame_padding.x * 2
        icon_w = imgui.calc_text_size(icon).x
        inline = imgui.get_content_region_avail().x >= icon_w + sp + reset_w

        # panel_header reserves reset_w, so the title truncates leaving that
        # much room — the header is therefore never wider than avail - reset_w.
        panel_header(self._title, icon, reserve=(reset_w + sp) if inline else 0.0)

        if inline:
            imgui.same_line()
            remaining = imgui.get_content_region_avail().x  # width left after the header
            # Show the delay only if it fits *alongside* the reserved Reset, so
            # Reset can never be pushed off-screen.
            if spec.delay is not None:
                delay = f"({_format_delay(spec.delay(self._hz, self._values[self._selected]))})"
                if remaining >= imgui.calc_text_size(delay).x + reset_w + sp:
                    imgui.push_style_color(imgui.Col_.text, muted)
                    imgui.text(delay)
                    imgui.pop_style_color()
                    imgui.same_line()
            # Right-align Reset in whatever space is left (it always renders).
            a = imgui.get_content_region_avail().x
            if a > reset_w:
                imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + (a - reset_w))
        # else: Reset renders on the next line (no same_line), left-aligned.
        if imgui.small_button(reset_label):
            self.reset()
        if imgui.is_item_hovered():
            imgui.set_tooltip("Clear smoothing history (e.g. on a new session).")

        # Filter selector (dropdown) + its parameter sliders. Params re-fetch
        # the selection because the combo may have just switched it this frame.
        self._render_combo()
        self._render_params()

    def _render_combo(self) -> None:
        names = [s.name for s in self._specs]
        current = next(i for i, s in enumerate(self._specs) if s.key == self._selected)
        imgui.push_item_width(-1)
        changed, idx = imgui.combo("##filter_select", current, names)
        imgui.pop_item_width()
        if changed and self._specs[idx].key != self._selected:
            self._select(self._specs[idx].key)

    def _render_params(self) -> None:
        # Fetch spec + values together from the current selection: the combo
        # may have switched selection this frame, so a spec captured earlier
        # could otherwise be paired with a different filter's value dict.
        spec = self._by_key[self._selected]
        if not spec.params:
            return
        values = self._values[self._selected]
        # Label to the LEFT of the slider (aligned column) when there's room;
        # otherwise stack the label ABOVE a full-width slider so it stays
        # usable in a narrow panel instead of collapsing to a sliver.
        gap = imgui.get_style().item_spacing.x * 3.0
        label_w = max(imgui.calc_text_size(p.label).x for p in spec.params) + gap
        stacked = imgui.get_content_region_avail().x - label_w < _MIN_SLIDER_W
        for p in spec.params:
            v = values[p.key]
            if stacked:
                imgui.text(p.label)  # label above; slider full-width below
            else:
                imgui.align_text_to_frame_padding()
                imgui.text(p.label)
                imgui.same_line(label_w)
            imgui.push_item_width(-1)
            if p.kind == "int":
                changed, nv = imgui.slider_int(f"##{p.key}", int(v), int(p.min), int(p.max))
            else:
                flags = imgui.SliderFlags_.logarithmic if p.log else 0
                changed, nv = imgui.slider_float(
                    f"##{p.key}", float(v), p.min, p.max, p.fmt or "%.2f", flags
                )
            imgui.pop_item_width()
            if changed:
                self._apply_param(p.key, nv)


class PostProcessor(FilterProcessor):
    """Preset [`FilterProcessor`][] for post-prediction output smoothing.

    The three built-in filters, a ``"POST-PROCESSING"`` header, and
    ``one_euro`` selected by default. For a custom palette, use
    [`FilterProcessor`][] directly.

    Examples
    --------
    >>> from myogestic.widgets import PostProcessor
    >>> processor = PostProcessor(hz=20.0)
    >>> processor.ui()
    """

    def __init__(self, hz: float = 50.0, *, widget_id: str = "output_filter") -> None:
        super().__init__(
            BUILTIN_FILTERS,
            hz=hz,
            default="one_euro",
            title="POST-PROCESSING",
            widget_id=widget_id,
        )


__all__ = [
    "BUILTIN_FILTERS",
    "FilterParam",
    "FilterProcessor",
    "FilterSpec",
    "PostProcessor",
]
