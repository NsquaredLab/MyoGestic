"""Live feature-selection panel.

Replaces the legacy MyoGestic GUI's "Features to use" tick-list. User
registers a name → callable map at construction; the widget renders one
toggle chip per feature; calling the selector with an EMG window returns
the *active* features stacked along the channel axis::

    from myogestic.widgets import FeatureSelector

    selector = FeatureSelector(
        {"RMS": sliding_rms, "MAV": sliding_mav, "WL": sliding_wl},
        default=["RMS"],
    )

    @pipeline.extract
    def extract(windows):
        return selector(windows["emg"])      # active features stacked

    @app.ui
    def ui(ctx):
        selector.ui()                        # wrapping toggle chips

The widget owns its own state (which chips are active); user code
just reads :pyattr:`active_names`, :pyattr:`n_active`, or calls the
selector. Model code can read ``selector.n_active`` to size architecture
hyperparameters - e.g. RaulNet's ``nr_of_electrode_grids`` for stacked
multi-feature inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.widgets.common import panel_header, pop_selected, push_selected

FeatureFn = Callable[[np.ndarray], np.ndarray]


class FeatureSelector:
    """Wrapping toggle chips for named feature functions.

    Parameters
    ----------
    features
        Ordered map of feature name → callable. Each callable
        takes an EMG window ``(n_channels, n_samples)`` and returns
        an array - typically ``(n_channels, n_features_out)`` for
        time-preserving features like sliding RMS, but any
        consistent shape works as long as every active feature
        returns the *same* shape (they're concatenated along axis
        0 by `__call__`).
    default
        Optional iterable of feature names to start active.
        ``None`` (default) activates every feature; an empty list activates
        none.
    show_header
        Render the standard panel header.

    Raises
    ------
    ValueError
        if a name in ``default`` isn't in ``features``.

    Examples
    --------
    >>> from myogestic.recipes.features import rms
    >>> from myogestic.widgets import FeatureSelector
    >>> selector = FeatureSelector({"RMS": rms}, default=["RMS"])
    >>> selector.ui()
    """

    def __init__(
        self,
        features: dict[str, FeatureFn],
        default: Iterable[str] | None = None,
        *,
        widget_id: str = "features",
        show_header: bool = True,
    ) -> None:
        if not features:
            raise ValueError("FeatureSelector needs at least one feature")
        self._features: dict[str, FeatureFn] = dict(features)
        self._widget_id = widget_id
        self._show_header = show_header
        if default is None:
            default_set = set(self._features)
        else:
            default_set = set(default)
            unknown = default_set - set(self._features)
            if unknown:
                raise ValueError(
                    f"default contains unknown feature names: {sorted(unknown)}. "
                    f"Available: {list(self._features)}"
                )
        # Insertion order = registration order; preserved for reproducibility.
        self._active: dict[str, bool] = {name: (name in default_set) for name in self._features}

    # ------------------------------------------------------------- API

    @property
    def active_names(self) -> list[str]:
        """Feature names currently active, in registration order."""
        return [n for n, on in self._active.items() if on]

    @property
    def n_active(self) -> int:
        """Number of active features."""
        return sum(1 for on in self._active.values() if on)

    def is_active(self, name: str) -> bool:
        """Check whether a specific feature is active."""
        return self._active.get(name, False)

    def set_active(self, name: str, active: bool) -> None:
        """Programmatically activate / deactivate a feature.

        Useful for restoring saved selections from a checkpoint, or for
        scripted training runs that bypass the UI.
        """
        if name not in self._features:
            raise ValueError(f"Unknown feature {name!r}")
        self._active[name] = bool(active)

    def __call__(self, emg: np.ndarray) -> np.ndarray:
        """Apply every active feature to ``emg``, stack along axis 0.

        Raises
        ------
        RuntimeError
            if zero features are active. Predict /
            training callers should validate :pyattr:`n_active`
            before invoking; this raise is a defensive backstop so
            downstream code never sees a misleading shape.
        ValueError
            if active features return shapes that can't be
            concatenated along axis 0 (numpy raises this).
        """
        names = self.active_names
        if not names:
            raise RuntimeError(
                "FeatureSelector has no active features. Select at least "
                "one feature in the FEATURES panel before calling."
            )
        outs = [self._features[n](emg) for n in names]
        return np.concatenate(outs, axis=0)

    # -------------------------------------------------------------- UI

    def ui(self) -> None:
        """Render feature toggle chips.

        Updates take effect on the next prediction tick.
        """
        imgui.push_id(self._widget_id)
        try:
            if self._show_header:
                panel_header("Features")
            imgui.push_font(mono_font(), imgui.get_style().font_size_base)
            try:
                style = imgui.get_style()
                right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
                previous_right = None
                for name, active in self._active.items():
                    width = imgui.calc_text_size(name).x + 2 * style.frame_padding.x
                    if (
                        previous_right is not None
                        and previous_right + style.item_spacing.x + width <= right
                    ):
                        imgui.same_line()
                    if active:
                        push_selected()
                    if imgui.small_button(name):
                        self._active[name] = not active
                    if active:
                        pop_selected()
                    previous_right = imgui.get_item_rect_max().x
            finally:
                imgui.pop_font()
        finally:
            imgui.pop_id()
