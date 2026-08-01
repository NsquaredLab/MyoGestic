# Build a renderer

A **renderer** is a separate application MyoGestic drives — a process of its own,
reached over gRPC and read from over LSL. A [target](add-a-target.md) is the opposite:
an in-process object a `ControlBus` calls directly, on the thread MyoGestic already owns.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | so a control map can resolve against you — the reply says which address sits on which channel |
| read your pose stream | N × `float32`, N being the width you declare — 9 for a VHI-shaped hand, standard values, positional: a channel *is* an address |
| report that stream's name in `stream_name` | a client resolves your manifest against one stream at a time, and it looks for the name it is configured to publish under — `MyoGestic_Output` by default, or `MyoGestic_ControlPose` for a control hand, both settable on its `InterfaceSpec`. A capability naming a *different* stream is left to whichever target drives that one. Leaving `stream_name` empty works too: it matches whatever the client is looking for |

| you may | for |
|---|---|
| serve `SetControl` | discrete DOFs — held states and gestures, which do not belong on a per-tick stream |
| serve `SweepControl` | letting a client sweep one DOF and read back the degrees it produced, as a direction check |
| serve `SetPresentation` | for a client asking you to smooth incoming poses |
| serve the four recording RPCs | driving a ground-truth hand through a capture session |

## The whole renderer

The reference renderer, complete — every method is the real one; nothing is elided. It
talks to the service defined in `myogestic/vhi/_proto/myogestic_vhi.proto`; generate
stubs from that file for any language other than Python:

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

## See also

- [Integrate the Virtual Hand](integrate-vhi.md) — how MyoGestic is pointed at a renderer: `InterfaceSpec`, the outlet, the control client
- [Drive your own device](add-a-target.md) — the in-process counterpart: a `Target` a `ControlBus` calls directly
