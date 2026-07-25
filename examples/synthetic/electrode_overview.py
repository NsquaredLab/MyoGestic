"""Five electrode arrays at a glance: spatial RMS maps that are comparable.

The overview counterpart to `multi_panel_grids.py`. Five 64-channel arrays
(IN1-IN5) of one 320-channel stream, each drawn as a live **spatial RMS
heatmap** in a `Grid(2, 3)` cell, with a full `SignalViewer` in the sixth for
temporal detail.

Why maps rather than traces: 64 overlaid traces in a small tile is texture, not
signal. A map answers "which electrode is dead, loose or noisy?" instantly,
which is the question a bring-up check actually asks.

The load-bearing detail is `Heatmap.ui(vrange=...)`: every map is given **one
shared colour range**, recomputed each frame across all 320 channels. Without
it each heatmap maps its own min/max, and a silent array renders exactly like a
busy one — which inverts the conclusion you would draw.

Run with:
    uv run python examples/synthetic/electrode_overview.py

What to try:
    * Watch the arrays: their amplitudes differ by design, and the shared scale
      is what makes that visible. Comment out `vrange=` to see them all light
      up identically.
    * Use the detail viewer's `[Edit...]` grid to pick which electrodes to
      trace; with several grids it tiles them near-square.
"""

import time

import numpy as np
from imgui_bundle import imgui

from myogestic import App, Grid, Stream
from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets import Heatmap, SignalViewer

N_GRIDS = 5
GRID_ROWS, GRID_COLS = 8, 8  # 8x8 electrode block per array
CHANNELS_PER_GRID = GRID_ROWS * GRID_COLS
N_CHANNELS = N_GRIDS * CHANNELS_PER_GRID  # 320
LAYOUT_COLS = 3  # 3 across x 2 down: 5 maps + 1 detail panel
FS = 2048.0
CHUNK = 64
RMS_MS = 250.0  # short integration, so a map tracks contractions live


def _grid_cells(index: int) -> list[list[int]]:
    """An 8x8 block of consecutive column indices for array `index`."""
    start = index * CHANNELS_PER_GRID
    return [
        list(range(start + r * GRID_COLS, start + (r + 1) * GRID_COLS)) for r in range(GRID_ROWS)
    ]


GRIDS = [ChannelGrid(f"IN{i + 1}", _grid_cells(i)) for i in range(N_GRIDS)]

# Column index per electrode cell, precomputed once (-1 marks an empty cell).
# Turns the per-channel RMS vector into each array's 2-D map with one gather.
INDEX_MAPS = [
    np.array([[-1 if c is None else c for c in row] for row in g.cells], dtype=np.intp)
    for g in GRIDS
]
HEATMAPS = [Heatmap(g.label, size=(-1, -1), label_fmt="%.2f") for g in GRIDS]


class _SyntheticArraySource:
    """In-process 320-channel source (no LSL) as five 8x8 electrode arrays.

    Wall-clock paced (see `channel_grid_demo.py` for why). Each array runs at a
    different amplitude, and one electrode is deliberately dead, so the map has
    something to reveal.
    """

    def __init__(self) -> None:
        self._pos = 0
        self._last_read_time: float | None = None
        self._rng = np.random.default_rng(0)
        self._scale = np.repeat(
            np.geomspace(1.0, 0.15, N_GRIDS).astype(np.float32), CHANNELS_PER_GRID
        )
        self._scale[CHANNELS_PER_GRID * 2 + 27] = 0.0  # a dead contact on IN3

    def connect(self) -> StreamInfo:
        return StreamInfo(
            n_channels=N_CHANNELS, fs=FS, dtype=np.float32, channel_grids=GRIDS
        )

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        now = time.perf_counter()
        if self._last_read_time is None:
            samples_due = CHUNK
        else:
            samples_due = int((now - self._last_read_time) * FS)
            if samples_due < 1:
                return None, None
        self._last_read_time = now

        noise = self._rng.standard_normal((samples_due, N_CHANNELS)).astype(np.float32)
        data = noise * self._scale[None, :]
        ts = (self._pos + np.arange(samples_due, dtype=np.float64)) / FS
        self._pos += samples_due
        return data, ts

    def disconnect(self) -> None:
        pass


app = App(f"Electrode overview - {N_GRIDS} x {CHANNELS_PER_GRID} ch @ {FS:.0f} Hz")
app.streams(Stream("emg", source=_SyntheticArraySource(), window_ms=2000, buffer_ms=10000))
viewer = SignalViewer("emg")
grid = Grid(2, LAYOUT_COLS)


def _channel_rms(stream) -> np.ndarray | None:
    """Per-channel RMS over the last `RMS_MS`, or None before any data lands."""
    data, _ = stream.get_window()  # channels-first (n_channels, n_samples)
    if data.size == 0:
        return None
    n = max(1, min(data.shape[1], int(RMS_MS / 1000.0 * FS)))
    return np.sqrt(np.mean(np.square(data[:, -n:], dtype=np.float64), axis=1))


@app.ui
def demo_ui(ctx):
    stream = ctx.streams.get("emg")
    rms = _channel_rms(stream) if stream is not None else None
    # ONE range across every array: comparing them is the entire point, and
    # per-map autoscaling would make a silent array look like a busy one.
    vmax = float(rms.max()) if rms is not None and rms.size else 0.0
    vrange = (0.0, vmax if vmax > 0.0 else 1.0)

    for i, (g, heatmap, idx) in enumerate(zip(GRIDS, HEATMAPS, INDEX_MAPS, strict=True)):
        with grid[divmod(i, LAYOUT_COLS)]:
            if rms is None:
                imgui.text_disabled(f"{g.label}: no data")
                continue
            if i == 0:
                imgui.text_disabled(f"RMS 0-{vrange[1]:.2f} (shared across arrays)")
            heatmap.ui(np.where(idx >= 0, rms[idx], 0.0), vrange=vrange)

    with grid[1, LAYOUT_COLS - 1]:  # last cell: temporal detail
        viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
