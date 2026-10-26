"""One 256-channel synthetic stream split into four tiled electrode-grid viewers.

Four 64-channel arrays (IN1-IN4) share one stream and one manual amplitude
range. Each has its own `SignalViewer` in a 2 x 2 grid below the app header.
The source runs in process, so no hardware or external generator is needed.

Two parameters make that work, and both matter:

* ``widget_id`` — viewer state and ImGui ids key off it instead of the stream,
  so four viewers on ``"emg"`` keep separate channels, filter and pause.
  Without it they would all resolve to one state and render identically.
* ``channel_scope`` — the hard restriction: the columns a panel may *ever*
  show. All / None / Invert, the ``N/total`` count, the ``[Edit...]`` grid and
  shift-click ranges all stay inside that panel's array.

Run with:
    uv run python examples/synthetic/electrode_grids.py

What to try:
    * Hit **All** in one tile: it selects that array's 64 channels, and the
      count reads ``64/64`` — not the stream's 256. (``initial_channels`` alone
      could not do this: it only seeds the opening selection.)
    * Expand a tile's controls, then open **Channels** and **Edit...**: only
      that array's grid is listed. Click a cell, drag a rectangle, or shift-click
      to select a contiguous range; the plot only processes enabled channels.
    * Press the header's toggle to collapse a tile's chrome down to the plot.
    * Compare amplitudes across tiles: all start on the same manual range,
      so a quiet array stays visibly quieter. Keep that common range when
      adjusting Scale, or see `electrode_overview.py` for the spatial view.
"""

import time

import numpy as np

from myogestic import App, Context, Fr, Grid, Px, Stream
from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets import AppHeader, SignalViewer
from myogestic.widgets.signals._channel_grid import auto_shape

N_GRIDS = 4
CHANNELS_PER_GRID = 64
N_CHANNELS = N_GRIDS * CHANNELS_PER_GRID  # 256
FS = 2048.0
CHUNK = 64
WINDOW_S = 1.0  # short on purpose: every viewer copies the buffer tail per frame
Y_RANGE = (-4.0, 4.0)  # one amplitude scale for every array, including the quietest


def _grid_columns(index: int) -> list[int]:
    start = index * CHANNELS_PER_GRID
    return list(range(start, start + CHANNELS_PER_GRID))


class _SyntheticGridSource:
    """In-process 256-channel source (no LSL) laid out as four electrode grids.

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
        # Distinct amplitude per array, visible against the shared manual range.
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


app = App("Electrode grids")
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
        scale_mode="manual",
        y_range=Y_RANGE,
    )
    for i in range(N_GRIDS)
]
grid = Grid.areas(
    "header header\nIN1 IN2\nIN3 IN4",
    row_height=[Px(52), Fr(1), Fr(1)],
    bare=("header",),
)
header = AppHeader("Electrode grids", show_state=False)


@app.ui
def demo_ui(ctx: Context) -> None:
    with grid.area("header"):
        header.ui(ctx)
    for i, viewer in enumerate(viewers):
        with grid.area(f"IN{i + 1}"):
            viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
