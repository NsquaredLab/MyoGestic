# Control standard

MyoGestic defines **one** canonical, application-independent control vocabulary. An
app declares *what it controls* — `index.flexion`, `wrist.rotation`, `hand.grasp` —
and a [`Target`][myogestic.controls.Target] renders those names in whatever a
specific application wants on its wire. The Virtual Hand, a keyboard, a cursor and a
prosthesis are all adapters; none of them gets to define the vocabulary.

Continuous DOFs are **signed and normalized**: the domain is `[-1, 1]`, `+1` is the
direction the name denotes, and rest is `0`. Discrete DOFs are separate on purpose —
a held state delivered on change is not the same thing as a number.

!!! tip "See it work before reading further"
    There is a narrated walkthrough that runs the whole path — declaration, the two
    kinds of control, the wire frame, and the negotiation against whatever Virtual Hand
    you have:

    ```bash
    uv run --extra grpc python tools/inspect_canonical_control.py
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
"index.flexion" = "continuous"                                 # [-1, 1], rest 0
"hand.grasp"    = ["rest", "fist", "pinch"]                    # array => discrete
"grip.force"    = { kind = "continuous", range = [0.0, 1.0] }  # one-way
```

Load it in two lines:

```python
import tomllib
from myogestic.controls import load_dofs

with open("hand.toml", "rb") as f:          # "rb" — tomllib requires binary
    controls = load_dofs(tomllib.load(f))
```

**Mapping-first**: the *shape* of each value is the discriminator. A bare string is a
continuous DOF at its defaults, a bare array is a discrete DOF's states, and a table is
the explicit form for a one-way range, a non-zero rest, a label, or a `debounce_s`
stability gate.

!!! note "`load_dofs` takes a Mapping, not a path"
    That is deliberate, and it is why the snippet above opens the file itself. The
    library reads no configuration files — a design rule, not an oversight — so the same
    call accepts JSON, a dict literal, a row from a database, or a config system you
    already have. TOML is what a *human* wants to edit, which is why the shipped example
    is TOML.

::: myogestic.controls.load_dofs

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
canonical client and it **asks** at bind time, then encodes according to the answer:

```python
vhi = virtual_hand()
target = VhiTarget(vhi.outlet(), client=vhi.canonical_client())
bus = ControlBus(controls, targets=[target])
```

Against a Virtual Hand that speaks the v2 contract this negotiates the channel layout
by name and lets discrete DOFs through as well. Against an older build the handshake
comes back empty and the target falls back to the legacy pose on its own — nothing
downstream changes either way, which is the point.

The fallback is **all-or-nothing**. A partly-understood negotiation is worse than
none: it would leave some DOFs believed rendered and others quietly dropped, and a
dropped joint is indistinguishable from a joint that is working and holding still. So
a refused DOF, a channel order with no place for a declared name, or a reply that will
not state its wire encoding all fall the whole way back.

::: myogestic.vhi.interfaces.InterfaceSpec.canonical_client

### Three layers of smoothing, and why they are not interchangeable

Smoothing is not one thing. Three separate mechanisms exist, at three different
places, and collapsing any two of them is a bug:

| Layer | Where | Applies to | Authoritative? |
|---|---|---|---|
| **1. Continuous smoothing** | `ControlBus(smoothing=...)`, MyoGestic | continuous DOFs | **Yes** — it decides the value that is commanded |
| **2. Debounce + hysteresis** | `Discrete.debounce_s`, `ControlBus(hysteresis=...)`, MyoGestic | discrete DOFs | **Yes** — it decides *when* a state transition happens |
| **3. Presentation blending** | the renderer (`canonical_client().set_presentation`) | how a commanded value looks | **No** — appearance only |

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

A canonical discrete DOF is a **held state**: ask for a grip, hold a grip. Collecting
regression training data wants the opposite — a control hand that keeps *moving*, so
the recorded kinematics sweep a continuous range for EMG windows to align against.

Those are different jobs, so they have different vocabularies. The sweep lives in the
**recording aid**, never in the control standard, because bending a held state to
accommodate data collection would make `hand.grip` mean "grip, unless someone is
recording".

While a training program runs it owns the control hand, and discrete DOFs are refused
with a reason rather than silently interrupting the trajectory a recording is aligned
against. Continuous DOFs are unaffected.

::: myogestic.vhi.interfaces.InterfaceSpec.training_client

## Encoding helpers

Wire-level helpers, for a target that needs a vector rather than a mapping.

::: myogestic.controls.encode

::: myogestic.controls.decode

::: myogestic.controls.clip

::: myogestic.controls.substitute_rest
