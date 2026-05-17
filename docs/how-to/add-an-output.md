# Add a custom output

Outputs are user-owned objects. They are **not** registered with the app - you construct them in `main()`, hold a reference, and call `.push(data)` from `@pipeline.predict`. The base class ([`Output`][myogestic.outputs.Output]) runs a daemon send thread at your chosen `hz`, draining whatever was last pushed.

## The pattern

```python
import numpy as np
from myogestic.outputs import Output


class Output:
    def __init__(self, hz: float = 50):
        self._latest: np.ndarray | None = None
        self._hz = hz
        # daemon thread reads _latest and calls _send() at hz

    def push(self, data: np.ndarray) -> None:
        self._latest = data  # atomic ref assignment

    def _send(self, data: np.ndarray) -> None:
        raise NotImplementedError
```

To add an output:

1. Subclass `Output`.
2. Implement `_send(self, data) -> None` - the actual transport call.
3. (Optional) override `__init__` to take connection parameters; call `super().__init__(hz=...)`.

## Worked example: ROS publisher

```python
import numpy as np
from myogestic.outputs import Output


class ROSPoseOutput(Output):
    """Publish a 9-DoF pose as a ROS Float32MultiArray."""

    def __init__(self, topic: str, hz: float = 50.0):
        super().__init__(hz=hz)
        import rclpy  # lazy import - keeps ROS optional
        from rclpy.node import Node
        from std_msgs.msg import Float32MultiArray

        rclpy.init(args=None)
        self._node = Node("myogestic_pose")
        self._pub = self._node.create_publisher(Float32MultiArray, topic, 10)
        self._Float32MultiArray = Float32MultiArray

    def _send(self, data: np.ndarray) -> None:
        msg = self._Float32MultiArray()
        msg.data = data.astype(np.float32).tolist()
        self._pub.publish(msg)
```

Use it:

```python
ros_out = ROSPoseOutput("/myogestic/pose", hz=50)


@pipeline.predict
def predict(model, features):
    pose = model.predict(features)
    ros_out.push(pose)
    return {"pose": pose}
```

The `_send` runs every `1/hz` on the output's own daemon thread; `push` is non-blocking and just swaps the latest reference.

## Worked example: Bluetooth haptic actuator

```python
class HapticOutput(Output):
    def __init__(self, ble_client, characteristic_uuid: str, hz: float = 30.0):
        super().__init__(hz=hz)
        self._ble = ble_client
        self._uuid = characteristic_uuid

    def _send(self, data: np.ndarray) -> None:
        # data: 3-vec of intensities in [0, 1] → 3 bytes
        payload = (np.clip(data, 0, 1) * 255).astype(np.uint8).tobytes()
        self._ble.write(self._uuid, payload, response=False)
```

The BLE write itself releases the GIL inside `bleak`, so the output thread doesn't impact the predict thread.

## Choosing `hz`

Match the consumer's input rate, not the predict rate:

| Consumer | Typical `hz` |
|----------|--------------|
| Virtual hand (Godot/VHI) | 32–50 |
| ROS subscriber | 50–100 |
| Serial actuator | 10–30 |
| Vibrotactile haptic | 30–60 |
| LSL outlet for downstream apps | 50 |

If `predict_hz > output_hz`, you push faster than you send - that's fine, the latest push wins. If `predict_hz < output_hz`, you re-send the same value - that's also fine, just wastes bandwidth.

## Reference implementations

| Output | Where | Wire |
|--------|-------|------|
| [`LSLOutlet`](../api/outputs.md#myogestic.outputs.LSLOutlet) | `myogestic/outputs/lsl.py` | LSL stream outlet |
| [`UDPOutput`](../api/outputs.md#myogestic.outputs.UDPOutput) | `myogestic/outputs/udp.py` | datagrams to host:port |
| `SerialOutput` | `myogestic/outputs/serial_output.py` | pyserial line-based |

Mirror the closest one.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **Heavy work inside `_send`.** It runs at `hz`. If `_send` takes longer than `1/hz`, the daemon thread falls behind. Keep transport calls non-blocking; if they aren't, lower `hz` or move the slow part elsewhere.
- **Calling `_send` directly from `predict()`.** Defeats the point of the daemon thread (you'd block predict on transport latency). Always go through `push`.
- **Assuming `push(...)` is fire-and-forget delivery.** It's fire-and-forget *latest-value*. If you push twice between two `_send` ticks, only the second is sent. Useful for control vectors; **wrong for events**. For event streams, write a queue-based output instead of using the latest-value pattern.
