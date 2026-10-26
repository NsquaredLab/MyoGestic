"""``PostProcessor`` in isolation — a live-tunable output smoother.

A post-prediction smoother (Identity / Gaussian / One Euro) with sliders
that tune parameters and a Reset that clears smoothing history. In a real
app you call ``fc(pose, timestamp=...)`` inside ``@pipeline.predict``; here
we just show the control UI.

Run with:
    uv run python examples/panels/post_processor.py
"""

from myogestic import App, Fr, Grid, Px
from myogestic.widgets import AppHeader, PostProcessor

fc = PostProcessor(hz=20.0)

app = App("panel: post_processor")
header = AppHeader("PostProcessor", show_state=False)
layout = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))


@app.ui
def ui(ctx):
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("body"):
        fc.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
