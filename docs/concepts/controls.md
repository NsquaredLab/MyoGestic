# Controls

A **control** is one thing a person drives: a finger, a wrist, a cursor axis, a key. MyoGestic
never hard-codes a list of them. Instead a device declares what it can render, your
application picks its own names for its model's outputs, and a **control map** — a TOML file —
pairs the two.

That file is the whole configuration surface. Everything else on this page is what the two
halves of a line in it mean.

## Two vocabularies meet on one line

```toml
[dofs]
my_thumb = "vhi.prediction.thumb.flexion"
```

| | left of `=` | right of `=` |
|---|---|---|
| whose name is it | **yours** | **the device's** |
| what is it | the key your model's `predict()` returns | an *address* the device declares |
| who reads it | nothing — it is never parsed for meaning | the device, which owns what it means |
| how far does it travel | nowhere; it never leaves the app | onto the wire as the control's identity |

Each entry under `[dofs]` is one **DOF** — one [degree of
freedom](../reference/glossary.md#dof). The left side is an **alias**. `my_thumb`, `fist`,
`drive_x` — anything readable. MyoGestic prescribes nothing about it and derives nothing from
it, so the same alias can point at a Virtual Hand in one file and at a cursor axis in another
with no code change.

The right side is an **address**: dotted, lowercase, at least two segments. The first segment
namespaces the device (`vhi.`, `keyboard.`, `cursor.`), so two devices cannot collide inside one
map. Crucially, the address is *all* the map says. Whether `vhi.prediction.thumb.flexion` takes a
number or a held state, what its range is, what its neutral value is — the device declares every
one of those, and MyoGestic asks.

## The map is a file

`examples/controls/regression.toml`, its whole `[dofs]` table:

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

Six model outputs, six addresses. Now `examples/controls/playground.toml`, which is the same
idea with the point made:

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

A keystroke and a 3-D hand sit in the same table, a line apart. One of them is a separate
Godot application reached over gRPC and LSL; the other is `pynput` in this process. **Nothing in
the file says so**, and that is the design: how a value reaches a device is the device's
business, and the map only ever names *what* is driven, never *how* it is delivered. Pointing an
application at a second device is lines in this file plus one more `Target` object in the list
handed to the bus — nothing in between changes.

The value shapes are the only grammar: a bare string is one address, an array fans one output
out to several, and a table is the explicit form where a per-address `weight` or a
`debounce_s` gate is written. [`docs/api/controls.md`](../api/controls.md) has the full rules
and every option.

## The one convention a device may not redefine

Continuous control values are **signed and normalised**:

- the range is `[-1, 1]`;
- `0` is rest;
- `+1` is the direction the control's **name** denotes — `…thumb.flexion` at `+1` flexes, and at
  `-1` extends. There is no second address for the other direction.
- a one-way control declares `lo=0.0`, and then only ever moves one way.

A device owns its own units — degrees for a renderer, pixels per second for a cursor — and
converts on its own side. What it may not do is decide that on its wire `+1` means extension.

That rule is not tidiness. **A sign error survives every test a device and its own read-back can
agree on**, because they agree whichever way they point: the renderer flexes when told to extend,
its read-back stream reports exactly the flexion it rendered, and the contract suite is green.
This repository shipped that bug with its own tests passing throughout. The only check that
catches it is outside the loop — a person looking at the device.

## Continuous and discrete are different things

| | continuous | discrete |
|---|---|---|
| what it is | an amount, this instant | a **held state**, until changed |
| how it travels | one value per tick, on a stream | on change only, over the device's own command channel |
| repeated? | every tick, forever | never — a repeat is expressed by returning through rest first |
| examples | `vhi.prediction.index` | `vhi.control.gesture`, `keyboard.tap.edit.space` |

A held state does not belong on a per-tick wire: re-sending it at 32 Hz is 32 keystrokes a
second, not one held key. So [`ControlBus`][myogestic.controls.ControlBus] delivers continuous
values as a full frame every tick and discrete ones as **edges** — only the states that settled
*this* tick — and each device does whatever its command channel is. For VHI that is a `SetControl`
gRPC call; for [`KeyboardTarget`][myogestic.keyboard.KeyboardTarget] it is a key-down or key-up.

Which addresses are which is `kind` in the **device's** manifest. The map never says, and cannot:
change a device's build so a control becomes discrete and the same map file keeps working.

A button is the one case that does not want the gate: [`ControlBus.select`][myogestic.controls.ControlBus.select]
delivers a state immediately **and rebases** the DOF's debounce, so the predict ticks that
follow — still carrying the class from a sliding window that has not caught up — do not
re-fire what the click just did.

## Who answers what

| question | answered by |
|---|---|
| which controls exist, and what each one *is* | the device — its manifest (`GetControlManifest` for a renderer, a local list for the keyboard) |
| what my model's outputs are called, and where each goes | the map — your file |
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

Note what came from where. `walk` is discrete with two states because the keyboard declares
`keyboard.hold.letter.w` that way — the file says nothing about states. `debounce_s` is the
reverse: how long a state must hold before it counts is a property of *this* control loop, not of
the keyboard, so it lives in the map.

And `resolve()` **refuses** rather than rendering the part it understood:

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

Binding the addresses it recognised and quietly dropping the typo would be worse than
failing, because **a silently dropped control is indistinguishable from one holding still**. You
would move, see nothing happen, and go looking at the model. The same rule runs one level down:
[`ControlBus`][myogestic.controls.ControlBus] checks that *some* target claims every alias, and
refuses a control nothing renders.

## Two ways to reach a device

This is the fork the how-to guides assume you have already taken.

| | a **target** | a **renderer** |
|---|---|---|
| what it is | an in-process Python object | a separate application |
| how it is driven | a `ControlBus` calls it directly, on the thread MyoGestic already owns | gRPC for the manifest and discrete state, LSL for continuous values |
| you write | three methods — `bind`, `send`, `stop` | a gRPC service and an LSL reader, in any language |
| right for | a cursor, a serial motor controller, a library you can import, anything in this process | its own window, its own process, its own machine, another language |
| guide | [Drive your own device](../how-to/add-a-target.md) | [Build a renderer](../how-to/build-a-renderer.md) |

The distinction is only about *where the code runs*. Both declare a manifest, both are named by
address in the same map, and a single `ControlBus` drives a mixed list of them. To take the
renderer route end to end on hardware of your own, follow
[Integrate your own interface](../tutorials/integrate-your-interface.md), which builds one in
seven stages with a checkpoint at each.

A renderer still needs a target on this side to talk to it — but you do not write that one:
[`RendererTarget`][myogestic.renderer.RendererTarget] is the shipped adapter for **any**
renderer that serves the contract. It reads the manifest, publishes one LSL stream per
address, and forwards discrete edges over gRPC. It knows nothing about what the renderer
renders. The Virtual Hand is one such renderer — see
[Integrate the Virtual Hand](../how-to/integrate-vhi.md) — and
[Integrate your own interface](../tutorials/integrate-your-interface.md) builds another.

## Binding is deferred, not decided

A map cannot be resolved until a device can answer, and an application that launches its device
from its own UI necessarily binds *before* that device exists. So
[`connect_controls()`][myogestic.controls.connect_controls] returns `None` in that case rather
than raising: "not yet" is a normal state, not a fault, and there is nothing half-built to
clean up.

[`ControlLink`][myogestic.controls.ControlLink] holds that retry, so no application has to carry
a nullable bus, a guard and a re-try of its own:

<!--docs:run-->
```python
from myogestic.controls import ControlLink


class NotStartedYet:
    def capabilities(self):
        return None  # the renderer is not up — not an empty manifest


link = ControlLink(load_control_map({"dofs": {"twist": "arm.wrist.rotation"}}), [NotStartedYet()])

assert link.ensure() is None  # try again on the next click
assert link.bus is None  # and read this from the predict thread
```

- `link.ensure()` is **idempotent** and one attribute read once it has bound, so it is safe at the
  top of every UI handler that needs the device.
- `link.bus` stays `None` until something answers. `@pipeline.predict` reads it and no-ops.
- **Never call `ensure()` from `@pipeline.predict`.** Asking a renderer what it exports costs a
  blocking RPC, and that callback runs at `predict_hz` with a deadline. A frame with no bus is
  much cheaper than a stalled control loop.

A device that answers `None` is distinct from one that answers with an empty list: `None` means
"cannot say yet", and an empty manifest would mean "renders nothing", which would resolve happily
into a bus that silently drives nothing.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across
every subsystem.

- **Writing a kind or a range into the map.** It has no place for one. If you think you need it,
  the device's manifest is wrong, not the file.
- **Publishing to a stream you named yourself.** A stream's name is the address, and the address
  is the device's to declare. Map your aliases onto addresses and let
  [`RendererTarget`][myogestic.renderer.RendererTarget] publish: VHI changed every stream name it
  had when it moved to one stream per DOF, and every application that had let the manifest answer
  needed no edit at all.
- **Reaching for a second address for the other direction.** A signed control already has both
  halves; emit a negative value, or give that address a negative `weight`.
- **Low-pass filtering a discrete control.** Averaging "rest" and "fist" interpolates through
  states nobody selected. `debounce_s` is the stability gate; smoothing is for continuous DOFs.
- **Calling `link.ensure()` from `@pipeline.predict`.** It blocks on an RPC. Read `link.bus` there.
- **Trusting a device's read-back to prove a sign.** It agrees with the device whichever way both
  point. Look at the device.
