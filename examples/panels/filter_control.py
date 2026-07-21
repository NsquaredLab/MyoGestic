"""``FilterControl`` in isolation — a live-tunable output smoother.

A post-prediction smoother (Identity / Gaussian / One Euro) with sliders
that tune parameters in place and a Reset that clears smoothing history.
In a real app you call ``fc(pose, timestamp=...)`` inside
``@pipeline.predict``; here we just show the control UI.

Run with:
    uv run python examples/panels/filter_control.py
"""

from myogestic import App
from myogestic.widgets import FilterControl

fc = FilterControl(hz=20.0, default="one_euro")

app = App("panel: FilterControl")


@app.ui
def ui(ctx):
    fc.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
