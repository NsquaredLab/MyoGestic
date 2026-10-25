"""``FeatureSelector`` in isolation — choose which features to extract.

Register a ``name → callable`` map; the widget renders one chip per
feature and a live active-count. Calling the selector with an EMG window
returns the *active* features stacked along the channel axis — wire that
inside ``@pipeline.extract``. Here we only show the selection UI.

Run with:
    uv run python examples/panels/feature_selector.py
"""

import numpy as np

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, FeatureSelector

selector = FeatureSelector(
    {
        "RMS": lambda x: np.sqrt(np.mean(x**2, axis=1)),
        "MAV": lambda x: np.mean(np.abs(x), axis=1),
        "WL": lambda x: np.sum(np.abs(np.diff(x, axis=1)), axis=1),
        "VAR": lambda x: np.var(x, axis=1),
        "ZC": lambda x: np.sum(np.diff(np.signbit(x), axis=1), axis=1),
    },
    default=["RMS", "MAV"],
)

app = App("panel: FeatureSelector")
header = AppHeader("FeatureSelector", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        selector.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
