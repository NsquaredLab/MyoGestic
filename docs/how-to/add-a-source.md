# Add a custom source

A `Source` is a [Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol) - three methods, no inheritance. Implement them, hand the instance to `Stream(...)`, and the framework handles threading, buffering, and recording for you.

## The protocol

```python
from typing import Protocol
import numpy as np

from myogestic import StreamInfo


class Source(Protocol):
    def connect(self) -> StreamInfo: ...
    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]: ...
    def disconnect(self) -> None: ...
```

That's the whole interface.

### `connect() -> StreamInfo`

Open the device / file / socket. Return a [`StreamInfo`][myogestic.StreamInfo] describing the data: `n_channels`, `fs`, optional `dtype` (defaults to `np.float32`), optional `channel_names`. Auto-discovery is the goal - the user shouldn't have to pass these manually unless the source genuinely can't self-describe.

If the source can't connect, raise - the framework surfaces the error in the GUI status bar.

### `read() -> (data, ts) | (None, None)`

Called repeatedly by the acquisition thread. Return either:

- `(data, ts)` where `data.shape == (n_samples, n_channels)` (sample-major) and `ts.shape == (n_samples,)` (float64 LSL clock timestamps). The framework converts to channels-first at `Stream.get_window()` for you.
- `(None, None)` if no new data is available right now. The framework will call `read()` again. Don't block forever - return promptly so the thread can be stopped cleanly when the app exits.

### `disconnect() -> None`

Release the device. Idempotent - may be called multiple times during shutdown.

## Worked example: a CSV replay source

A toy source that replays a CSV file at the original sample rate:

```python
from pathlib import Path
import numpy as np
import time
from mne_lsl.lsl import local_clock

from myogestic import StreamInfo


class CSVSource:
    def __init__(self, path: str, fs: float, channel_names: list[str] | None = None):
        self.path = Path(path)
        self.fs = fs
        self.channel_names = channel_names
        self._data: np.ndarray | None = None
        self._idx = 0
        self._t0 = 0.0

    def connect(self) -> StreamInfo:
        arr = np.loadtxt(self.path, delimiter=",", dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        self._data = arr
        self._idx = 0
        self._t0 = local_clock()
        return StreamInfo(
            n_channels=arr.shape[1],
            fs=self.fs,
            dtype=np.dtype("float32"),
            channel_names=self.channel_names,
        )

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        if self._data is None or self._idx >= self._data.shape[0]:
            return None, None
        # How many samples should have arrived by now (real-time pacing)?
        elapsed = local_clock() - self._t0
        target = int(elapsed * self.fs)
        if target <= self._idx:
            return None, None
        end = min(target, self._data.shape[0])
        chunk = self._data[self._idx : end]
        ts = (np.arange(self._idx, end) / self.fs + self._t0).astype(np.float64)
        self._idx = end
        return chunk, ts

    def disconnect(self) -> None:
        self._data = None
```

Use it:

```python
from myogestic import App, Stream

app = App("CSV replay")
app.streams(Stream("emg", source=CSVSource("recording.csv", fs=2000.0), window_seconds=1.0))
app.run()
```

That's the whole integration.

## Worked example: bridge a third-party SDK

Suppose you have a vendor SDK that emits chunks via a callback. Adapter pattern:

```python
import threading
import queue
import numpy as np

from myogestic import StreamInfo


class VendorSource:
    def __init__(self, vendor_handle):
        self._vendor = vendor_handle
        self._queue: queue.Queue = queue.Queue(maxsize=1000)

    def connect(self) -> StreamInfo:
        self._vendor.set_callback(self._on_chunk)
        self._vendor.start()
        info = self._vendor.describe()  # whatever the SDK exposes
        return StreamInfo(n_channels=info.n_ch, fs=info.fs)

    def _on_chunk(self, samples: np.ndarray, ts: np.ndarray) -> None:
        try:
            self._queue.put_nowait((samples, ts))
        except queue.Full:
            pass  # backpressure: drop on overflow rather than block the SDK

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None, None

    def disconnect(self) -> None:
        self._vendor.stop()
```

The vendor's callback runs on its own thread; the queue decouples it from the acquisition thread.

## Reference implementations

| Source | Where | Pattern |
|--------|-------|---------|
| [`LSLSource`](../api/sources.md#myogestic.sources.LSLSource) | `myogestic/sources/lsl.py` | LSL inlet polling with `pull_chunk(timeout=0.0)` |
| [`ReplaySource`](../api/sources.md#myogestic.sources.ReplaySource) | `myogestic/sources/replay.py` | Reads from a `.session.zip`, paces with real-time clock |
| `SerialSource` | `myogestic/sources/serial_source.py` | pyserial loop with line-based parsing |

Mirror whichever is closest to your transport.

## Testing your source without the GUI

```python
import time

src = MySource(...)
info = src.connect()
print(f"{info.n_channels} ch @ {info.fs} Hz")

for _ in range(20):
    data, ts = src.read()
    if data is not None:
        print(f"got {data.shape[0]} samples")
    time.sleep(0.05)

src.disconnect()
```

Once that loop produces sane output, the framework will work too.
