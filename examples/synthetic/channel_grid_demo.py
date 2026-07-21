"""Channel-grid demo: synthetic 256-ch stream, split into 4 electrode grids.

Manual-validation harness for the signal viewer's spatial channel-selection
grid (the toggle-grid that replaced the old per-channel button wall). No
LSL, no ML, no VHI — just a live viewer wired to an in-process synthetic
source, so the grid widget can be exercised by hand.

Run with:
    uv run python examples/synthetic/channel_grid_demo.py

What to try:
    * The viewer opens with 16 of 256 channels enabled (`initial_channels`)
      — only those 16 plot; the rest of the 256-channel stream sits idle.
    * Open the channel grid: it renders as 4 separate IN1-IN4 grids of 64
      cells each (one per synthetic electrode array).
    * Click a cell to toggle a single channel.
    * Drag across a region to select/deselect a rectangular block at once.
    * Shift-click to select a contiguous range from the last click.
    * Watch the plot: only enabled channels ever get decimated/drawn, so
      toggling channels off should keep the view responsive even at 256 ch.
"""

import time

import numpy as np

from myogestic import App, Grid, Stream
from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets import SignalViewer
from myogestic.widgets.signals._channel_grid import auto_shape

N_CHANNELS = 256
N_GRIDS = 4
CHANNELS_PER_GRID = N_CHANNELS // N_GRIDS
FS = 2048.0
CHUNK = 64


class _SyntheticGridSource:
    """In-process 256-channel Source (no LSL) with a 4-grid electrode layout.

    Same connect/read/disconnect shape as the synthetic sources used across
    the test suite (e.g. `tests/test_signal_viewer_decimation.py`), but
    paced to wall-clock time like `myogestic.sources.replay.ReplaySource` —
    `read()` returns `(None, None)` until a full chunk's worth of real time
    has elapsed, instead of returning data every call unthrottled. The tests
    can get away with an unpaced stub because they drive the acquire loop
    manually a fixed number of times; a live GUI app runs the acquire loop
    on a free-spinning daemon thread; without self-pacing it would busy-loop
    a CPU core generating channels far faster than `FS`.
    """

    def __init__(self) -> None:
        self._pos = 0
        self._last_read_time: float | None = None
        self._rng = np.random.default_rng()

    def connect(self) -> StreamInfo:
        channel_grids = [
            ChannelGrid(
                f"IN{i + 1}",
                auto_shape(list(range(i * CHANNELS_PER_GRID, (i + 1) * CHANNELS_PER_GRID))),
            )
            for i in range(N_GRIDS)
        ]
        return StreamInfo(
            n_channels=N_CHANNELS,
            fs=FS,
            dtype=np.float32,
            channel_grids=channel_grids,
        )

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        now = time.perf_counter()
        if self._last_read_time is None:
            samples_due = CHUNK
        else:
            elapsed = now - self._last_read_time
            samples_due = int(elapsed * FS)
            if samples_due < 1:
                return None, None
        self._last_read_time = now

        data = self._rng.standard_normal((samples_due, N_CHANNELS)).astype(np.float32)
        ts = (self._pos + np.arange(samples_due, dtype=np.float64)) / FS
        self._pos += samples_due
        return data, ts

    def disconnect(self) -> None:
        pass


app = App("Channel Grid Demo")
app.streams(Stream("emg", source=_SyntheticGridSource(), window_ms=1000, buffer_ms=10000))

grid = Grid(1, 1)

viewer = SignalViewer("emg", selectable=True, initial_channels=range(16))


@app.ui
def demo_ui(ctx):
    with grid[0, 0]:
        viewer.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
