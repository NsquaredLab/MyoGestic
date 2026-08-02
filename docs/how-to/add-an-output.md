# Publish a data stream

!!! warning "If something moves, you want a target"
    An `Output` is a paced sender and nothing else: no aliases, no declared range, no clamp,
    and no neutral frame on shutdown. A hand, a motor, a haptic or a cursor is a
    **[target](add-a-target.md)** - three methods and a write to a port, with the control map
    and the rest-on-teardown a device needs.

    Outputs are not shut out of that road, they are *part* of it.
    [`RemoteTarget`][myogestic.remote.RemoteTarget] builds one
    [`LSLOutlet`][myogestic.outputs.LSLOutlet] per control it drives, inside the target. That
    is where an output belongs when a device is on the other end.

This page is for the other case: publishing numbers for something else to read. A downstream
analysis script, a dashboard, a recorder in another process.

Outputs are user-owned. They are **not** registered with the app: construct one in `main()`,
hold a reference, and call `.push(data)` from `@pipeline.predict`. The base class
([`Output`][myogestic.outputs.Output]) runs a daemon send thread at your chosen `hz` that
sends whatever was last pushed.

## Writing one

1. Subclass [`Output`][myogestic.outputs.Output].
2. Open your socket, file or channel **first**, then call `super().__init__(hz=...)` **last**.
   The send thread starts inside that call, so a resource opened after it can be read before
   it exists.
3. Implement `_send(self, data) -> None`, the actual transport call. Treat `data` as
   read-only and validate its shape.
4. Override `stop()` if you hold a resource, calling `super().stop()` first.

## Worked example: a telemetry socket

Numbers to a dashboard on another host. Nothing here moves, which is what makes it an output
rather than a target.

```python
import socket

import numpy as np

from myogestic.outputs import Output


class TelemetryOutput(Output):
    """Send the latest prediction vector to a dashboard as float32 datagrams."""

    def __init__(self, host: str, port: int, hz: float = 20.0):
        # The socket first: `super().__init__` starts the send thread, and a thread that
        # wakes before `self._sock` exists raises on its first tick.
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
telemetry = TelemetryOutput("127.0.0.1", 9000, hz=20)


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    telemetry.push(pose)
    return {"pose": pose}
```

`push` is non-blocking and swaps a reference. `_send` runs every `1/hz` on the output's own
daemon thread, so transport latency never reaches the predict loop.

## Choosing `hz`

Match the consumer's input rate, not the predict rate. A dashboard redrawing at 20 Hz gains
nothing from 200. An LSL stream feeding another application is conventionally 50.

If `predict_hz > output_hz` you push faster than you send, and the latest push wins. If
`predict_hz < output_hz` you re-send the same value, which costs bandwidth and nothing else.

## Common mistakes

See also: the full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom.

- **Driving a device with one.** No clamp to a declared range, no aliases, and the transport
  closes while the device still holds the last thing it was told. That is a
  [target](add-a-target.md).
- **Heavy work inside `_send`.** It runs at `hz`. Longer than `1/hz` and the thread falls
  behind. Keep transport calls non-blocking, or lower `hz`.
- **Calling `_send` directly from `predict()`.** That blocks predict on transport latency,
  which is what the daemon thread exists to prevent. Always go through `push`.
- **Assuming `push(...)` delivers everything.** It is fire-and-forget *latest-value*. Push
  twice between two ticks and only the second is sent. Right for a control vector, **wrong
  for events**: for those, write a queue-based output instead.
