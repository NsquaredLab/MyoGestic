"""One stream, one viewer per electrode grid, tiled 3 x 2.

Where `channel_grid_demo.py` shows *one* viewer picking channels out of a
multi-grid stream, this shows the other arrangement: a **panel per grid**. Five
64-channel arrays (IN1-IN5) of a single 320-channel stream, each with its own
`SignalViewer` in a `Grid(2, 3)` cell.

Two parameters make that work, and both matter:

* ``widget_id`` — viewer state and ImGui ids key off it instead of the stream,
  so five viewers on ``"emg"`` keep separate channels, scale, filter and pause.
  Without it they would all resolve to one state and render identically.
* ``channel_scope`` — the hard restriction: the columns a panel may *ever*
  show. All / None / Invert, the ``N/total`` count, the ``[Edit...]`` grid and
  shift-click ranges all stay inside that panel's array.

Run with:
    uv run python examples/synthetic/multi_panel_grids.py

What to try:
    * Hit **All** in one tile: it selects that array's 64 channels, and the
      count reads ``64/64`` — not the stream's 320. (``initial_channels`` alone
      could not do this: it only seeds the opening selection.)
    * Open **[Edit...]** in a tile: only that array's grid is listed.
    * Press the header's toggle to collapse a tile's chrome down to the plot.
    * Note the tiles do **not** share a y-scale — each auto-scales alone, so do
      not compare amplitudes across them by eye. Give them a common manual
      range when that matters, or see `electrode_overview.py` for the
      shared-scale spatial view.
"""

import time

import numpy as np

from myogestic import App, Grid, Stream
from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets import SignalViewer
from myogestic.widgets.signals._channel_grid import auto_shape

N_GRIDS = 5
CHANNELS_PER_GRID = 64
N_CHANNELS = N_GRIDS * CHANNELS_PER_GRID  # 320
LAYOUT_COLS = 3  # 3 across x 2 down: 5 tiles, one cell to spare
FS = 2048.0
CHUNK = 64
WINDOW_S = 1.0  # short on purpose: every viewer copies the buffer tail per frame


def _grid_columns(index: int) -> list[int]:
    start = index * CHANNELS_PER_GRID
    return list(range(start, start + CHANNELS_PER_GRID))


class _SyntheticGridSource:
    """In-process 320-channel source (no LSL) laid out as five electrode grids.

    Self-paced from wall clock like `myogestic.sources.replay.ReplaySource`:
    ``read()`` returns ``(None, None)`` until real time has produced samples,
    so the free-spinning acquire thread doesn't busy-loop a core generating
    data far faster than ``FS``. Each array gets its own amplitude so the tiles
    look visibly different.
    """

    def __init__(self) -> None:
        self._pos = 0
        self._last_read_time: float | None = None
        self._rng = np.random.default_rng(0)
        # Distinct amplitude per array — also what makes the *absence* of a
        # shared y-scale across tiles obvious.
        self._scale = np.repeat(
            np.geomspace(1.0, 0.15, N_GRIDS).astype(np.float32), CHANNELS_PER_GRID
        )

    def connect(self) -> StreamInfo:
        return StreamInfo(
            n_channels=N_CHANNELS,
            fs=FS,
            dtype=np.float32,
            channel_grids=[
                ChannelGrid(f"IN{i + 1}", auto_shape(_grid_columns(i))) for i in range(N_GRIDS)
            ],
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


app = App(f"Multi-panel grids - {N_GRIDS} x {CHANNELS_PER_GRID} ch @ {FS:.0f} Hz")
app.streams(Stream("emg", source=_SyntheticGridSource(), window_ms=2000, buffer_ms=10000))

# `channel_scope` restricts; `initial_channels` seeds. Both are passed because
# scope alone would open each panel on its array's FIRST 16 channels (the
# >32-channel default policy, applied within the scope), not all 64.
viewers = [
    SignalViewer(
        "emg",
        widget_id=f"emg:grid{i}",
        title=f"IN{i + 1} - {CHANNELS_PER_GRID} ch",
        channel_scope=_grid_columns(i),
        initial_channels=_grid_columns(i),
        show_controls=False,
        window_s=WINDOW_S,
    )
    for i in range(N_GRIDS)
]
grid = Grid(2, LAYOUT_COLS)


@app.ui
def demo_ui(ctx):
    for i, viewer in enumerate(viewers):
        with grid[divmod(i, LAYOUT_COLS)]:
            viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
