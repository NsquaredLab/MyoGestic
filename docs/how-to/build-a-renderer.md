# Build a renderer

A **renderer** is a separate application MyoGestic drives — a process of its own,
reached over gRPC and driven over LSL. A [target](add-a-target.md) is the opposite:
an in-process object a `ControlBus` calls directly, on the thread MyoGestic already owns.

If you have not chosen between the two yet, [Concepts › Controls](../concepts/controls.md)
explains the control system and which route fits what you are building. This page is the
contract; if you would rather arrive at it a stage at a time, with something to run and watch
at each one, start from [Integrate your own
interface](../tutorials/integrate-your-interface.md) instead.

## Which way the streams run

MyoGestic writes, you read. **One stream per DOF** — one [degree of
freedom](../reference/glossary.md#dof) — named for the DOF's own address and one channel
wide:

```
MyoGestic  --[ vhi.prediction.index, 1 channel ]-->  your renderer   (you read this)
```

There is one shape and it needs no describing. The address you advertise in your manifest
*is* the stream name, so nothing further is published about the transport: there is no
width to declare and no positional layout for the two of you to agree on. A DOF applies
the moment its sample arrives, and the DOFs that did not deliver hold whatever they were
last commanded to — which is what these DOFs actually are: independently actuated,
possibly driven by different processes at different rates. Two programs can each own a
finger.

MyoGestic drives all of it with one [`RendererTarget`](../api/controls.md), which publishes one
outlet per address the map names.

Publishing a read-back of your own is optional; VHI does it (`VHI_Predict` and
`VHI_Control`, nine positional channels each, whatever the inbound shape) so a client can
verify what actually rendered, which is how a sign error gets caught. Nothing requires
it.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | so a control map can resolve against you — the reply is the whole contract: every address, its kind, its range, its states |
| report `vocabulary_version` `"2"` or newer | the compatibility gate. MyoGestic refuses an older renderer **by name at bind**, because these are separately installed applications and a mismatch is otherwise silent: a renderer waiting for a stream nobody publishes reports nothing at all, and the hand just never moves |
| advertise **one address per control** | the address is the control's identity *and* its stream name. Two spellings of one control is a second vocabulary to keep in step by hand, and it makes "these two aliases collide" undecidable from the manifest |
| read one stream per address, exactly one `float32` channel wide | that is the contract, so **refuse anything else** rather than reading element zero of it. An inlet is found by its address's stream name, so a nine-channel whole-pose outlet from an out-of-date client corrupts only the one DOF it is named for — quietly, because element zero of somebody's pose frame is a *different* DOF's value, plausible and in range and wrong |

| you may | for |
|---|---|
| serve `SetControl` | discrete DOFs — held states and gestures, which do not belong on a per-tick stream. Both maps are keyed by **address**, exactly as the manifest publishes them and as your streams are named: resolve the *control* from the key and the *state* from the value, and refuse an address you do not export. Resolving on the state alone would leave two discrete controls that share a state name indistinguishable |
| serve `SweepControl` | letting a client sweep one DOF and read back the degrees it produced, as a direction check |
| serve `SetPresentation` | for a client asking you to smooth incoming poses |
| serve the four recording RPCs | driving a ground-truth hand through a capture session |

Nothing above is about *running* the thing. The table below is what turns a process that
satisfies the wire into an application you can leave up, and it is a separate table only
because a client cannot check any of it — not because it is optional or because it waits
for hardware. Closing inlets and joining reader threads is lifecycle hygiene for every
renderer there is; refusing a duplicate producer and refusing a non-finite or out-of-range
sample is what makes your input deterministic, which a simulation wants as much as a
gripper does; and every renderer already *has* a liveness policy — the only question is
whether anyone wrote it down.

| every renderer | why |
|---|---|
| check the sample, not just the width | a correctly shaped stream still carries a NaN out of a divide or a `12.0` out of an unclipped model. The range you advertised is a promise you are entitled to enforce before anything moves |
| refuse an address published by more than one outlet | resolving into `{info.name: info}` keeps whichever producer the sweep answered with last, so two applications driving one DOF look exactly like one, and which you obey changes between restarts |
| state a liveness policy | hold-last, a timed return to rest, or a hardware deadman. A `SIGKILL`ed producer sends no neutral frame, and *nothing* about a stream going quiet distinguishes an idle system from a dead one. `source_id` recovery is a separate concern: it decides whether the stream comes back, not what the device does meanwhile — and neither replaces an interlock the software is not in the path of |
| close inlets and join reader threads on shutdown | setting an event is not shutting down: it leaves the reader mid-`pull_chunk` while the caller carries on, and every inlet still open and re-connecting |

**The reference renderer below meets none of them, and that is deliberate.** It is a wire
example — the least code that shows the transport — so it renders any sample that is the
right shape, keeps `{info.name: info}` and cannot see a duplicate producer, is hold-last by
omission rather than by decision, and `stop()`s by setting a flag without joining its reader
or closing an inlet. Read it for the contract; do not deploy it as a template.
[Integrate your own interface](../tutorials/integrate-your-interface.md) builds one that
meets all four instead, one stage at a time — and marks the one place its duplicate check
stops looking.

## What calls it

You write none of the client side. [`RendererTarget`][myogestic.renderer.RendererTarget]
drives the wire through two clients — `RendererClient` and `RecordingClient` — both built
from the [`InterfaceSpec`][myogestic.renderer.InterfaceSpec] that says where your renderer
listens, and both reached as `spec.control_client()` and `spec.recording_client()`. Absence
is **reported rather than raised**: every call answers `None` or `False` while you are not
up, so an application that launches its renderer from its own button stays responsive
while it starts.

| the client calls | when, and what it needs back |
|---|---|
| `control_client().capabilities()` | at bind, and on every retry until you answer. Your manifest is the whole reply. `None` means "not up yet" and is deferred, never failed |
| `control_client().set_control(...)` | on a discrete edge, from the predict thread. **Queued and latest-wins** — it never blocks and never raises, so a slow handler of yours cannot stall a 60 fps loop, and your `rejected` reasons reach a log rather than a caller |
| `control_client().sweep(name)` | never automatically. Verification only, by a human or a test: it animates one DOF and reads back the degrees your rig produced |
| `control_client().set_presentation(blend=…)` | when a client asks you to smooth what you render. Appearance only — it must not change what was commanded |
| `recording.set_recording_session(True/False)` | around a capture, to gate any local input of your own so the recording has one movement source |
| `recording.start_trajectory(movement, frequency_hz=…)` | to sweep a ground-truth control through a range while training data is collected |
| `recording.state()` | to show a client which movements you have, which is current, and whether a trajectory is running |

Everything except `set_control` is **synchronous** — setup, teardown and verification, where
the caller cannot go on without your answer. Only the per-edge call is queued, and only
because it is the one on a deadline.

## The whole renderer

The reference renderer, complete — every method is the real one; nothing is elided. It
talks to the service defined in `myogestic/renderer/_proto/renderer_control.proto`; generate
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
`MyoGestic_ControlPose`) to one stream per DOF, and that is now the contract rather than
one renderer's choice. The proto's `stream_name` (field 10) and `channel` (field 11)
are **gone** — both numbers and both names are reserved in the proto — because with the
address naming the stream they could only repeat it. A renderer serving them is a
vocabulary-1 renderer and is refused by version.

An application no longer picks its targets either: `vhi_targets()` existed to build one
target per stream a map spanned, and one target now drives the whole map. It is
`[RendererTarget(client=…, interface=spec)]`, and it is named for what it drives — a
renderer — rather than for the first renderer that shipped.

## See also

- [Control standard](../api/controls.md) — the other side of this contract: the map, `RendererTarget`, and what it refuses
- [Integrate the Virtual Hand](integrate-vhi.md) — one renderer that serves it, and how MyoGestic is pointed at that one
- [Drive your own device](add-a-target.md) — the in-process counterpart: a `Target` a `ControlBus` calls directly
