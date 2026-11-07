---
title: "Drive your own device"
---
A target drives a prosthesis, motor controller, cursor or robot arm. Implement
its three methods and pass the object to a
[`ControlBus`][myogestic.controls.ControlBus]. The target is a plain object.
It needs no registration, subclassing or discovery by name.

## Run it first

`examples/synthetic/my_device.py` is a complete target with three lines left for you. It
needs no hardware:

```bash
uv run python examples/synthetic/my_device.py
```

## Expected output

```
a frame, as @pipeline.predict would push it:
  mydevice.grip              +0.80
  mydevice.wrist.pronation   -0.40
out of range and NaN, both handled before you see them:
  mydevice.grip              +1.00
  mydevice.wrist.pronation   +0.00
teardown, which rests every control first:
  mydevice.grip              +0.00
  mydevice.wrist.pronation   +0.00
  stopped
```

[`ControlBus`][myogestic.controls.ControlBus] clamps `5.0` to `1.0` using the declared `hi=1.0`
and replaces `NaN` with `0.0`. It returns every control to rest before teardown
so the device releases its last grip. The bus supplies these checks, keeping
clamping, invalid-value handling and resting out of the three target methods.

## Change these three things

Copy `my_device.py` next to your own code and edit the three marked lines:

| | what | where |
|---|---|---|
| 1 | Name your controls. Use two or more dotted lowercase segments; the first is your namespace. Name the direction of `+1`, as in `grip.close`; `grip.motor` names a component. | `ADDRESSES` |
| 2 | Drive your hardware. Replace the `print` with a call to `self._port.write(...)`, `self._motors.set(...)` or an MQTT publish. | in `send` |
| 3 | Release your hardware. Close the port, disconnect, power down. | in `stop` |

Nothing else has to change. If your device only moves one way, declare `lo=0.0` in
`capabilities` and MyoGestic will refuse a map that asks for the other direction.

To check a control map against your device before running anything:

```bash
uv run python tools/inspect_control_map.py my-map.toml
```

It calls only `capabilities()` and `resolve()`, so it builds no target and moves nothing.

## The contract, in full

If "control map", "address" and "alias" are new words,
[Concepts › Controls](../concepts/controls.md) explains the system this page uses. A
[remote target](drive-a-remote-target.md) is the separate case where your device is already
its own program and the target is written for you.

```python
class Target(Protocol):
    def bind(self, controls: ControlSet) -> None: ...
    def send(self, values, changed) -> None: ...
    def stop(self) -> None: ...

    claims: frozenset[str]  # optional

    def capabilities(self) -> Sequence | None: ...  # optional
```

`bind` runs when the bus is constructed, on the caller's thread, and may raise. Refuse a configuration you cannot
drive there, before sending any frames. `send` runs on the thread calling the bus
(predict ticks, UI selections or teardown) and must not raise; every continuous value it gets is already finite and inside its declared range,
because [`ControlBus`][myogestic.controls.ControlBus] sanitized the frame before fanning it
out.

The two optional members are what the bus asks for by name:

| member | absent means | present means |
|---|---|---|
| `claims` | "assume it drives everything" | the aliases it drives, so the bus can catch a control nothing drives |
| `capabilities()` | "the caller already knows my vocabulary" | what addresses you export, so a map can be resolved against you |

Apply a route's `weight` before clamping to your own range. The bus delivers the
unweighted value; compute `min(hi, max(lo, weight * value))`, as `RemoteTarget` does.
Ignoring `weight` silently discards every gain in the map, including the `weight = -1.0` that
inverts an axis.

## A complete target

This target moves a cursor.

<!--docs:run-->
```python
from myogestic.controls import Capability, ControlBus, Continuous, ControlSet


class CursorTarget:
    """Drive a 2-D cursor from two continuous controls."""

    #: What this target exports. Addresses are namespaced by their first segment, so
    #: `cursor.*` cannot collide with `vhi.*` in the same map.
    ADDRESSES = ("cursor.x", "cursor.y")

    def __init__(self) -> None:
        self.position = (0.0, 0.0)
        self._slots: dict[str, tuple[str, float]] = {}

    def capabilities(self):
        """Signed, normalised, resting at zero — the control standard's defaults."""
        return [
            Capability(address=a, kind="continuous", lo=-1.0, hi=1.0, rest=0.0)
            for a in self.ADDRESSES
        ]

    def bind(self, controls: ControlSet) -> None:
        """Refuse here, not at the first frame."""
        self._slots = {}
        for alias, refs in controls.routes.items():
            for ref in refs:
                if ref.address in self.ADDRESSES:
                    self._slots[alias] = (ref.address, ref.weight)
        if not self._slots:
            raise ValueError(f"nothing in this map targets {self.ADDRESSES}")

    @property
    def claims(self) -> frozenset[str]:
        return frozenset(self._slots)

    def send(self, values, changed) -> None:
        """One tick. Must not raise."""
        x, y = self.position
        for alias, (address, weight) in self._slots.items():
            # Weight first, then your own range. Yours to apply — the bus does not.
            value = min(1.0, max(-1.0, weight * float(values.get(alias, 0.0))))
            if address == "cursor.x":
                x = value
            else:
                y = value
        self.position = (x, y)

    def stop(self) -> None:
        """Rest. The bus sends a neutral frame first, so this is usually enough."""
        self.position = (0.0, 0.0)
```

## Driving it

`connect_controls` resolves the map against each target's exported controls and builds the bus:

<!--docs:run-->
```python
from myogestic.controls import connect_controls, load_control_map

control_map = load_control_map({"dofs": {"aim_x": "cursor.x", "aim_y": "cursor.y"}})

cursor = CursorTarget()
bus = connect_controls(control_map, [cursor], hz=32)

bus.push({"aim_x": 0.5, "aim_y": -0.25})
assert cursor.position == (0.5, -0.25)
bus.stop()
```

`connect_controls` answers `None` while any target's `capabilities()` returns `None`,
so a target that is not up yet defers instead of failing.
[`ControlLink`][myogestic.controls.ControlLink] holds the arguments and asks again for you,
which saves you a module-level `bus` and a `global`:

<!--docs:run-->
```python
from myogestic.controls import ControlLink

link = ControlLink(control_map, [CursorTarget()], hz=32)


def on_click():  # a button handler, or a training thread
    if link.ensure():  # idempotent, and cheap once it has bound
        link.bus.push({"aim_x": 0.5, "aim_y": -0.25})


on_click()
assert link.bus is not None  # this target answers immediately; a remote one would not
link.stop()  # rests every target and clears the bus
```

Targets are user-owned. In an app, register `link.stop()` with
`app.cleanup_hooks` so normal shutdown rests and closes them too.

Call `ensure()` from a UI handler or training thread that can wait for it.
Never call it from `@pipeline.predict`; it can block.
In `@pipeline.predict`, read `link.bus` and skip output while it is `None`
to keep the predict thread within its deadline.

If a UI loop should reconnect automatically, wrap the link in
[`ControlLinkConnector`][myogestic.controls.ControlLinkConnector] and call its non-blocking
`poll()` from that loop. Resolution is atomic across all targets in one link; use separate maps
and links when one output should keep working while another is unavailable.

For a fixed vocabulary with known capabilities, build the bus directly.
`connect_controls` is a convenience for lazy resolution.

```python
from myogestic.controls import ControlBus, resolve

controls = resolve(control_map, cursor.capabilities())
bus = ControlBus(controls, targets=[cursor], hz=32)
```

## Addresses are yours to name

A control map's right-hand side is an address, and its first segment namespaces it:
`vhi.prediction.index`, `keyboard.tap.function.f1`, `cursor.x`. Pick a segment nobody else uses
and the same map can drive your device and a Virtual Hand at once, with one `ControlBus` and
one list of targets:

```python
bus = ControlBus(controls, targets=[cursor, vhi_target], hz=32)
```

The bus checks at bind that a target claims every alias, catching addresses that no target drives.
Without that check, an undriven control could appear to work while the device stays still.

## A servo hand target

`examples/synthetic/servo_hand.py` drives six servos on a serial port and can run without hardware:

```bash
uv run python examples/synthetic/servo_hand.py
```

```python
--8 < --"examples/synthetic/servo_hand.py"
```

`hand.thumb` couples two servos in the target, keeping that coupling out of the map.
`frame` iterates `SERVOS` by name to preserve the device's wire order. `stop` returns the hand to rest before closing.

## Control value convention

A control value is signed and normalized to `[-1, 1]`, with `0` at rest. `+1` means the
direction the name denotes. `cursor.x` at `+1` should move right if you called it *right*.
A one-way control declares `lo=0.0` instead.

Check the sign by watching the device move.
[Concepts › Controls](../concepts/controls.md#the-one-convention-a-device-may-not-redefine)
explains why tests alone can miss a sign error.

## See also

- [Drive a remote target](drive-a-remote-target.md) - for a separate application, not an in-process object
- [Publish a data stream](add-an-output.md) - for telemetry: a sink with no control space, which drives nothing
- [Integrate the Virtual Hand](integrate-vhi.md) - the one remote target this project ships
- [Controls reference](../api/controls.md) - `Capability`, `ControlSet`, address rules
