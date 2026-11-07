---
title: "Publish a data stream"
---
!!! warning "If something moves, you want a target"
    An `Outlet` has no aliases, no declared range, no clamp and no rest on shutdown. A hand, a
    motor, a haptic or a cursor is a [target](add-a-target.md).
    [`RemoteTarget`][myogestic.remote.RemoteTarget] builds one
    [`LSLOutlet`][myogestic.outputs.LSLOutlet] per control *inside* the target, which is where
    an output belongs when a device is on the other end.

Use an outlet to publish numbers for another application to read.

Construct an output in `main()`, keep a reference and call `.push(data)`
from `@pipeline.predict`. Outputs are user-owned. [`Outlet`][myogestic.outputs.Outlet]
runs a daemon thread at your `hz` that sends whatever was last pushed.

## Writing one

1. Subclass [`Outlet`][myogestic.outputs.Outlet].
2. Open your socket, file or channel first, then call `super().__init__(hz=...)` last.
   The send thread starts inside that call, so a resource opened after it can be read before
   it exists.
3. Implement `_send(self, data) -> None`, the actual transport call. Treat `data` as
   read-only and validate its shape.
4. Override `stop()` if you hold a resource, calling `super().stop()` first.

## Worked example: a telemetry socket

Numbers to a dashboard on another host.

```python
import socket

import numpy as np

from myogestic.outputs import Outlet


class TelemetryOutlet(Outlet):
    """Send the latest prediction vector to a dashboard as float32 datagrams."""

    def __init__(self, host: str, port: int, hz: float = 20.0):
        # Socket first: `super().__init__` starts the send thread.
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._addr = (host, port)
        super().__init__(hz=hz)

    def _send(self, data: np.ndarray) -> None:
        self._sock.sendto(data.astype(np.float32).tobytes(), self._addr)

    def stop(self) -> None:
        super().stop()
        self._sock.close()
```

Use it:

```python
telemetry = TelemetryOutlet("127.0.0.1", 9000, hz=20)
app.cleanup_hooks.append(lambda _app: telemetry.stop())


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    telemetry.push(pose)
    return {"pose": pose}
```

`push` is non-blocking. `_send` runs every `1/hz` on the output's own thread, so transport
latency never reaches the predict loop.

## Choosing `hz`

Match `hz` to the consumer's input rate. A dashboard redrawing at 20 Hz gains
nothing from 200. If you push faster than `hz`, only the latest value is sent;
if you push slower, the same value is sent again.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for errors by symptom.

- Driving a device with one. No clamp, no aliases, and the transport closes while the
  device still holds the last thing it was told. That is a [target](add-a-target.md).
- Heavy work inside `_send`. It runs at `hz`; longer than `1/hz` and the thread falls
  behind. Keep it non-blocking, or lower `hz`.
- Calling `_send` from `predict()`. Blocks predict on transport latency. Go through `push`.
- Assuming `push(...)` delivers everything. Push twice between ticks and only the second value is sent. Use a queue for events.
