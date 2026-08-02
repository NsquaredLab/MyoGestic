# Control standard

A control space is a **mapping**, in a file: your name for a model output on the left, a
control the target declares on the right. The left side is yours and arbitrary. The right
side belongs to the target, which also declares what the control *is*: a number or a held
state, its range, its states. MyoGestic hard-codes none of that, so a Virtual Hand, a
keyboard, a cursor and a prosthesis each keep their own vocabulary, and a build that grows
a control needs no change on this side.

New to this? [Concepts › Controls](../concepts/controls.md) explains the system this page
documents: what a control is, why the standard is fixed, and how to choose between an
in-process target and a remote one.

Continuous controls are **normalized**: `+1` is the direction the control denotes, rest is
`0`, and the range is signed when the target says the control is. Discrete controls are
separate on purpose: a held state delivered on change is a different kind of value.

!!! tip "There is no separate control for the other direction"
    A signed control already has both halves: `+1` on `vhi.prediction.thumb` flexes the
    thumb and `-1` extends it. There is **no** `…thumb.extension` address; a model that
    wants extension emits a negative value, or a mapping gives that target a negative
    `weight`.

    Two things that look like exceptions:

    * **`vhi.prediction.thumb.abduction`** is a second axis, not the other half of the
      first. The thumb has two; the short `…thumb` is *declared* to mean flexion, and the
      other one has to be named, because silently picking one of two would be a guess.
      Every other digit has one axis, so its short form is all there is.
    * **`ThumbExtension`** is one of `vhi.control.gesture`'s **movement presets**: a held
      state on the control hand. A preset commands a whole-hand pose in one held state, a
      compound shape no single continuous address expresses.

    **One address per control**, always: the address is the control's identity and also
    the name of the one-channel LSL stream that carries it. A target that advertised two
    spellings of one control would make "these two aliases collide" impossible to decide
    from a manifest.

!!! tip "Inspect the whole control path with `tools/inspect_control.py`"
    A narrated walkthrough runs the whole path: declaration, the two kinds of control,
    the wire frame, and the negotiation against whatever Virtual Hand you have.

    ```bash
    uv run --extra grpc python tools/inspect_control.py
    ```

    Run it with no Virtual Hand at all and it still walks the first three steps, then
    shows what a target does when the far side is absent. Launch a VHI and run it again
    for the handshake: it prints a different step 4 for a v2 build, a v1 build, and
    nothing at all.

## Declaring a control space

Write a TOML file. A ready-to-copy one ships at
[`examples/controls/hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/hand.toml):

```toml
[dofs]
# Left side: your model's output names. Right side: controls VHI declares.
my_thumb_spread = "vhi.prediction.thumb.abduction"

fist = [                                       # one output, fanned out
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },   # ...with a per-target gain
  { target = "vhi.prediction.index" },
  { target = "vhi.prediction.middle" },
  { target = "vhi.prediction.ring" },
  { target = "vhi.prediction.little" },
]

gesture = { target = "vhi.control.gesture", debounce_s = 0.1 }
```

**The left side is yours.** `my_thumb_spread`, `fist`, `gesture`, whatever your model
calls its outputs. Nothing prescribes these names or reads meaning out of them. A control
takes only *one* output, so no two entries may name the same address; a fan-out is how one
output reaches several.

**The right side belongs to the target.** `vhi.prediction.index` is a name VHI declares
in its own manifest, along with everything needed to send it: whether it takes a number
or a held state, its range, its states. Ask a running target what it exports:

```bash
uv run --extra grpc python tools/inspect_control.py
```

Load it and resolve it:

```python
import tomllib
from myogestic.controls import load_control_map, resolve

with open("hand.toml", "rb") as f:          # "rb" — tomllib requires binary
    control_map = load_control_map(tomllib.load(f))

# Resolution needs a live target: it is what declares the semantics.
controls = resolve(control_map, vhi.control_client().capabilities())
```

**Mapping-first**: the *shape* of each value says how a value travels. A bare string is
one target control; an array is a fan-out reaching several; a table with `target`/`targets`
is the explicit form, and the only place a per-target `weight` or a `debounce_s` stability
gate is written. Whether a control is a number or a held state stays out of this file: the
target declares it.

!!! note "`load_control_map` takes a Mapping, not a path"
    The library reads no configuration files, by design, so the snippet above opens the
    file itself. The same call accepts JSON, a dict literal, a row from a database, or a
    config system you already have. TOML is what a *human* wants to edit, so the shipped
    example is TOML.

!!! warning "A mapping becomes a control space when a target answers"
    `load_control_map` checks structure; whether `vhi.prediction.index` is a number or a
    held state is the target's to declare. So an application that launches its own target
    resolves *after* startup rather than at import. The examples all build their bus
    lazily for that reason.

### Classification uses the same mapping

A classifier produces an **activation** (open or closed) where a regressor produces a
position, and an activation is just a control value, so it travels the same mapping. Add a
`threshold_fraction`, the probability cutoff, to say the input is a classifier's
confidence:

```toml
fist = { targets = [
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },
  { target = "vhi.prediction.index" },
], threshold_fraction = 0.5 }
```

Push the model's probability and the bus gates it to exactly `0.0` or `1.0` before
anything else sees it: before the weights, before the wire, before the recording. From
there it is an ordinary value, `0` to every listed control when inactive and `1 × weight`
when active. The target receives continuous per-control values either way, with no
separate state command.

Drop the `threshold_fraction` and the identical mapping serves a regressor emitting `0..1`
directly. Gating here rather than in a separate discrete path is what lets one mapping
serve both: a continuous address is a *position*, so a raw `0.73` streamed into one says
the finger is 73% curled, a different statement from 73% confident that it is closed.

Map onto a **discrete** address instead when the thing genuinely is a state rather than
an amount: a preset, a keypress, a mode. `examples/controls/classification.toml` shows
the activation form and `examples/controls/classification_grpc.toml` the discrete one.

::: myogestic.controls.load_control_map

::: myogestic.controls.resolve

::: myogestic.controls.Capability

::: myogestic.controls.ControlMap

::: myogestic.controls.Binding

::: myogestic.controls.TargetRef

::: myogestic.controls.read_control_space

::: myogestic.controls.ControlSet

::: myogestic.controls.Continuous

::: myogestic.controls.Discrete

::: myogestic.controls.Dof

## Delivering a frame

One bus sanitises each frame exactly once and fans it out to every target, owning
an ordering that is easy to get subtly wrong per-application.

::: myogestic.controls.ControlBus

::: myogestic.controls.connect_controls

::: myogestic.controls.ControlLink

::: myogestic.controls.Target

## Targets

::: myogestic.remote.RemoteTarget

::: myogestic.remote.ControlSink

### Negotiating with the target

Hand `RemoteTarget` a control client and it **asks** what the target drives at bind time,
then encodes according to the answer.

**One target drives the whole map.** It owns one LSL outlet per address it drives, each
named for that address and one channel wide, all built after negotiation has resolved
which addresses those are:

```python
vhi = virtual_hand()
client = vhi.control_client()
# No stream is named here and none is counted. `interface=` is why: which controls exist
# is the manifest's answer, and each one's stream is named for its own address, so both
# facts arrive together once `bind` has something to ask.
target = RemoteTarget(client=client, interface=vhi)
bus = connect_controls(control_map, [target])   # None while the far side is unreachable
```

An application that launches its own target binds before that target exists, so it
holds a [`ControlLink`][myogestic.controls.ControlLink] instead and calls `ensure()` from
each handler that needs the hand: same arguments, plus the retry.

The client is **required**: every address, range and state comes from that answer. A
target that answers but reports an older `vocabulary_version` is refused by name, since it
would be listening for a stream layout this client no longer publishes and would report
nothing while the rig stayed still.

Four things are refused rather than half-driven: a target too old for the vocabulary this
client speaks, an address the target does not export, one it exports as something other
than a number, and two aliases aimed at one control. A partly understood negotiation
leaves some controls believed driven and others quietly dropped, and a dropped control is
indistinguishable from one that is working and holding still.

One case is **deferred** instead: a target that has not answered *at all*. Nothing is
decided until [`negotiate`][myogestic.remote.RemoteTarget.negotiate] settles it. A Virtual
Hand older than 2.0 has no manifest to answer with, and MyoGestic 2.x carries no fallback
table to drive one from, but it answers `capabilities()` with `None` exactly as a target
that is simply not up yet does, so it is retried the same way.

::: myogestic.remote.InterfaceSpec.control_client

### Three layers of smoothing

Three separate mechanisms sit at three different places, and collapsing any two of them
is a bug:

| Layer | Where | Applies to | Authoritative? |
|---|---|---|---|
| **1. Continuous smoothing** | `ControlBus(smoothing=...)`, MyoGestic | continuous DOFs | **Yes** - it decides the value that is commanded |
| **2. Debounce** | `Discrete.debounce_s`, MyoGestic | discrete DOFs | **Yes** - it decides *when* a state transition happens |
| **2b. Dead zone + hysteresis** | `ControlBus(dead_zone=...)`, `ControlBus(hysteresis=...)`, MyoGestic | continuous DOFs | **Yes** - they decide the value that is commanded |
| **3. Presentation blending** | the target (`control_client().set_presentation`) | how a commanded value looks | **No** - appearance only |

Layer 1 runs before any target sees a frame, and that is what makes it authoritative:
smoothing after delivery would mean different targets acted on different values.

Layer 2 is the one people reach for layer 1 to solve. Low-pass filtering a discrete
control as though it were an axis averages "rest" and "fist" and interpolates through
states nobody selected. What a noisy classifier needs is a *stability gate*: hold the new
state for `debounce_s` before it counts, with optional hysteresis so a value hovering near
a boundary settles on one side. `debounce_s` is declared on the DOF for that reason,
rather than configured on the filter.

Layer 3 affects presentation only. With blending on and no debounce every accepted transition
is still applied; blending smooths how the change is drawn, not whether it happened.

### Recording is not control

A discrete DOF is a **held state**: ask for a grip, hold a grip. Collecting regression
training data wants the opposite, a control hand that keeps *moving*, so the recorded
kinematics sweep a continuous range for EMG windows to align against.

Two different jobs, so two vocabularies. The sweep lives in the **recording aid**, never
in the control standard, because bending a held state to accommodate data collection
would make `hand.grip` mean "grip, unless someone is recording".

While a recording trajectory runs it owns the control hand, and discrete DOFs are refused
with a reason rather than silently interrupting the trajectory a recording is aligned
against. Continuous DOFs keep flowing.

::: myogestic.remote.InterfaceSpec.recording_client

## Encoding helpers

Wire-level helpers, for a target that needs a vector rather than a mapping.

::: myogestic.controls.encode

::: myogestic.controls.decode

::: myogestic.controls.clip

::: myogestic.controls.substitute_rest
