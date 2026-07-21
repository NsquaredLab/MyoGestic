"""``image`` in isolation — a generic fit-to-cell image widget.

Renders any asset (relative to MyoGestic's assets folder) as the largest
aspect-preserving rectangle that fits the current cell, centred, with a
muted fallback when the asset is missing. ``app_logo`` is a thin wrapper
over this. Here we render the shipped square app icon to show it works with
any asset, not just the wordmark.

Run with:
    uv run python examples/panels/image.py
"""

from myogestic import App
from myogestic.widgets import Image

app = App("panel: image")

img = Image("app_settings/icon.png", max_size=256)


@app.ui
def ui(ctx):
    img.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
