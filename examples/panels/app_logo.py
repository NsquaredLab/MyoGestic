"""``app_logo`` in isolation — the MyoGestic wordmark, fit-to-cell.

Renders the shipped wordmark as the largest aspect-preserving rectangle
that fits the current panel (minus padding), centred. Handy as a header in
a corner cell of a multi-panel layout.

Run with:
    uv run python examples/panels/app_logo.py
"""

from myogestic import App
from myogestic.widgets import AppLogo

app = App("panel: app_logo")

logo = AppLogo()


@app.ui
def ui(ctx):
    logo.ui()


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
