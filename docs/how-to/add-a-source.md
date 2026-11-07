---
title: "Add a custom source"
---
A `Source` implements three methods of a [Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol). No inheritance is required. Pass the instance to `Stream(...)` for threading and buffering, with recording handled by the framework.

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

### `connect() -> StreamInfo`

Open the device, file or socket. Return a [`StreamInfo`][myogestic.StreamInfo] with `n_channels`, `fs`, optional `dtype` and optional `channel_names`. `dtype` defaults to `np.float32`. Discover these values from the source where possible. Require manual values only when the source cannot describe itself.

If the source can't connect, raise. `Stream.reconnect()` returns `False` and stores the error in `stream.last_error`; the connection widgets show it.

### `read() -> (data, ts) | (None, None)`

Called repeatedly by the acquisition thread. Return either:

- `(data, ts)` where `data.shape == (n_samples, n_channels)` (sample-major) and `ts.shape == (n_samples,)` (float64 LSL clock timestamps). The framework converts to channels-first at `Stream.get_window()` for you.
- `(None, None)` if no data is available. The framework calls `read()` again. Return promptly so the thread can stop when the app exits.

### `disconnect() -> None`

Release the device. Make this idempotent because shutdown may call it multiple times.

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
        arr = np.loadtxt(self.path, delimiter=",", dtype=np.float32, ndmin=2)
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
stream = Stream("emg", source=CSVSource("recording.csv", fs=2000.0), window_ms=1000)
app.streams(stream)
if not stream.reconnect():
    raise RuntimeError(stream.last_error)
app.run()
```

## Worked example: bridge a third-party SDK

Use the adapter pattern with a queue for a vendor SDK that emits chunks through a callback.

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
| [`ReplaySource`](../api/sources.md#myogestic.sources.ReplaySource) | `myogestic/sources/replay.py` | Reads from a `.mg.zip`, paces with real-time clock |
| `SerialSource` | `myogestic/sources/serial_source.py` | pyserial reads of fixed-width little-endian float32 frames |

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

Check the sample shapes and timestamps before connecting the source to the app.
