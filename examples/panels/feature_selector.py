"""``FeatureSelector`` in isolation — tick which features to extract.

Register a ``name → callable`` map; the widget renders one checkbox per
feature and a live active-count. Calling the selector with an EMG window
returns the *active* features stacked along the channel axis — wire that
inside ``@pipeline.extract``. Here we only show the checkbox UI.

Run with:
    uv run python examples/panels/feature_selector.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import FeatureSelector

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


@app.ui
def ui(ctx):
    selector.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
