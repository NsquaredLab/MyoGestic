# Build a renderer

A **renderer** is a separate application MyoGestic drives — a process of its own,
reached over gRPC and read from over LSL. A [target](add-a-target.md) is the opposite:
an in-process object a `ControlBus` calls directly, on the thread MyoGestic already owns.

## Which way the streams run

The names are written from MyoGestic's point of view, so they read backwards from
yours. `MyoGestic_Output` is MyoGestic's *output* — for your renderer it is the input,
the stream you read:

```
MyoGestic  --[ MyoGestic_Output ]------>  your renderer   (you read this)
MyoGestic  --[ MyoGestic_ControlPose ]->  your control hand, if you have one
```

Publishing a read-back of your own is optional; VHI does it (`VHI_Predict`,
`VHI_Control`) so a client can verify what actually rendered, which is how a sign error
gets caught. Nothing requires it.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | so a control map can resolve against you — the reply says which address sits on which channel |
| read your pose stream | N × `float32`, N being the width you declare — 9 for a VHI-shaped hand, standard values, positional: a channel *is* an address |
| report that stream's name in `stream_name` | **you name the stream, not the client.** MyoGestic reads the name off the capabilities its control map points at, and publishes under it — there is nothing to configure on the client side and nothing for the two of you to agree in advance. A capability naming a *different* stream is left to whichever target drives that one, which is how one map can drive two hands. Leave `stream_name` empty and there is no name to build an outlet from, so the application has to construct and hand over its own — supported, but it puts the name back in the client, which is the thing this contract exists to avoid |

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
