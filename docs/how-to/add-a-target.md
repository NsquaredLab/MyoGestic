# Drive your own device

A **target** is a Python object that drives a control map onto something: a hand, a
cursor, a prosthesis, a motor controller. MyoGestic ships two ([`RemoteTarget`][myogestic.remote.RemoteTarget] and
[`KeyboardTarget`][myogestic.keyboard.KeyboardTarget]); this is how you write a third.

There is one way to do it. A target is a plain object with three methods, you hand it to a
[`ControlBus`][myogestic.controls.ControlBus], and the bus drives it. Nothing registers,
nothing subclasses, nothing is discovered by name.

If "control map", "address" and "alias" are new words, read [Concepts ›
Controls](../concepts/controls.md) first. It explains the system, and why you would pick this
route over a [remote target](drive-a-remote-target.md).

## The contract

```python
class Target(Protocol):
    def bind(self, controls: ControlSet) -> None: ...
    def send(self, values, changed) -> None: ...
    def stop(self) -> None: ...

    claims: frozenset[str]                      # optional
    def capabilities(self) -> Sequence | None: ...   # optional
```

`bind` runs once, on the main thread, and **may raise**. Refuse a configuration you cannot
drive there, while a human is still reading the traceback. `send` runs on the predict thread
and **must not raise**; every value it gets is already finite and inside its declared range,
because [`ControlBus`][myogestic.controls.ControlBus] sanitised the frame before fanning it
out.

The two optional members are what the bus asks for by name:

| member | absent means | present means |
|---|---|---|
| `claims` | "assume it drives everything" | the aliases it drives, so the bus can catch a control nothing drives |
| `capabilities()` | "the caller already knows my vocabulary" | what addresses you export, so a map can be resolved against you |

## A complete target

The whole of a target that moves a cursor.

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
        self._slots: dict[str, str] = {}

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
                    self._slots[alias] = ref.address
        if not self._slots:
            raise ValueError(f"nothing in this map targets {self.ADDRESSES}")

    @property
    def claims(self) -> frozenset[str]:
        return frozenset(self._slots)

    def send(self, values, changed) -> None:
        """One tick. Must not raise."""
        x, y = self.position
        for alias, address in self._slots.items():
            if address == "cursor.x":
                x = float(values.get(alias, 0.0))
            else:
                y = float(values.get(alias, 0.0))
        self.position = (x, y)

    def stop(self) -> None:
        """Rest. The bus sends a neutral frame first, so this is usually enough."""
        self.position = (0.0, 0.0)
```

## Driving it

Same three lines as any other target. `connect_controls` asks each target what it exports,
resolves the map against the answers, and builds the bus:

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

`connect_controls` answers `None` rather than raising while any target's `capabilities()` does,
so a target that is not up yet defers instead of failing.
[`ControlLink`][myogestic.controls.ControlLink] holds the arguments and asks again for you,
which saves you a module-level `bus` and a `global`:

<!--docs:run-->
```python
from myogestic.controls import ControlLink

link = ControlLink(control_map, [CursorTarget()], hz=32)

def on_click():                 # a button handler, or a training thread
    if link.ensure():           # idempotent, and cheap once it has bound
        link.bus.push({"aim_x": 0.5, "aim_y": -0.25})

on_click()
assert link.bus is not None     # this target answers immediately; a remote one would not
link.stop()                     # rests every target and clears the bus
```

Call `ensure()` from anywhere that can afford to block: a UI handler, a training thread. Never
from `@pipeline.predict`, which has its own thread and a deadline - read `link.bus` there and
no-op while it is `None`.

If your target's vocabulary is fixed and you have the capabilities in hand already, build
the bus directly instead; `connect_controls` is only the lazy-resolve convenience:

```python
from myogestic.controls import ControlBus, resolve

controls = resolve(control_map, cursor.capabilities())
bus = ControlBus(controls, targets=[cursor], hz=32)
```

## Addresses are yours to name

A control map's right-hand side is an **address**, and its first segment namespaces it:
`vhi.prediction.index`, `keyboard.tap.function.f1`, `cursor.x`. Pick a segment nobody else uses
and the same map can drive your device and a Virtual Hand at once, with one `ControlBus` and
one list of targets:

```python
bus = ControlBus(controls, targets=[cursor, vhi_target], hz=32)
```

The bus checks that *someone* claims every alias, so an address no target drives is caught at
bind. Uncaught, it would look like a control that works and holds still.

## What the standard asks of you

A control value is **signed and normalised**: `[-1, 1]`, `0` at rest, and `+1` means the
direction the name denotes. `cursor.x` at `+1` should move right if you called it *right*.
A one-way control declares `lo=0.0` instead.

Getting a sign backwards is the one mistake that survives every test you are likely to write -
[Concepts › Controls](../concepts/controls.md#the-one-convention-a-device-may-not-redefine)
has the reason. Check it against something outside the loop: a person looking at the device.

## See also

- [Drive a remote target](drive-a-remote-target.md) - for a separate application, not an in-process object
- [Add a custom output](add-an-output.md) - for a plain data sink with no control space
- [Integrate the Virtual Hand](integrate-vhi.md) - the one remote target this project ships
- [Controls reference](../api/controls.md) - `Capability`, `ControlSet`, address rules
