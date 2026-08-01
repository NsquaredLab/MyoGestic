# Build a renderer

A **renderer** is a separate application MyoGestic drives — a process of its own,
reached over gRPC and read from over LSL. A [target](add-a-target.md) is the opposite:
an in-process object a `ControlBus` calls directly, on the thread MyoGestic already owns.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | so a control map can resolve against you — the reply says which address sits on which channel |
| read your pose stream | 9 × `float32`, standard values, positional: a channel *is* an address |

| you may | for |
|---|---|
| serve `SetControl` | discrete DOFs — held states and gestures, which do not belong on a per-tick stream |
| serve `SweepControl` | letting a client sweep one DOF and read back the degrees it produced, as a direction check |
| serve `SetPresentation` | reporting whether you smooth incoming poses |
| serve the four recording RPCs | driving a ground-truth hand through a capture session |

## The whole renderer

The reference renderer, complete — every method is the real one; nothing is elided:

```python
--8<-- "examples/synthetic/reference_renderer.py"
```

## The standard

Values are `[-1, 1]`, `0` is rest, `+1` is the direction the DOF's name denotes. A fist
is `[1, -1, 1, 1, 1, 1, 0, 0, 0]` — five flexions and an *ad*ducted thumb, because that
is what a fist does with a thumb.

## The warning

A backwards sign survives every test you would think to write, because a renderer and
its own read-back agree whichever way they point. Check against something outside the
loop — a person looking at the device. This repo shipped that bug and its own contract
suite passed throughout.

## What changed

`Declare` no longer exists; the manifest is the contract, and a control hand is driven
by publishing to its stream rather than by asking permission.
