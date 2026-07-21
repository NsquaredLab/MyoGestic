"""``trial_preview`` in isolation — stacked waveform + shaded band overlay.

A recorded-trial review surface: multi-channel data drawn as stacked
traces (per-channel offsets, auto-gain like ``signal_viewer``), with an
optional colored band marking a region of interest — an extracted
template, a labeled gesture, a chosen training window.

Here: a mock 4-channel, 1-second trial with a burst in the middle and a
band drawn over it.

Run with:
    uv run python examples/panels/trial_preview.py
"""

import numpy as np

from myogestic import App
from myogestic.widgets import TrialPreview

FS = 2000.0
_t = np.arange(0, 1.0, 1 / FS)
# Channels-first (n_channels, n_samples); a burst in the 0.4-0.6 s window.
_burst = np.exp(-((_t - 0.5) ** 2) / (2 * 0.05**2))
DATA = np.stack(
    [(0.4 + 0.9 * _burst) * np.sin(2 * np.pi * f * _t) for f in (20, 35, 50, 65)]
).astype(np.float32)

app = App("panel: trial_preview")

preview = TrialPreview(
    widget_id="trial",
    title="Trial 0 — Fist",
    band=(0.4, 0.6),
    channel_names=["ch0", "ch1", "ch2", "ch3"],
)


@app.ui
def ui(ctx):
    preview.ui(DATA, FS)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
