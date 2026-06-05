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
    ) -> None:
        if not features:
            raise ValueError("FeatureSelector needs at least one feature")
        self._features: dict[str, FeatureFn] = dict(features)
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

    def set_active(self, name: str, on: bool) -> None:
        """Programmatically tick / untick a feature.

        Useful for restoring saved selections from a checkpoint, or for
        scripted training runs that bypass the UI.
        """
        if name not in self._features:
            raise ValueError(f"Unknown feature {name!r}")
        self._active[name] = bool(on)

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

        Call from inside ``@app.ui``. Renders a header, the feature
        checkboxes laid out in a **wrapping grid** that reflows with the
        panel's current width (one column when narrow, many when wide),
        and a footer line showing the active count. State updates take
        effect on the next predict-thread tick.
        """
        panel_header("FEATURES", fa.ICON_FA_LAYER_GROUP)

        # Compute how many checkboxes fit per row at the current panel
        # width. Item width = checkbox indicator (~one frame-height
        # square) + inner spacing + the widest label. We size every
        # column to the widest label so the grid stays a clean alignment.
        style = imgui.get_style()
        spacing = style.item_spacing.x
        inner = style.item_inner_spacing.x
        frame_h = imgui.get_frame_height()
        max_label_w = max(imgui.calc_text_size(name).x for name in self._features)
        item_w = frame_h + inner + max_label_w
        avail_w = imgui.get_content_region_avail().x
        n_cols = max(1, int((avail_w + spacing) / (item_w + spacing)) if item_w > 0 else 1)

        for i, name in enumerate(self._features):
            if i > 0 and i % n_cols != 0:
                imgui.same_line()
            on = self._active[name]
            changed, new_val = imgui.checkbox(name, on)
            if changed:
                self._active[name] = new_val

        n = self.n_active
        suffix = "" if n == 1 else "s"
        imgui.text_disabled(f"{n} active feature{suffix}")
