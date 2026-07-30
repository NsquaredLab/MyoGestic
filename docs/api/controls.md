# Control standard

A control space is a **mapping**, in a file: your name for a model output on the left, a
control the target declares on the right. The left side is yours and arbitrary — nothing
here reads meaning out of it. The right side belongs to the target, which also declares
what the control *is*: a number or a held state, its range, its states. MyoGestic hard-codes
none of that, so a Virtual Hand, a keyboard, a cursor and a prosthesis each keep their own
vocabulary and a build that grows a control needs no change on this side.

Continuous controls are **normalized**: `+1` is the direction the control denotes, rest is
`0`, and the range is signed when the target says the control is. Discrete controls are
separate on purpose — a held state delivered on change is not the same thing as a number.

!!! tip "There is no separate control for the other direction"
    A signed control already has both halves: `+1` on `vhi.prediction.thumb` flexes the
    thumb and `-1` extends it. So there is **no** `…thumb.extension` address, and you do not
    need one — a model that wants extension emits a negative value, or a mapping gives that
    target a negative `weight`.

    Two things that look like exceptions:

    * **`vhi.prediction.thumb.abduction`** is a genuinely different control, not the other
      half of one. The thumb has two axes; the short `…thumb` is *declared* to mean flexion,
      and the second axis has to be named because silently picking one of two would be a
      guess. Every other digit has one axis, so its short form is all there is.
    * **`ThumbExtension`** is one of `vhi.control.gesture`'s **movement presets** — a held
      state on the control hand, not a number and not an address. It exists because a
      preset commands a whole-hand pose in one held state — a compound shape no single
      continuous address expresses.

    A renderer is free to publish one control under several addresses — `…index` and
    `…index.flexion` on one channel, say — and the manifest's `channel` field is what tells
    you two names are one control. VHI advertises each of its controls once.

!!! tip "See it work before reading further"
    There is a narrated walkthrough that runs the whole path — declaration, the two
    kinds of control, the wire frame, and the negotiation against whatever Virtual Hand
    you have:

    ```bash
    uv run --extra grpc python tools/inspect_control.py
    ```

    It is safe to run with no Virtual Hand at all: it still walks the first three steps
    and then shows what a target does when its renderer is absent. Launch a VHI and run
    it again to see the handshake — it prints a different step 4 for a v2 build, a v1
    build, and nothing at all.

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

**The left side is yours.** `my_thumb_spread`, `fist`, `gesture` — whatever your model
calls its outputs. Nothing prescribes these names or reads meaning out of them. A control
may take only *one* output, though, so no two entries may name the same address; that is
what a fan-out is for.

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
gate is written. Whether a control is a number or a held state is **not** written here —
the target declares that.

!!! note "`load_control_map` takes a Mapping, not a path"
    That is deliberate, and it is why the snippet above opens the file itself. The library
    reads no configuration files — a design rule, not an oversight — so the same call
    accepts JSON, a dict literal, a row from a database, or a config system you already
    have. TOML is what a *human* wants to edit, which is why the shipped example is TOML.

!!! warning "A mapping is not a control space until a target answers"
    `load_control_map` checks structure; it cannot know whether `vhi.prediction.index` is
    a number or a held state, because that is the target's to declare. So an application
    that launches its own target resolves *after* startup, not at import — see the
    examples, which all build their bus lazily for exactly this reason.

### Classification uses the same mapping

A classifier produces an **activation** — open or closed — not a position, and an
activation is just a control value. So it travels the mapping a regressor travels. Add a
`threshold_fraction` — the probability cutoff — to say the input is a classifier's
confidence:

```toml
fist = { targets = [
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },
  { target = "vhi.prediction.index" },
], threshold_fraction = 0.5 }
```

Push the model's probability and the bus gates it to exactly `0.0` or `1.0` before
anything else sees it — before the weights, before the wire, before the recording. From
there it is an ordinary value: `0` to every listed control when inactive, `1 × weight`
when active. The target receives continuous per-control values either way, and no
separate state command exists.

Drop the `threshold_fraction` and the identical mapping serves a regressor emitting `0..1`
directly. That is the point of gating here rather than in a separate discrete path: a
continuous address is a *position*, and streaming a raw `0.73` into one says the finger
is 73% curled, which is not what a 73%-confident classifier meant.

Map onto a **discrete** address instead when the thing genuinely is a state rather than
an amount — a preset, a keypress, a mode. `examples/controls/classification.toml` shows
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

::: myogestic.controls.Target

## Targets

::: myogestic.vhi.VhiTarget

::: myogestic.vhi.PoseSink

### Negotiating with the target

A target does not have to guess what an application can render. Hand `VhiTarget` a
control client and it **asks** at bind time, then encodes according to the answer:

```python
vhi = virtual_hand()
target = VhiTarget(vhi.outlet(), client=vhi.control_client())
bus = ControlBus(controls, targets=[target])
```

The client is **required**, because every channel, range and state comes from that
answer. A Virtual Hand older than 2.0 has no manifest to answer with and is reported as
unsupported — MyoGestic 2.x has no fallback and no table of channel numbers.

What it refuses, rather than half-rendering: an address the renderer does not export,
one it does not carry on this stream, two aliases aimed at one control, a channel order
with no place for a declared name, or a reply that will not state its wire encoding. A
partly-understood negotiation is worse than none — it would leave some controls believed
rendered and others quietly dropped, and a dropped control is indistinguishable from one
that is working and holding still.

One case is **deferred** rather than refused: a renderer that has not answered *at all*.
An application that launches VHI from its own button binds before VHI exists, so nothing
is decided until [`negotiate`][myogestic.vhi.VhiTarget.negotiate] settles it. A renderer
that answers and does not speak v2 is a settled fact and raises.

::: myogestic.vhi.interfaces.InterfaceSpec.control_client

### Three layers of smoothing, and why they are not interchangeable

Smoothing is not one thing. Three separate mechanisms exist, at three different
places, and collapsing any two of them is a bug:

| Layer | Where | Applies to | Authoritative? |
|---|---|---|---|
| **1. Continuous smoothing** | `ControlBus(smoothing=...)`, MyoGestic | continuous DOFs | **Yes** — it decides the value that is commanded |
| **2. Debounce + hysteresis** | `Discrete.debounce_s`, `ControlBus(hysteresis=...)`, MyoGestic | discrete DOFs | **Yes** — it decides *when* a state transition happens |
| **3. Presentation blending** | the renderer (`control_client().set_presentation`) | how a commanded value looks | **No** — appearance only |

Layer 1 runs before any target sees a frame, which is what makes it authoritative:
smoothing after delivery would mean different targets acted on different values.

Layer 2 is the one people reach for layer 1 to solve, and must not. A discrete control
is **never** numerically low-pass filtered as though it were an axis — averaging
"rest" and "fist" interpolates through states nobody selected. What a noisy classifier
needs is a *stability gate*: hold the new state for `debounce_s` before it counts, with
optional hysteresis so a value hovering near a boundary does not oscillate. That is why
`debounce_s` is declared on the DOF rather than configured on the filter.

Layer 3 is real and worth having — a hand that snaps between poses looks wrong — but it
is only cosmetic. It cannot make an unstable prediction stable. A renderer with
blending on and no debounce still jumps between states; it just does so smoothly, which
is arguably worse because it *looks* deliberate.

### Recording is not control

A discrete DOF is a **held state**: ask for a grip, hold a grip. Collecting
regression training data wants the opposite — a control hand that keeps *moving*, so
the recorded kinematics sweep a continuous range for EMG windows to align against.

Those are different jobs, so they have different vocabularies. The sweep lives in the
**recording aid**, never in the control standard, because bending a held state to
accommodate data collection would make `hand.grip` mean "grip, unless someone is
recording".

While a recording trajectory runs it owns the control hand, and discrete DOFs are
refused with a reason rather than silently interrupting the trajectory a recording is
aligned against. Continuous DOFs are unaffected.

::: myogestic.vhi.interfaces.InterfaceSpec.recording_client

## Encoding helpers

Wire-level helpers, for a target that needs a vector rather than a mapping.

::: myogestic.controls.encode

::: myogestic.controls.decode

::: myogestic.controls.clip

::: myogestic.controls.substitute_rest
