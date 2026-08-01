# Build a renderer

A **renderer** is a separate application MyoGestic drives — a process of its own,
reached over gRPC and read from over LSL. A [target](add-a-target.md) is the opposite:
an in-process object a `ControlBus` calls directly, on the thread MyoGestic already owns.

## Which way the streams run

MyoGestic writes, you read. **You name the streams** — your manifest is where every name
is decided, and MyoGestic publishes under whatever `stream_name` you report:

```
MyoGestic  --[ a stream you named ]-->  your renderer   (you read this)
```

*How many* streams is yours too, and both shapes are supported:

| shape | what it looks like | who does this |
|---|---|---|
| **one stream per DOF** | a 1-channel stream named after the address — `vhi.prediction.index` carries `vhi.prediction.index` on channel 0 | the Virtual Hand, and the reference renderer below. The simplest thing to write: no width to declare, no layout to agree, and a DOF applies the moment its sample arrives, so two processes can each own a finger |
| **one stream, many channels** | one wider stream carrying several addresses, each on the `channel` you gave it | a renderer that wants a whole pose to land in one sample, or one already built around a fixed frame |

Neither is deprecated and MyoGestic needs telling neither way round: it groups a control
map's addresses by the `stream_name` each capability reports and builds one target per
group — a shared stream gets one target, nine separate streams get nine. That is
[`vhi_targets`](../api/controls.md), and an application calls it identically either way.

Publishing a read-back of your own is optional; VHI does it (`VHI_Predict`,
`VHI_Control`, nine positional channels each whatever the inbound shape) so a client can
verify what actually rendered, which is how a sign error gets caught. Nothing requires
it.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | so a control map can resolve against you — the reply says which stream carries which address, and on which channel of it |
| read the streams you named | `float32`, standard values. One channel per stream is the simplest shape; several addresses on one stream, each at the `channel` you reported, works the same |
| report `stream_name` and `channel` on every continuous capability | **you name the streams, not the client.** MyoGestic reads the name off the capabilities its control map points at, and publishes under it — there is nothing to configure on the client side and nothing for the two of you to agree in advance. It also *groups* by that name, which is the whole of how the two shapes above are told apart. A capability naming a stream this map does not reach is left to whichever target drives that one, which is how one map can drive two hands. Leave `stream_name` empty and there is no name to build an outlet from, so the application has to construct and hand over its own — supported, but it puts the name back in the client, which is the thing this contract exists to avoid |

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

Values are `[-1, 1]`, `0` is rest, `+1` is the direction the DOF's name denotes. Across
the nine addresses of a VHI-shaped hand a fist is `[1, -1, 1, 1, 1, 1, 0, 0, 0]` — five
flexions and an *ad*ducted thumb, because that is what a fist does with a thumb. That is
a statement about the *addresses*: it reads the same whether those nine values travel as
one nine-channel sample or as nine one-channel ones.

## The warning

A backwards sign survives every test you would think to write, because a renderer and
its own read-back agree whichever way they point. Check against something outside the
loop — a person looking at the device. This repo shipped that bug and its own contract
suite passed throughout.

## What changed

`Declare` no longer exists; the manifest is the contract, and a control hand is driven
by publishing to its stream rather than by asking permission.

VHI moved from two nine-channel positional streams (`MyoGestic_Output`,
`MyoGestic_ControlPose`) to one stream per DOF. That was a renderer's choice, not a rule
— the wide shape is still supported — and the client end needed no change to follow it,
because nothing on that side ever wrote a stream name down.

## See also

- [Integrate the Virtual Hand](integrate-vhi.md) — how MyoGestic is pointed at a renderer: `InterfaceSpec`, the outlet, the control client
- [Drive your own device](add-a-target.md) — the in-process counterpart: a `Target` a `ControlBus` calls directly
