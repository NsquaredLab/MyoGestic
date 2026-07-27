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

## Encoding helpers

Wire-level helpers, for a target that needs a vector rather than a mapping.

::: myogestic.controls.encode

::: myogestic.controls.decode

::: myogestic.controls.clip

::: myogestic.controls.substitute_rest
