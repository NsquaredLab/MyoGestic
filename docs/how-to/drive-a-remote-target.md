---
title: "Drive a remote target"
---
A remote target runs as a separate application, reached over gRPC and driven
over LSL. For a device in the MyoGestic process, use an
[in-process target](add-a-target.md) that `ControlBus` calls directly.

If you have not chosen between the two yet, [Concepts › Controls](../concepts/controls.md)
explains how to choose. For a tutorial with runnable stages, see
[Your first remote target](../tutorials/your-first-remote-target.md).

## Stream direction

MyoGestic writes, you read. One stream per continuous DOF (one [degree of
freedom](../reference/glossary.md#dof)), named for the DOF's own address and one channel wide:

```
MyoGestic  --[ vhi.prediction.index, 1 channel ]-->  your target     (you read this)
```

Use the manifest address as the stream name. Each stream has one channel.
A DOF applies each sample on arrival and holds its last command between samples.
These DOFs are independently actuated, possibly driven by different processes at different
rates. Two programs can each drive a different DOF.

MyoGestic drives all of it with one [`RemoteTarget`](../api/controls.md), which publishes one
outlet per continuous address the map names and sends discrete changes over gRPC.

Publishing a read-back of your own is optional; VHI does it (`VHI_Predict` and `VHI_Control`,
nine positional channels each, whatever the inbound shape) so a client can verify movement
and catch a sign error.

## The contract

| you must | why |
|---|---|
| serve `GetControlManifest` | lets a control map resolve each address against its kind, range and states |
| report `vocabulary_version` `"2"` or newer | MyoGestic refuses an older target by name at bind. The applications are installed separately; a mismatch can leave a target waiting silently for an unpublished stream |
| advertise one address per control | the address identifies the control and names its stream. Multiple spellings prevent collision checks from recognizing aliases for the same control |
| read one stream per address, exactly one `float32` channel wide | validate the width and dtype. Reading element zero of a nine-channel pose can silently apply another DOF's value to the address named by the stream |

| you may | for |
|---|---|
| serve `SetControl` | held states and gestures. Both maps use manifest addresses as keys. Resolve the control from the key and the state from the value; refuse unexported addresses. Two discrete controls can share a state name |
| serve `SweepControl` | letting a client sweep one DOF and read back the degrees it produced, as a direction check |
| serve `SetPresentation` | for a client asking you to smooth incoming poses |
| serve the four recording RPCs | driving a ground-truth hand through a capture session |
| report `target_version` in the manifest | your build's release version (`"2.1.0"`). A client can refuse a build with known behaviour faults even when `vocabulary_version` matches. An absent version produces a warning and is accepted because the target may omit versioning |

Implement these runtime checks and policies in the target; the client cannot verify them.

| every remote target | why |
|---|---|
| validate sample values | a correctly shaped stream can carry NaN or `12.0`. Enforce the advertised range before moving the device |
| refuse an address published by more than one outlet | resolving into `{info.name: info}` keeps whichever producer the sweep answered with last, so two applications driving one DOF look exactly like one, and which you obey changes between restarts |
| state a liveness policy | choose hold-last, timed return to rest or a hardware deadman. A `SIGKILL`ed producer sends no neutral frame; a quiet stream may be idle or dead. `source_id` recovery handles reconnection. Device behaviour while disconnected needs its own policy and an independent safety interlock |
| close inlets and join reader threads on shutdown | setting an event alone leaves the reader in `pull_chunk` and the inlets open and reconnecting |

The reference target below demonstrates transport only. It accepts any correctly shaped
sample, uses `{info.name: info}` without duplicate detection and holds the last command.
`stop()` sets a flag without joining the reader or closing inlets.
For deployment, build all four runtime checks and policies using
[Your first remote target](../tutorials/your-first-remote-target.md), which also
documents the limit of its duplicate check.

## Client calls

[`RemoteTarget`][myogestic.remote.RemoteTarget] drives the
wire through two clients, `RemoteClient` and `RecordingClient`. Both are built from the
[`InterfaceSpec`][myogestic.remote.InterfaceSpec] that says where your target listens, and both
are reached as `spec.control_client()` and `spec.recording_client()`. Calls return
`None` or `False` while the target is unavailable, allowing the app to stay responsive
during launch.

| the client calls | when, and what it needs back |
|---|---|
| `control_client().capabilities()` | at bind, and on every retry until you answer. Your manifest is the whole reply. `None` means "not up yet" and is deferred, never failed |
| `control_client().set_control(...)` | on a discrete edge from the predict thread. Queued with latest-wins delivery; it never blocks or raises, keeping a 60 fps loop responsive. `rejected` reasons are logged |
| `control_client().sweep(name)` | on an explicit verification request from a person or test. It animates one DOF and reads back the degrees produced |
| `control_client().set_presentation(blend=…)` | when a client requests display smoothing. Keep the commanded values unchanged |
| `recording.set_recording_session(True/False)` | around a capture, to gate any local input of your own so the recording has one movement source |
| `recording.start_trajectory(movement, frequency_hz=…)` | to sweep a ground-truth control through a range while training data is collected |
| `recording.state()` | to show a client which movements you have, which one is current, and whether a trajectory is running |

Calls other than `set_control` are synchronous because setup, teardown and verification
need a reply. `set_control` is queued to meet the predict thread's deadline.

## The whole target

The reference target implements the service in
`myogestic/remote/_proto/remote_control.proto`. Generate stubs from that file
for languages other than Python:

```python
--8 < --"examples/synthetic/reference_target.py"
```

## The standard

Values are `[-1, 1]`, `0` is rest, `+1` is the direction the DOF's name denotes. Across the
nine addresses of a VHI-shaped hand, a fist is `[1, -1, 1, 1, 1, 1, 0, 0, 0]`,
with five flexions and an adducted thumb. These values apply to the addresses
whether sent as one nine-channel sample or nine one-channel samples.

## The warning

Watch the device to verify direction. Contract tests can pass despite a sign error;
[the one convention a device may not redefine](../concepts/controls.md#the-one-convention-a-device-may-not-redefine)
explains why.

## Design notes

A liveness timeout is not a safety interlock. A target that has itself crashed, hung or
been swapped out cannot time anything out. Anything that can injure a person needs a release
the software is not in the path of.

Stream recovery and the liveness timeout are different jobs. Recovery decides whether the
*stream* comes back; the timeout decides what the *device* does meanwhile. A rig can want both.

`SetControl` delivery timing is not guaranteed. `set_control` queues a frame for the
client's worker thread, which drains one blocking RPC at a time with a two-second deadline. A
later state can be queued before an earlier one is delivered, and two can land inside one tick
of a status poller. Verify discrete state with a handler that prints each applied state; a poller can miss changes.

## See also

- [Control standard](../api/controls.md) - the other side of this contract: the map, `RemoteTarget`, and what it refuses
- [Integrate the Virtual Hand](integrate-vhi.md) - one remote target that serves it, and how MyoGestic is pointed at that one
- [Drive your own device](add-a-target.md) - the in-process counterpart: a `Target` a `ControlBus` calls directly
