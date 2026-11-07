---
title: "Controls"
---
A control is something a person drives, such as a finger, wrist, cursor axis or key. A device
declares its controls, your application names its model outputs, and a TOML control map pairs them.
MyoGestic has no hard-coded list of controls. The map file is the whole control configuration surface.

## Two vocabularies meet on one line

```toml
[dofs]
my_thumb = "vhi.prediction.thumb.flexion"
```

| | left of `=` | right of `=` |
|---|---|---|
| whose name is it | yours | the device's |
| what is it | the key your model's `predict()` returns | an *address* the device declares |
| who reads it | nothing; it is never parsed for meaning | the device, which owns what it means |
| how far does it travel | nowhere; it never leaves the app | onto the wire as the control's identity |

Each entry under `[dofs]` is one DOF, one [degree of
freedom](../reference/glossary.md#dof). The left side is an alias, such as `my_thumb`, `fist` or
`drive_x`. Choose any readable name. MyoGestic prescribes no alias names and derives no meaning from them. The same alias can point at a Virtual Hand in one file
and at a cursor axis in another with no code change.

The right side is a dotted, lowercase address with at least two segments. The first segment
namespaces the device (`vhi.`, `keyboard.`, `cursor.`), so two devices cannot collide inside
one map. The device declares whether
`vhi.prediction.thumb.flexion` takes a number or a held state, its range and its neutral value.
MyoGestic reads these declarations.

## The map is a file

`examples/controls/regression.toml` maps six model outputs to six addresses in `[dofs]`.

```toml
[dofs]

# One regressed output per digit.
thumb = "vhi.prediction.thumb.flexion"
index = "vhi.prediction.index"
middle = "vhi.prediction.middle"
ring = "vhi.prediction.ring"
little = "vhi.prediction.little"

# Discrete, per VHI. `debounce_s` gates classifier chatter.
gesture = { target = "vhi.control.gesture", debounce_s = 0.1 }
```

`examples/controls/playground.toml` maps outputs to several devices.

```toml
[dofs]
close = { targets = [
  { target = "vhi.prediction.thumb.flexion" },
  { target = "vhi.prediction.thumb.abduction", weight = -1.0 },
  { target = "vhi.prediction.index" },
  { target = "vhi.prediction.middle" },
  { target = "vhi.prediction.ring" },
  { target = "vhi.prediction.little" },
] }
my_control_1 = { target = "keyboard.hold.function.f1", debounce_s = 0.41, threshold_fraction = 0.5 }
my_control_2 = { target = "keyboard.tap.function.f1", threshold_fraction = 0.5 }
my_control_3 = "vhi.prediction.wrist.rotation"
```

A keystroke and a 3-D hand share the table. The hand is a Godot application reached over
gRPC and LSL; the keystroke uses `pynput` in this process. Each device handles delivery.
The map names only what is driven. It contains no transport or delivery instructions.
To add a device, add its addresses to the map and its `Target` to the bus. Nothing between them changes.

The value shapes are the entire map grammar. A bare string names one address. An array sends one output to several addresses. Use a table
to set a per-address `weight` or `debounce_s` gate. [`docs/api/controls.md`](../api/controls.md) has the full rules
and every option.

## The one convention a device may not redefine

Continuous control values are signed and normalized:

- the range is `[-1, 1]`;
- `0` is rest;
- `+1` is the direction the control's name denotes: `…thumb.flexion` at `+1` flexes, and at
  `-1` extends. There is no second address for the other direction.
- a one-way control declares `lo=0.0`, and then only ever moves one way.

A device converts to its own units, such as degrees for a robotic hand or pixels per second
for a cursor. `+1` must follow the direction named by the control.

Check the sign by looking at the device. A device and its read-back can agree even when the
device flexes in response to an extension command. Their contract tests can all pass with
this sign error. This repository shipped such a bug while its tests passed. A person looking
at the device provides the check outside that loop.

## Continuous and discrete are different things

| | continuous | discrete |
|---|---|---|
| what it is | an amount, this instant | a held state, until changed |
| how it travels | one value per tick, on a stream | on change only, over the device's own command channel |
| repeated? | every tick, forever | never: a repeat is expressed by returning through rest first |
| examples | `vhi.prediction.index` | `vhi.control.gesture`, `keyboard.tap.edit.space` |

Do not send a held state on a per-tick stream. Re-sending it at 32 Hz produces 32 keystrokes
a second instead of one held key.
[`ControlBus`][myogestic.controls.ControlBus] delivers continuous values as a full frame every
tick and discrete values as edges when a state settles. Each device uses its own command channel. For VHI that is a
`SetControl` gRPC call; for [`KeyboardTarget`][myogestic.keyboard.KeyboardTarget] it is a
key-down or key-up.

The device's manifest declares `kind`. The map cannot declare it. The same map file works if the device changes a
control from continuous to discrete.

For buttons, [`ControlBus.select`][myogestic.controls.ControlBus.select] delivers a state
immediately and rebases the DOF's debounce, so matching predict ticks do not repeat the click. A different predicted
state must pass the debounce gate again.

## Who answers what

| question | answered by |
|---|---|
| which controls exist, and what each one *is* | the device, through its manifest (`GetControlManifest` for a remote target, a local list for the keyboard) |
| what my model's outputs are called, and where each goes | the map you write |
| whether those two fit together | [`resolve()`][myogestic.controls.resolve] |

`resolve()` puts an alias and a capability together and produces the DOF you actually drive.
Here it is against the keyboard, which answers from a local list with nothing launched:

<!--docs:run-->
```python
from myogestic.controls import load_control_map, resolve
from myogestic.keyboard import KeyboardTarget

control_map = load_control_map(
    {
        "dofs": {
            "walk": ["keyboard.hold.letter.w", "keyboard.hold.letter.a"],
            "fire": {"target": "keyboard.tap.edit.space", "debounce_s": 0.1},
        }
    }
)
controls = resolve(control_map, KeyboardTarget().capabilities())

walk = controls.dofs["walk"]
assert walk.states == ("up", "down")  # the target said so; the map never mentioned states
assert walk.rest == "up"
assert controls.dofs["fire"].debounce_s == 0.1  # this one the map did say
```

The keyboard declares `keyboard.hold.letter.w` as discrete with two states, so `walk` inherits
those properties. The map says nothing about states. It sets `debounce_s`, the time a state
must hold before this control loop accepts it. That duration belongs to the control loop,
which is why it lives in the map. The keyboard does not define it.

`resolve()` rejects the whole map if it has unknown addresses. It never binds only the entries it recognizes.

<!--docs:run-->
```python
from myogestic.controls import Capability

arm = [
    Capability("arm.wrist.rotation", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability("arm.grip", "continuous", lo=0.0, hi=1.0, rest=0.0),  # one-way
]

try:
    resolve(load_control_map({"dofs": {"twist": "arm.wrist.rotate"}}), arm)
except ValueError as exc:
    assert "Did you mean: arm.wrist.rotation" in str(exc)

controls = resolve(load_control_map({"dofs": {"twist": "arm.wrist.rotation"}}), arm)
assert controls.dofs["twist"].lo == -1.0  # signed, because that capability is
```

Silently dropping an unknown control would look like a control holding still. The operator
could move, see nothing happen and mistakenly investigate the model.
When every target reports `claims`, [`ControlBus`][myogestic.controls.ControlBus] checks that
some target claims every alias and rejects any alias that no target drives. Leaving `claims` off
means the target accepts every alias, as a recorder or test double might. Such a target
covers the whole frame, so the bus cannot detect an undriven alias. An empty `claims` set
means the target drives nothing; it does not bypass the check. With no targets, the bus
can still sanitize and return a frame without a coverage check.

## Everything that moves is a target

A [`Target`][myogestic.controls.Target] drives a prosthesis on a serial port, a motor controller,
a cursor, a keyboard or a remote Godot window. It has three methods and a list of `Capability`.

The transport is yours. `send` receives named values and does whatever your device needs with
them, using `serial.write`, a UDP datagram, an MQTT publish or a library call. The shipped
[`KeyboardTarget`][myogestic.keyboard.KeyboardTarget] opens no socket at all.

Choose an adapter for your device.

| | you write the target | it is already written |
|---|---|---|
| when | anything you can `import` and call | your device is already its own program and serves MyoGestic's contract: `GetControlManifest` over gRPC, one LSL stream per address |
| how much | three methods and a `serial.write` | none of it. Construct [`RemoteTarget`][myogestic.remote.RemoteTarget] and hand it to the bus |
| what you write instead | the target | the *other side*: the contract your program serves |
| guide | [Drive your own device](../how-to/add-a-target.md) | [Drive a remote target](../how-to/drive-a-remote-target.md) |

A device running its own firmware still needs a Python target that writes to its port.
Firmware alone does not provide the remote contract. Use the remote adapter only if the
device already serves the gRPC and LSL contract. `examples/synthetic/servo_hand.py` is a whole six-servo hand.

Both adapters declare a manifest and use addresses from the same map. One `ControlBus` can
drive a mixed list. Moving a device into its own process leaves the map unchanged. To take the remote route end to end on
hardware of your own, follow [Your first remote target](../tutorials/your-first-remote-target.md),
which builds one in seven stages with a checkpoint at each.

Use [`RemoteTarget`][myogestic.remote.RemoteTarget] as the local adapter for any program
that serves the contract. It reads the manifest, publishes one LSL stream per address, and
forwards discrete edges over gRPC. It knows nothing about what the far side drives. The Virtual
Hand is one such program. See [Integrate the Virtual Hand](../how-to/integrate-vhi.md);
[Your first remote target](../tutorials/your-first-remote-target.md) builds another.

!!! note "Outputs do not drive devices"
    [`Outlet`][myogestic.outputs.Outlet] is a paced latest-wins sender that a target writes
    through. `RemoteTarget` builds one per address. An outlet alone has no aliases, no declared
    range, no clamp and no rest on shutdown. Use a target for these guarantees. See
    [Publish a data stream](../how-to/add-an-output.md).

## Binding retries while the target is unavailable

[`connect_controls()`][myogestic.controls.connect_controls] returns `None` until every device
can answer. It does not raise for this normal waiting state or leave a half-built bus to
clean up. An application can launch its devices from the UI and retry binding.

[`ControlLink`][myogestic.controls.ControlLink] manages binding retries. Applications need
no separate nullable bus, guard or retry loop of their own.

<!--docs:run-->
```python
from myogestic.controls import ControlLink


class NotStartedYet:
    def capabilities(self):
        return None  # the target is not up — not an empty manifest


link = ControlLink(load_control_map({"dofs": {"twist": "arm.wrist.rotation"}}), [NotStartedYet()])

assert link.ensure() is None  # try again on the next click
assert link.bus is None  # and read this from the predict thread
```

- `link.ensure()` is idempotent and one attribute read once it has bound, so it is safe at the
  top of every UI handler that needs the device.
- `link.bus` stays `None` until something answers. `@pipeline.predict` reads it and no-ops.
- Never call `ensure()` from `@pipeline.predict`. Asking a remote target what it exports costs a
  blocking RPC, and that callback runs at `predict_hz` with a deadline. Skip delivery while the bus is unavailable.

For automatic reconnect from a UI loop, use
[`ControlLinkConnector`][myogestic.controls.ControlLinkConnector]. Its `poll()` returns
immediately, rate-limits attempts, and never starts a second capability request while the first
is still in flight:

```python
from myogestic.controls import ControlLinkConnector

connector = ControlLinkConnector(link, retry_s=2.0)


def update_ui():
    connector.poll()
    status_label.set_text(connector.status)
```

Prediction still reads `link.bus`; `poll()` belongs only in the UI loop. Call
`connector.stop()` during teardown to stop retrying and rest a bus that has connected.

!!! warning "One link is one failure domain"
    Resolution is atomic across every target in a link. If any target cannot provide its
    manifest, none are bound. This keeps aliases aimed at the missing target from being dropped. Give independently useful outputs separate maps and links, so an
    unavailable visualization cannot disable a keyboard, robot, or another output.

A device that answers `None` means
"cannot say yet", and an empty manifest means "drives nothing". If the map names addresses absent from the
combined manifest, resolution raises instead of building an empty bus.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for symptoms and fixes.

- Writing a kind or a range into the map. It has no place for one. If you think you need it,
  the device's manifest is wrong, not the file.
- Publishing to a stream you named yourself. A stream's name is the address, and the address
  is the device's to declare. Map your aliases onto addresses and let
  [`RemoteTarget`][myogestic.remote.RemoteTarget] publish one stream per DOF. When VHI moved
  to one stream per DOF, every stream name changed. Applications that read names from the
  manifest needed no code changes.
- Reaching for a second address for the other direction. A signed control already has both
  halves; emit a negative value, or give that address a negative `weight`.
- Low-pass filtering a discrete control. Averaging "rest" and "fist" interpolates through
  states nobody selected. `debounce_s` is the stability gate; smoothing is for continuous DOFs.
- Calling `link.ensure()` from `@pipeline.predict`. It blocks on an RPC. Read `link.bus` there.
- Trusting a device's read-back to prove a sign. It agrees with the device whichever way both
  point. Look at the device.
