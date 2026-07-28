# Control standard

MyoGestic defines **one** canonical, application-independent control vocabulary. An
app declares *what it controls* — `index.flexion`, `wrist.rotation`, `hand.grasp` —
and a [`Target`][myogestic.controls.Target] renders those names in whatever a
specific application wants on its wire. The Virtual Hand, a keyboard, a cursor and a
prosthesis are all adapters; none of them gets to define the vocabulary.

Continuous DOFs are **signed and normalized**: the domain is `[-1, 1]`, `+1` is the
direction the name denotes, and rest is `0`. Discrete DOFs are separate on purpose —
a held state delivered on change is not the same thing as a number.

## Declaring a control space

`load_dofs` takes a plain mapping, so the library never reads a file itself: parse
your TOML (or JSON, or a dict literal) and hand it over.

```toml
[dofs]
"index.flexion" = "continuous"                                 # [-1, 1], rest 0
"hand.grasp"    = ["rest", "fist", "pinch"]                    # array => discrete
"grip.force"    = { kind = "continuous", range = [0.0, 1.0] }  # one-way
```

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
