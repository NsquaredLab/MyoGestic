"""Live feature-selection panel.

Replaces the legacy MyoGestic GUI's "Features to use" tick-list. User
registers a name → callable map at construction; the widget renders one
checkbox per feature; calling the selector with an EMG window returns
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
        selector.ui()                        # checkboxes + count

The widget owns its own state (which checkboxes are ticked); user code
just reads :pyattr:`active_names`, :pyattr:`n_active`, or calls the
selector. Model code can read ``selector.n_active`` to size architecture
hyperparameters - e.g. RaulNet's ``nr_of_electrode_grids`` for stacked
multi-feature inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import numpy as np
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import panel_header

FeatureFn = Callable[[np.ndarray], np.ndarray]


class FeatureSelector:
    """Tickable list of named feature functions.

    Parameters
    ----------
    features
        Ordered map of feature name → callable. Each callable
        takes an EMG window ``(n_channels, n_samples)`` and returns
        an array - typically ``(n_channels, n_features_out)`` for
        time-preserving features like sliding RMS, but any
        consistent shape works as long as every active feature
        returns the *same* shape (they're concatenated along axis
        0 by :meth:`__call__`).
    default
        Optional iterable of feature names to start ticked.
        ``None`` (default) ticks every feature; an empty list ticks
        none.

    Raises
    ------
    ValueError
        if a name in ``default`` isn't in ``features``.
    """

    def __init__(
        self,
        features: dict[str, FeatureFn],
        default: Iterable[str] | None = None,
        *,
        widget_id: str = "features",
    ) -> None:
        if not features:
            raise ValueError("FeatureSelector needs at least one feature")
        self._features: dict[str, FeatureFn] = dict(features)
        self._widget_id = widget_id
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
        """Feature names currently ticked, in registration order."""
        return [n for n, on in self._active.items() if on]

    @property
    def n_active(self) -> int:
        """Number of ticked features."""
        return sum(1 for on in self._active.values() if on)

    def is_active(self, name: str) -> bool:
        """Check whether a specific feature is ticked."""
        return self._active.get(name, False)

    def set_active(self, name: str, active: bool) -> None:
        """Programmatically tick / untick a feature.

        Useful for restoring saved selections from a checkpoint, or for
        scripted training runs that bypass the UI.
        """
        if name not in self._features:
            raise ValueError(f"Unknown feature {name!r}")
        self._active[name] = bool(active)

    def __call__(self, emg: np.ndarray) -> np.ndarray:
        """Apply every ticked feature to ``emg``, stack along axis 0.

        Raises
        ------
        RuntimeError
            if zero features are ticked. Predict /
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
                "FeatureSelector has no active features. Tick at least "
                "one feature in the FEATURES panel before calling."
            )
        outs = [self._features[n](emg) for n in names]
        return np.concatenate(outs, axis=0)

    # -------------------------------------------------------------- UI

    def ui(self) -> None:
        """Render the panel inside an ImGui frame.

        Call from inside ``@app.ui``. The header carries the active count
        (``FEATURES (2)``) and the feature checkboxes reflow into a
        content-sized table so columns stay aligned: each column is as wide
        as its own widest ``box + label``, so a label never clips under the
        next column's checkbox. State updates take effect on the next
        predict-thread tick.
        """
        # Scope every ImGui id below to this instance so two selectors in one
        # window (their same-named checkboxes / the table id) don't collide.
        imgui.push_id(self._widget_id)
        try:
            # Active count in the header. Rendered before the checkboxes, so a
            # click this frame shows in the title next frame — imperceptible at
            # UI frame rates.
            panel_header(f"FEATURES ({self.n_active})", fa.ICON_FA_LAYER_GROUP)

            # How many columns fit at the current width. Item width = checkbox
            # square + inner spacing + the widest label, so the column estimate
            # already accounts for the label text.
            style = imgui.get_style()
            spacing = style.item_spacing.x
            inner = style.item_inner_spacing.x
            frame_h = imgui.get_frame_height()
            features = self._features
            max_label_w = max(imgui.calc_text_size(name).x for name in features)
            item_w = frame_h + inner + max_label_w
            avail_w = imgui.get_content_region_avail().x
            fit = int((avail_w + spacing) / (item_w + spacing)) if item_w > 0 else 1
            n_cols = max(1, min(fit, len(features)))

            # A content-sized table lays out the grid: each column sizes to its
            # own widest box+label and cells never overlap — unlike a manual
            # same_line() grid, a label can't clip under the next column's box.
            if imgui.begin_table("##features_grid", n_cols, imgui.TableFlags_.sizing_fixed_fit):
                for name in features:
                    imgui.table_next_column()
                    changed, new_val = imgui.checkbox(name, self._active[name])
                    if changed:
                        self._active[name] = new_val
                imgui.end_table()
        finally:
            imgui.pop_id()
