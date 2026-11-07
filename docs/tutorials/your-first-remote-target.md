---
title: "Your first remote target"
---
!!! danger "Choose an adapter"
    Most devices do not need this page. Use a remote target only for a device that is
    already a separate program reached over gRPC and LSL, such as a game, simulator or
    service in another language or on another machine.

    For devices you can import and call from Python, such as a serial prosthesis, motor
    controller, cursor or vendor library, follow
    [Drive your own device](../how-to/add-a-target.md). It uses three methods in one process
    with no remote wire. Its copyable example runs in a few seconds.

This builds a remote target in seven stages, each ending in something you run and watch. The
device is a two-axis rig with a gripper that closes and opens and a wrist that rotates.

Everything happens in a MyoGestic checkout, because the stages call `tools/` scripts by
relative path:

```bash
git clone https://github.com/NsquaredLab/MyoGestic && cd MyoGestic
uv sync --extra grpc          # `grpc` because a remote target speaks gRPC
```

Create five files in that directory. Three form the target and producer; two are test probes.

| file | side | what it is |
|---|---|---|
| `my_target.py` | yours | the target: the manifest, the inlets, the held state |
| `my-rig.toml` | shared | the map, pairing your model's output names with the rig's addresses |
| `drive.py` | MyoGestic's | the producer: a stand-in for your application, the thing that publishes |
| `probe.py` | throwaway | stage 1, asks the target what it exports |
| `wide.py` | throwaway | stage 4, publishes a deliberately wrong stream |

The three application files are listed at [the end of the page](#the-finished-files). From
stage 3 on, two of them run at once, in two terminals:

```bash
uv run --extra grpc python my_target.py        # terminal 1 — your target
uv run --extra grpc python drive.py            # terminal 2 — MyoGestic
```

MyoGestic writes and your target reads, so running only the target publishes nothing and
nothing moves.

### Making it your device

To drive your hardware, change only these three settings. Nothing else in the rig needs to change.

| | what | where |
|---|---|---|
| 1 | the addresses your device exports | `ADDRESSES`, and the right-hand side of `my-rig.toml` |
| 2 | the one line where a value becomes motion | in `_apply`, marked with a comment |
| 3 | the device's name, used to find its streams again after a restart | Use the same string for `target_name=` and `InterfaceSpec(name=…)`; see the stage 5 warning before changing it |

## First, the wiring

The MyoGestic side is two objects, and it is the same two for every remote target:

```python
from myogestic.remote import InterfaceSpec, RemoteTarget

#: Your endpoint and your outlet settings. `process=[]` because nothing launches this —
#: you start your own device. `output_hz` is how fast MyoGestic re-sends each value.
rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

target = RemoteTarget(client=rig.control_client(), interface=rig)
```

These two objects are the complete MyoGestic-side wiring. They do not change again.
`virtual_hand()` supplies the corresponding VHI settings and resolves its Godot path.
Do not use it for this rig, which has no Godot binary to launch.

Every stream this spec publishes carries the `source_id`
`myogestic:<name>:<address>`, which lets your target find the same stream again after a
restart. Keep `name=` stable as described in stage 5.

<a id="stage-1--serve-a-manifest-and-read-it-back"></a>

## Stage 1. Serve a manifest, and read it back

Implement `GetControlManifest`, the remote target's one discovery obligation. That method
alone lets a client learn the device controls. Add LSL in stage 4.

Save this as `my_target.py`:

```python
"""my_target.py — stage 1."""

from __future__ import annotations

import sys
import threading
from concurrent import futures

import grpc

from myogestic.remote._proto import remote_control_pb2 as pb2
from myogestic.remote._proto import remote_control_pb2_grpc as pb2_grpc

#: Your addresses, in your own namespace. The first segment namespaces the device, so
#: `rig.*` cannot collide with `vhi.*` or `keyboard.*` in one map. The address is also the
#: name of the LSL stream that carries it — there is no second name to keep in step.
ADDRESSES = ["rig.gripper.closure", "rig.wrist.pronation"]

#: The range every address here declares, and the value each rests at.
LO, HI, REST = -1.0, 1.0, 0.0


class Rig(pb2_grpc.RemoteControlServicer):
    """Two axes. Holds the last value it was sent, per address."""

    def __init__(self, port: int = 50051) -> None:
        self.pose = dict.fromkeys(ADDRESSES, REST)
        self._port = port
        self._server: grpc.Server | None = None

    def GetControlManifest(self, request, context):  # noqa: N802 - gRPC's spelling
        """What this rig exports. The only call a client must be able to make."""
        manifest = pb2.ControlManifest(target_name="rig", vocabulary_version="2")
        for address in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(address=address, kind=pb2.CONTINUOUS, lo=LO, hi=HI, rest=REST)
            )
        return manifest

    def serve(self) -> None:
        """Start the gRPC server."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_RemoteControlServicer_to_server(self, self._server)
        self._server.add_insecure_port(f"127.0.0.1:{self._port}")
        self._server.start()

    def stop(self) -> None:
        """Stop the gRPC server."""
        if self._server is not None:
            self._server.stop(grace=None)


class Antique(Rig):
    """The same rig, reporting the vocabulary MyoGestic no longer drives.

    Here so the refusal below is something you can *run*, not something you read about.
    Delete it once you have seen it once.
    """

    def GetControlManifest(self, request, context):  # noqa: N802
        """The manifest above, with its version walked back to 1."""
        manifest = super().GetControlManifest(request, context)
        manifest.vocabulary_version = "1"
        return manifest


if __name__ == "__main__":
    rig = Antique() if "--antique" in sys.argv else Rig()
    print(f"{type(rig).__name__} on 127.0.0.1:50051 — Ctrl-C to stop")
    rig.serve()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        rig.stop()
```

`vocabulary_version="2"` is the compatibility gate, and the negative below is what it catches.
`lo=-1.0, hi=1.0, rest=0.0` is the [signed convention](../concepts/controls.md#the-one-convention-a-device-may-not-redefine):
`+1` is the direction the address *name* denotes, so `rig.gripper.closure` at `+1` is
closed and `rig.wrist.pronation` at `+1` is pronated.

!!! tip "End each address in a word that has an opposite"
    `+1` means the direction the address name says, so the name has to say one.
    Use `closure` and `pronation` so stage 6 can check the sign against the name.
    `rig.gripper` names a part; `rig.wrist.rotation` names a motion with two directions.
    Neither specifies the `+1` direction, so the sign check has no expected answer and
    the next map author must guess. `closure` and `pronation` each have an opposite.

### Checkpoint

Start it, and leave it running:

```bash
uv run --extra grpc python my_target.py
```

In a second terminal, ask it what it exports, using the real client so
the answer you see is the one MyoGestic will get:

```python
"""probe.py"""

from myogestic.remote import InterfaceSpec

rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)
client = rig.control_client()
for cap in client.capabilities():
    print(f"{cap.address:20s} {cap.kind}  [{cap.lo:+.1f}, {cap.hi:+.1f}]  rest={cap.rest:+.1f}")
client.stop()
```

```
rig.gripper.closure  continuous  [-1.0, +1.0]  rest=+0.0
rig.wrist.pronation  continuous  [-1.0, +1.0]  rest=+0.0
```

!!! warning "Use a rig-specific probe"
    `tools/inspect_control.py` is a Virtual Hand walkthrough. It takes no arguments and loads
    `examples/controls/hand.toml`, requiring six `vhi.prediction.*` addresses and
    `vhi.control.gesture`. This two-address rig cannot satisfy that map. Running the tool
    against it produces an uncaught traceback from `resolve()`.

    ```
    ValueError: [dofs] 'fist': this target does not export 'vhi.prediction.thumb.flexion'.
        It exports: rig.gripper.closure, rig.wrist.pronation
    ```

    With a compatible manifest, that walkthrough builds LSL outlets and looks for
    `VHI_Predict`. Stage 2 uses `tools/inspect_control_map.py` to inspect your map by path.

<a id="the-negative-an-old-target-is-refused-by-name"></a>

### Reject an incompatible target

MyoGestic and the target are installed separately, so their versions can differ.
MyoGestic checks the target's vocabulary version. Vocabulary 1 expects a wide pose stream
that this client no longer publishes. Without rejection, the target would wait silently
and never move. The client publishes per-address streams and rejects that version. Stop the target and
start it with the wrong version.

```bash
uv run --extra grpc python my_target.py --antique
```

```
Antique on 127.0.0.1:50051 — Ctrl-C to stop
```

Run `probe.py` against it and `client.capabilities()` raises `ValueError`:

```
ValueError: rig speaks control vocabulary 1, and MyoGestic needs 2 or newer. Vocabulary 2 publishes one LSL stream per control, named for that control's own address and one channel wide; vocabulary 1 read a single wide pose stream that MyoGestic no longer sends. Paired with this client such a target would report no error and never move. Update rig.
```

The error is one string on one line; any wrapping is done by the terminal. It names your
target because advice to update VHI would name the wrong program. Read it through the
direct probe. From stage 3, `ControlLink` catches the exception and returns `None`,
hiding that direct error from the caller.

Restart without `--antique` before going on.

<a id="stage-2--write-the-control-map-and-see-a-bad-address-refused"></a>

## Stage 2. Write the control map, and see a bad address refused

The map pairs your model's output names with the addresses the rig declared. Left side yours,
right side the device's. Each line under `[dofs]` declares one DOF, one [degree of
freedom](../reference/glossary.md#dof).

```toml
# my-rig.toml
[dofs]
grip = "rig.gripper.closure"
twist = "rig.wrist.pronation"
```

### Checkpoint

`tools/inspect_control_map.py` takes a path. It calls only `capabilities()` and `resolve()`, so
it builds no target, publishes no stream and cannot move anything:

```bash
uv run --extra grpc python tools/inspect_control_map.py my-rig.toml
```

```
──────────────────────────────────────────────────────────────────────────────
Control map: my-rig.toml
──────────────────────────────────────────────────────────────────────────────

──────────────────────────────────────────────────────────────────────────────
Declared in the file
──────────────────────────────────────────────────────────────────────────────
  grip   ->  rig.gripper.closure
  twist  ->  rig.wrist.pronation

  2 alias(es), 2 distinct target control(s), 0 fanning out to more than one.
  The left column is yours. The right belongs to the target, which is also
  what decides whether an address takes a number or a held state — so the
  next section needs one running.

──────────────────────────────────────────────────────────────────────────────
Resolved against a live target
──────────────────────────────────────────────────────────────────────────────
  The target exports 2 controls.

  grip   NUMBER  [-1.0, +1.0]
           x1.0   -> rig.gripper.closure
  twist  NUMBER  [-1.0, +1.0]
           x1.0   -> rig.wrist.pronation

  Every kind, range and state above came from the target, not the file.

my-rig.toml is usable against this target.
```

It reaches your target at `127.0.0.1:50051`. With
nothing running, the second section reports that state and exits `0`, confirming only
structural validity. Exit `0` without a running target is not a successful binding check.

Change `rig.wrist.pronation` to `rig.wrist.pronate` and run it again. The
first section prints unchanged, and the second becomes:

```
  This map cannot be used against that target:

  [dofs] 'twist': this target does not export 'rig.wrist.pronate'. Did you mean: rig.wrist.pronation?
      It exports: rig.gripper.closure, rig.wrist.pronation

my-rig.toml was refused.
```

Exit status `1`. The refusal names the address, the near miss, and everything the rig exports,
and it goes to stderr, so it can appear above the stdout section it belongs to. `resolve()` rejects the whole map if any address is unknown. It never binds only the recognized entries. A dropped control is indistinguishable from one that works and holds still.

The "Did you mean" hint is the addresses sharing the longest dotted prefix with what you
wrote, so it is absent only when nothing matches even the namespace. Here is that refusal
with no target running at all, resolved against a manifest written by hand:

<!--docs:run-->
```python
from myogestic.controls import Capability, load_control_map, resolve

rig_manifest = [
    Capability("rig.gripper.closure", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability("rig.wrist.pronation", "continuous", lo=-1.0, hi=1.0, rest=0.0),
]

try:
    resolve(load_control_map({"dofs": {"twist": "rig.wrist.pronate"}}), rig_manifest)
except ValueError as exc:
    assert "Did you mean: rig.wrist.pronation" in str(exc)
    assert "It exports: rig.gripper.closure, rig.wrist.pronation" in str(exc)

# Nothing shares even the namespace, so there is no near miss to offer.
try:
    resolve(load_control_map({"dofs": {"twist": "arm.wrist.pronation"}}), rig_manifest)
except ValueError as exc:
    assert "Did you mean" not in str(exc)
```

<a id="stage-3--bind-the-map-with-controllink"></a>

## Stage 3. Bind the map with `ControlLink`

Fix the typo and create the third file for the MyoGestic producer. This script calls
`bus.push()` as your application would inside `@pipeline.predict`.

```python
"""drive.py — the MyoGestic side. Stage 3: just the handshake."""

import tomllib

from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import InterfaceSpec, RemoteTarget

rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

#: Held in a variable, not built inline. `link.stop()` deliberately leaves the client
#: alive so the link can be re-used, so this is the only reference that will ever be able
#: to shut its worker thread and gRPC channel down. See the end of stage 5.
client = rig.control_client()

with open("my-rig.toml", "rb") as handle:  # "rb" — tomllib requires binary
    control_map = load_control_map(tomllib.load(handle))

link = ControlLink(control_map, [RemoteTarget(client=client, interface=rig)], hz=32)
try:
    print(link.ensure())
finally:
    link.stop()
    client.stop()
```

### Checkpoint

With the target stopped, `ensure()` prints `None`. Start it and run again, and you get a
`ControlBus`:

```
<myogestic._controls_bus.ControlBus object at 0x10f5bcc10>
```

A bus means the manifest resolved and one LSL outlet per address exists. The target has
not read any sample yet because it has no inlet code until stage 4. A bus alone does not
prove a connected data path.

`link.ensure()` has three outcomes.

| situation | `link.ensure()` |
|---|---|
| target unreachable | `None` |
| target reachable, address wrong | raises `ValueError` |
| target too old | logs the refusal, returns `None` |

Rows one and three both return `None`. A permanently incompatible target looks the same
as one that has not started yet, so an application can retry forever.
Run `drive.py` against `my_target.py --antique` to see row three and a `logging.WARNING`
on the `myogestic.controls` logger.

```
RemoteTarget refused the handshake: rig speaks control vocabulary 1, and MyoGestic needs 2 or newer. …
```

That reaches stderr even with logging unconfigured, but in a GUI application stderr is a
terminal behind the window. Pass `ctx=` so it lands in the app's own log panel instead:

```python
link = ControlLink(control_map, [target], ctx=ctx, hz=32)
```

<a id="stage-4--read-the-streams"></a>

## Stage 4. Read the streams

MyoGestic publishes one single-channel LSL stream per address, named for that address.

Add imports and five fields to `my_target.py`. Add the seven methods below to the existing
`Rig` class. Do not start a second `class` statement. `_open`, `_apply`, `_read`, `_status` and `_watch` are additions; replace the
stage-1 `serve` and `stop` methods to manage the reader thread and gRPC server. See
[the finished file](#my_targetpy) for placement.

Add these imports.

```python
import time
from contextlib import suppress

from mne_lsl.lsl import StreamInlet, resolve_streams
```

Five more fields in `__init__`:

```python
        #: When each address last accepted a sample, for the liveness policy in stage 5.
        self._fresh = dict.fromkeys(ADDRESSES, 0.0)
        #: Addresses currently sending values this rig will not accept, so the complaint
        #: is printed once rather than per tick.
        self._refused: set[str] = set()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._inlets: dict[str, StreamInlet] = {}
```

Finding and opening the inlets:

```python
    def _open(self, missing: list[str]) -> None:
        """Open an inlet for each address exactly one one-channel outlet publishes.

        Resolved into a list per name, not a `{s.name: s}` dict: that dict silently keeps
        whichever producer the sweep happened to answer with last, so two applications
        both driving your gripper would look exactly like one, and which of them you were
        obeying would change between restarts.

        **This sees a duplicate only at the moment it opens the inlet.** `_read` drops an
        address from `missing` as soon as it has one, so nothing sweeps for that address
        again — a second producer that starts *afterwards* is never noticed: liblsl keeps
        feeding you the outlet your inlet already bound to, and the other one is simply
        not read. Closing that gap costs a resolve sweep on a timer whether or not
        anything is wrong, which is a real price on a multicast network. Decide it for
        your rig; this one takes the cheap half and says so.
        """
        found: dict[str, list] = {}
        for info in resolve_streams(timeout=1.0):
            found.setdefault(info.name, []).append(info)
        for address in missing:
            infos = found.get(address, [])
            if not infos:
                continue
            if len(infos) > 1:
                print(
                    f"rig: {address} is published by {len(infos)} outlets at once. "
                    f"One address, one producer — not opening any of them."
                )
                continue
            if infos[0].n_channels != 1:
                print(
                    f"rig: {address} is published {infos[0].n_channels} channels "
                    f"wide; this contract is one channel. Not opening it."
                )
                continue
            self._inlets[address] = StreamInlet(infos[0])
            self._inlets[address].open_stream()
```

Apply each sample to the device in this method. This is the only method where a value becomes motion.

```python
    def _apply(self, address: str, value: float) -> None:
        """Apply one sample, or refuse it.

        Width is checked when the inlet opens; this checks the *value*. A correctly
        shaped stream can still carry a NaN out of a divide, or a 12.0 out of a model
        nobody clipped — and a range you advertised is a promise you are also entitled
        to enforce. `not LO <= value <= HI` rejects a NaN too: every comparison with a
        NaN is False, so the negation catches it without a separate `isnan`.
        """
        if not LO <= value <= HI:
            if address not in self._refused:
                self._refused.add(address)
                print(
                    f"rig: {address} sent {value!r}, which is not a finite value in "
                    f"[{LO:+.1f}, {HI:+.1f}] — ignored (reported once)."
                )
            return
        self._refused.discard(address)
        self._fresh[address] = time.monotonic()
        # Call your actuator here instead of storing the value.
        self.pose[address] = value
```

The loop that drives them:

```python
def _read(self) -> None:
    """Read every stream and apply each value as it arrives.

    One thread, not one per stream: `resolve_streams` is a multicast sweep of the
    whole network, and one sweep already answers for every stream still missing an
    inlet.
    """
    while not self._stop.is_set():
        # Resolving is inside the `try` too: an outlet can vanish between the resolve
        # and the open. Outside it, that ordinary race kills this thread while the gRPC
        # server keeps answering the manifest — a client would bind successfully
        # against a target that never reads another sample.
        try:
            missing = [a for a in ADDRESSES if a not in self._inlets]
            if missing:
                self._open(missing)
            for address, inlet in self._inlets.items():
                chunk, _ = inlet.pull_chunk(timeout=0.0)
                if chunk is not None and len(chunk):
                    # One channel, so there is nothing to unpack: `chunk[-1][0]` is
                    # the whole sample.
                    self._apply(address, float(chunk[-1][0]))
            self._stop.wait(0.005)
        except Exception as exc:  # noqa: BLE001 - this thread must survive
            print(f"rig: lost an inlet ({type(exc).__name__}: {exc}), re-resolving")
            for inlet in self._inlets.values():
                with suppress(Exception):
                    inlet.close_stream()
            self._inlets.clear()
            self._stop.wait(1.0)  # `resolve_streams` can raise too — back off
```

Print status to check the rig. A rig with no visible state cannot be checked.

```python
def _status(self) -> str:
    """One line naming every address's current value."""
    axes = "  ".join(f"{a.removeprefix('rig.')}={self.pose[a]:+.2f}" for a in ADDRESSES)
    return f"rig: {axes}"


def _watch(self) -> None:
    """Print the driven state whenever it changes."""
    last = None
    while not self._stop.is_set():
        line = self._status()
        if line != last:
            last = line
            print(line)
        self._stop.wait(0.05)
```

Finally, `serve` starts both threads and `stop` shuts them down properly:

```python
def serve(self) -> None:
    """Start the gRPC server, the inlet reader and the status printer."""
    self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb2_grpc.add_RemoteControlServicer_to_server(self, self._server)
    self._server.add_insecure_port(f"127.0.0.1:{self._port}")
    self._server.start()
    for target in (self._read, self._watch):
        thread = threading.Thread(target=target, name=target.__name__, daemon=True)
        thread.start()
        self._threads.append(thread)


def stop(self) -> None:
    """Stop the threads, close every inlet, and stop the gRPC server.

    Setting the event is not shutting down. The threads are daemons, so the process
    will exit either way — but a `stop()` that only sets a flag leaves the reader
    mid-`pull_chunk` while the caller carries on, and every inlet still open. So join
    first, then close: closing an inlet is what stops liblsl trying to re-connect to a
    stream this rig has finished with.

    The join is **bounded, and that is a trade rather than a detail**. Two seconds is
    comfortably longer than a pass of `_read` — a one-second resolve sweep plus the
    back-off — so in practice the reader has ended by the time the loop below runs. It
    is a timeout and not a bare `join()` because a wedged liblsl call would otherwise
    hang shutdown forever. If it *does* expire, this closes inlets underneath a
    reader that is still using them, which is a race liblsl makes no promise about;
    the reader will not re-open anything (`_stop` is set, so that pass is its last)
    but that is the extent of the guarantee. A rig that cannot accept even that
    should `join()` without a timeout and accept a hung reader hanging shutdown
    instead. What you may *not* do is keep the timeout and describe it as a wait.
    """
    self._stop.set()
    for thread in self._threads:
        thread.join(timeout=2.0)
    self._threads.clear()
    for inlet in self._inlets.values():
        with suppress(Exception):
            inlet.close_stream()
    self._inlets.clear()
    if self._server is not None:
        self._server.stop(grace=None)
```

Reject streams where `n_channels != 1`. An inlet is found by address name, so a nine-channel
stream called `rig.gripper.closure` can reach that inlet. Reading element zero would use
another DOF's value, such as a thumb, to drive the gripper. Never read element zero of
a wrong-width stream. The resulting motion could look plausible and stay in range for
the whole session while following the wrong control. Rejecting the width makes this
failure visible.

### Checkpoint 1: routing, not motion

Add `import time` at the top of `drive.py`, and replace the bare `print(link.ensure())`
inside the `try:` with a loop that drives the two axes to opposite values. It stays
indented in the `try:`, so `link.stop()` and `client.stop()` still run whatever happens:

```python
    bus = link.ensure()
    print(bus)
    if bus is not None:
        for _ in range(80):
            bus.push({"grip": 1.0, "twist": -1.0})
            time.sleep(0.05)
```

The target prints:

```
rig: gripper.closure=+0.00  wrist.pronation=+0.00
rig: gripper.closure=+1.00  wrist.pronation=-1.00
```

The first line is `RemoteTarget`'s initial rest frame; the second is your loop.
Opposite values reveal crossed or duplicated streams. Sending `+1` on both axes would
hide those errors. `tests/test_reference_target.py`
drives its two DOFs to `1.0` and `-1.0` for that reason.

### Checkpoint 2: the wrong width, refused

Stop `drive.py` and the target, so nothing is publishing these addresses legitimately. Then
publish one of them at the wrong width, from a script that stays up. A producer that pushes
once and exits takes its outlet with it, and `LSLOutlet`'s sender is a daemon thread, so the
stream would be gone before the target's next one-second sweep could find it:

```python
"""wide.py — publish one of the rig's addresses at the wrong width."""

import threading

import numpy as np

from myogestic.outputs import LSLOutlet

wide = LSLOutlet(name="rig.gripper.closure", n_channels=9, hz=32)
wide.push(np.ones(9, dtype=np.float32))
print("publishing rig.gripper.closure 9 channels wide — Ctrl-C to stop")
try:
    threading.Event().wait()
except KeyboardInterrupt:
    wide.stop()
```

Start that first, then start the target:

```
rig: rig.gripper.closure is published 9 channels wide; this contract is one channel. Not opening it.
```

The refusal prints once per resolve sweep while the bad producer runs. The same
script with `n_channels=1`, one-element samples, and *two* outlets under one
name gets you the other refusal:

```
rig: rig.gripper.closure is published by 2 outlets at once. One address, one producer — not opening any of them.
```

As documented in `_open`, a second producer started after binding is not detected.
The rig keeps reading the first producer.

And a one-channel stream carrying a value the rig never agreed to accept gets the third:

```
rig: rig.wrist.pronation sent nan, which is not a finite value in [-1.0, +1.0] — ignored (reported once).
```

The three refusals identify the producer error.

<a id="stage-5--stopping-reconnecting-and-staying-alive"></a>

## Stage 5. Stopping, reconnecting, and staying alive

MyoGestic's outlets resend their last value at `output_hz`. This target holds the last
received value when samples stop. A stationary device can therefore indicate either
a healthy idle system or a stopped producer. Check shutdown delivery.

### Checkpoint 1: stop returns the device to rest

```python
link.stop()
```

```
rig: gripper.closure=+0.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
```

Read the last line to check rest delivery. Never use the number of printed lines as the check. You may see two lines because the axes are
independent streams whose rest samples arrive milliseconds apart. Each is applied on arrival.

Those lines are [`ControlBus.stop`][myogestic.controls.ControlBus.stop] delivering the neutral
frame *before* tearing the targets down, and `RemoteTarget` pushing and flushing each
stream's declared rest before it releases the outlet. The send loop is paced, so a
pushed-but-unflushed rest would sit unsent while the outlet went away.

### Checkpoint 2: it reconnects

Leave the target up, stop the producer, start a fresh one, and drive the axes the other way:

```
rig: gripper.closure=+1.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
rig: gripper.closure=-1.00  wrist.pronation=+1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
```

Check reconnection separately from initial binding. A target can work on its first inlet
and fail silently after a restart.

Liblsl inlet recovery matches a returning outlet by `source_id`. `_inlets` still holds
both addresses, so `missing` stays empty and `_read` does not resolve again.
`InterfaceSpec.stream_outlet` gives every stream a stable one,
`myogestic:<spec name>:<address>`.

!!! danger "Change `InterfaceSpec(name=…)` and reconnection stops, silently"
    The `source_id` is built from that name, so a producer that comes back under a different
    one is, to liblsl, a *different stream*. The inlet stays alive and recovering, waiting
    for the original `source_id`, which will never return. `pull_chunk` keeps yielding
    empty forever, `missing` stays empty, and no resolve sweep, exception or printed
    diagnostic occurs. Run under `name="rig"` and then
    `name="rig-renamed"` to reproduce the stalled connection.

    Pick one name per device and keep it.

The `except` around the loop is what keeps the reader alive through the ordinary race where an
outlet vanishes between the resolve and the open. Without it the thread dies while the gRPC
server continues to answer the manifest, so a client binds against a target that will never
read another sample.

### Checkpoint 3: what an *unclean* exit does, and what you choose to do about it

`link.stop()` is the orderly path. If the producer is killed with `SIGKILL`, loses its network,
or crashes, rest delivery, flushing and outlet teardown are skipped. Under a hold-last
policy the target then retains the last values it received.

Choose one of these three policies and document it.

| policy | what the rig does when samples stop | when |
|---|---|---|
| hold-last | keeps the last value forever | a display, a simulation, anything that cannot hurt anyone |
| timed rest | returns to `REST` after a declared timeout | a rig with force behind it, driven over a network |
| device deadman | the hardware itself releases without a heartbeat | anything that can injure someone |

The middle one is a *software deadman* and it is about six lines. Take a timestamp whenever a
sample is accepted, as `_apply` does in `self._fresh`, and add an optional timeout to
`__init__`:

```python
    def __init__(self, port: int = 50051, rest_after_s: float | None = None) -> None:
        ...
        #: The liveness policy. `None` is hold-last. A number is a software deadman: an
        #: axis whose newest accepted sample is older than this returns to `REST`.
        self._rest_after_s = rest_after_s
```

…and check it once per pass of `_read`, right after the `pull_chunk` loop:

```python
                if self._rest_after_s is not None:
                    stale = time.monotonic() - self._rest_after_s
                    for address in ADDRESSES:
                        if self._fresh[address] < stale:
                            self.pose[address] = REST
```

Replace the `rig = ...` line in `my_target.py`'s main block with the flag parser:

```python
    rest_after = None
    if "--rest-after" in sys.argv:
        rest_after = float(sys.argv[sys.argv.index("--rest-after") + 1])
    rig = Antique() if "--antique" in sys.argv else Rig(rest_after_s=rest_after)
```

Add `import os` to `drive.py` and print its Python PID before `link.ensure()`:

```python
    print(f"producer PID: {os.getpid()}", flush=True)
```

Restart the rig with the policy armed, then kill the producer mid-grip:

```bash
uv run --extra grpc python my_target.py --rest-after 1.0    # terminal 1
uv run --extra grpc python drive.py                          # terminal 2
kill -KILL <PID>                                              # terminal 3; use the printed Python PID
```

Unlike Ctrl-C, `SIGKILL` skips the producer's `finally` block. This tests the rig's timeout. It does not test orderly rest delivery. With both inlets connected,
the rig lets go about a second after the last accepted samples:

```
rig: gripper.closure=+1.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
```

Set the timeout well above your producer's tick interval. At `output_hz=32.0` a sample is due
every 31.25 ms, so one second is about 32 missed samples. A software deadman is not a safety
interlock. It performs a different job from stream recovery. See
[Design notes](../how-to/drive-a-remote-target.md#design-notes).

<a id="stage-6--the-sign-check"></a>

## Stage 6. The sign check

This stage requires your device and your eyes. It cannot be run here or replaced by
an automated check. The procedure below must be performed on the device; there is no
automated output to quote.

Command `grip = +1.0` and watch the gripper. It must close, because `closure` is what
the name `rig.gripper.closure` denotes at `+1`. Then `-1.0`, and it must open. Command
`twist = +1.0` and the wrist must pronate, because that is what `rig.wrist.pronation`
denotes at `+1`; `-1.0` supinates.

An inverted gripper can open on `+1` while its automated read-back checks pass.
The read-back reports the motion performed. This repository shipped that exact sign
bug while its automated suite stayed green. A person must make this checkpoint. See [Concepts ›
Controls](../concepts/controls.md#the-one-convention-a-device-may-not-redefine) for the sign rule.

Stage 1's directional names provide the expected sign. `rig.gripper` alone
would leave that direction unspecified.

If your rig is inverted, fix it *inside your target*. Flip the sign in `_apply`, where the
value becomes motion. Do not flip it in the map with a `weight = -1.0`, and do not advertise a
second address for the other direction. The declared range has both halves, and the
next person to write a map against your manifest will read the name and expect it to mean what
it says.

<a id="stage-7--discrete-state"></a>

## Stage 7. Discrete state

An amount and a held state are different things. Do not put a held state on a per-tick
stream. Send held states over gRPC only when they change. Re-sending "clamped" at 32 Hz
produces 32 commands a second. It does not create one held state. Add a mode to the manifest and implement `SetControl`.

Module level, next to `ADDRESSES`:

```python
MODES = ("rest", "active")

MODE_CAPABILITY = pb2.ControlCapability(
    address="rig.mode",
    kind=pb2.DISCRETE,
    states=MODES,
    rest_state=MODES[0],
    #: What a client driving this numerically should cross to select the non-rest state.
    #: Yours to declare, because you know what your states cost: a rig that takes a second
    #: to clamp wants a higher bar than a cursor click. `0` means "no opinion, use the
    #: client's own default".
    activation_threshold=0.6,
)
```

Add a field and method to the same `Rig` class.

```python
        #: Initialised to the state the manifest advertises as `rest_state`, so this rig
        #: is *in* the state it claims to be in before anybody commands anything. An
        #: uninitialised `self.mode` makes the status line fail on its first read, which
        #: is before the first command rather than after it.
        self.mode = MODES[0]
```

```python
    def SetControl(self, request, context):  # noqa: N802 - gRPC's spelling
        """Apply held states. The key is one of your addresses; the value is a state."""
        rejected = {}
        for address, state in request.discrete.items():
            #: Two lookups, not one: which control, then which of its states. Resolving
            #: on the state alone would make two discrete controls that share a state
            #: name indistinguishable, and would accept an address you never advertised.
            if address != MODE_CAPABILITY.address:
                rejected[address] = f"{address!r} is not a discrete control of this rig"
            elif state not in MODES:
                rejected[address] = f"{state!r} is not one of {list(MODES)}"
            else:
                self.mode = state
                #: Printed *here*, not left to the status poller. This handler runs once
                #: per command and in the order the commands arrived, so it is the only
                #: place a state change is certain to be seen. `_watch` samples every
                #: 50 ms and shows you whatever `self.mode` happens to be at the tick —
                #: a state replaced before the next tick leaves no trace at all.
                print(f"rig: mode -> {state}")
        return pb2.ControlAck(applied=not rejected, rejected=rejected)
```

Append the capability in `GetControlManifest`, after the continuous loop:

```python
        manifest.capabilities.append(MODE_CAPABILITY)
```

…and put the mode on the status line, so you can watch it the same way you watch the axes:

```python
        return f"rig: {axes}  mode={self.mode}"
```

Then add the alias to `my-rig.toml`. `debounce_s` is how long a state must hold before it
counts, a property of *your control loop* and not of the rig, so it lives in the map and not in
the manifest:

```toml
# my-rig.toml
[dofs]
grip = "rig.gripper.closure"
twist = "rig.wrist.pronation"
mode = { target = "rig.mode", debounce_s = 0.1 }
```

!!! warning "Restart both processes after changing the manifest or the map"
    [`ControlLink.ensure()`][myogestic.controls.ControlLink.ensure] returns its cached bus
    without a second handshake once it has one, and `RemoteTarget` caches what it resolved and
    has no detection of a changed manifest. Restarting your target is not enough; the
    running MyoGestic side retains the two-address contract.

    Call `link.stop()` and build a `ControlLink` from a freshly loaded map. `stop()` permits
    another handshake but retains the original `ControlMap`. Restart `drive.py` to reload
    the TOML and bind again.

Only the target declares `kind`. The map cannot say whether an address takes a number
or a held state. The same map works when you change a control from continuous
to discrete.

<!--docs:run-->
```python
from myogestic.controls import Capability, load_control_map, resolve

manifest = [
    Capability("rig.gripper.closure", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability(
        "rig.mode",
        "discrete",
        states=("rest", "active"),
        rest_state="rest",
        activation_threshold=0.6,
    ),
]
controls = resolve(
    load_control_map(
        {
            "dofs": {
                "grip": "rig.gripper.closure",
                "mode": {"target": "rig.mode", "debounce_s": 0.1},
            }
        }
    ),
    manifest,
)

mode = controls.dofs["mode"]
assert mode.states == ("rest", "active")  # the rig said so; the map never mentioned states
assert mode.rest == "rest"
assert mode.debounce_s == 0.1  # this one the map did say
```

### Checkpoint

Add this to `drive.py` inside the same `if bus is not None:` block, after the `for` loop.
Use eight spaces of indentation; four would place it outside the block.

```python
        print(bus.select("mode", "active"))
        time.sleep(0.5)
        print(bus.select("mode", "rest"))
        time.sleep(0.5)
        print(bus.select("mode", "banana"))
```

```
True
True
False
```

and, with successful RPC delivery, the target normally prints these four
command lines in this order, alongside its status lines.

```
rig: mode -> rest
rig: mode -> active
rig: mode -> rest
rig: mode -> rest
```

The middle two are your `select` calls. The first comes from the push loop. `mode` is absent from what
you push, so it settles on its declared rest and is delivered once, as an edge. The last is
`link.stop()` delivering the neutral frame.

`select()` returns `True` for a valid state after handing the frame to the target. For
`RemoteTarget`, the gRPC command is queued on its client and sent on a worker
thread. Whether the rig *applied* it is a fact on the target's side, which is why the target prints
what it applied. The bus rejects `banana` locally because it is absent from your declared states.
Delivery timing is not guaranteed. See
[Design notes](../how-to/drive-a-remote-target.md#design-notes).

!!! note "Match `request.discrete` keys to addresses"
    Match keys against advertised addresses, such as `rig.mode`, and reject unknown keys.
    `continuous` and stream names also use addresses. Aliases such as `mode` belong to
    the client's map. The target has never seen those invented names and cannot interpret
    them. Address keys distinguish controls even if two share a `hold` state; only the
    address identifies which control a shared state belongs to.

## The finished files

The files below assemble everything from the stages. Copy them as a starting point or
compare them with your stage-by-stage version.

### `my_target.py`

```python
"""my_target.py — a two-axis rig with a held mode."""

from __future__ import annotations

import sys
import threading
import time
from concurrent import futures
from contextlib import suppress

import grpc
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.remote._proto import remote_control_pb2 as pb2
from myogestic.remote._proto import remote_control_pb2_grpc as pb2_grpc

#: Your addresses. Each name states the direction `+1` moves in.
ADDRESSES = ["rig.gripper.closure", "rig.wrist.pronation"]

#: The range every address here declares, and the value each rests at.
LO, HI, REST = -1.0, 1.0, 0.0

#: The held states of `rig.mode`, rest first.
MODES = ("rest", "active")

MODE_CAPABILITY = pb2.ControlCapability(
    address="rig.mode",
    kind=pb2.DISCRETE,
    states=MODES,
    rest_state=MODES[0],
    activation_threshold=0.6,
)


class Rig(pb2_grpc.RemoteControlServicer):
    """Two axes and a mode. Holds the last value it was sent, per address.

    Parameters
    ----------
    port
        The port to serve `GetControlManifest` and `SetControl` on.
    rest_after_s
        The liveness policy. ``None`` is hold-last: an axis keeps its last value for
        ever. A number is a software deadman — an axis whose newest accepted sample is
        older than this returns to ``REST``. Neither replaces a hardware interlock.
    """

    def __init__(self, port: int = 50051, rest_after_s: float | None = None) -> None:
        self.pose = dict.fromkeys(ADDRESSES, REST)
        self.mode = MODES[0]
        self._port = port
        self._rest_after_s = rest_after_s
        self._fresh = dict.fromkeys(ADDRESSES, 0.0)
        self._refused: set[str] = set()
        self._server: grpc.Server | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._inlets: dict[str, StreamInlet] = {}

    # --- the manifest ---------------------------------------------------------

    def GetControlManifest(self, request, context):  # noqa: N802 - gRPC's spelling
        """What this rig exports. The only call a client must be able to make."""
        manifest = pb2.ControlManifest(target_name="rig", vocabulary_version="2")
        for address in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(address=address, kind=pb2.CONTINUOUS, lo=LO, hi=HI, rest=REST)
            )
        manifest.capabilities.append(MODE_CAPABILITY)
        return manifest

    # --- held state -----------------------------------------------------------

    def SetControl(self, request, context):  # noqa: N802 - gRPC's spelling
        """Apply held states. The key is one of your addresses; the value is a state.

        Per entry, so a mixed request applies its good entries and still answers
        ``applied=False``. Validate into a local dict first if your device cannot
        tolerate that.

        Prints each accepted state itself: this handler runs once per command, so it
        is the only observation of a state change that cannot be missed. `_watch`
        polls, and a state replaced between two polls never appears.
        """
        rejected = {}
        for address, state in request.discrete.items():
            if address != MODE_CAPABILITY.address:
                rejected[address] = f"{address!r} is not a discrete control of this rig"
            elif state not in MODES:
                rejected[address] = f"{state!r} is not one of {list(MODES)}"
            else:
                self.mode = state
                print(f"rig: mode -> {state}")
        return pb2.ControlAck(applied=not rejected, rejected=rejected)

    # --- lifecycle ------------------------------------------------------------

    def serve(self) -> None:
        """Start the gRPC server, the inlet reader and the status printer."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_RemoteControlServicer_to_server(self, self._server)
        self._server.add_insecure_port(f"127.0.0.1:{self._port}")
        self._server.start()
        for target in (self._read, self._watch):
            thread = threading.Thread(target=target, name=target.__name__, daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        """Stop the threads, close every inlet, and stop the gRPC server.

        The join is bounded so a wedged liblsl call cannot hang shutdown forever. If
        the timeout expires the inlets are closed under a still-running reader; drop
        the timeout if your rig cannot accept that.
        """
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        self._threads.clear()
        for inlet in self._inlets.values():
            with suppress(Exception):
                inlet.close_stream()
        self._inlets.clear()
        if self._server is not None:
            self._server.stop(grace=None)

    # --- reading --------------------------------------------------------------

    def _open(self, missing: list[str]) -> None:
        """Open an inlet for each address exactly one one-channel outlet publishes."""
        found: dict[str, list] = {}
        for info in resolve_streams(timeout=1.0):
            found.setdefault(info.name, []).append(info)
        for address in missing:
            infos = found.get(address, [])
            if not infos:
                continue
            if len(infos) > 1:
                print(
                    f"rig: {address} is published by {len(infos)} outlets at once. "
                    f"One address, one producer — not opening any of them."
                )
                continue
            if infos[0].n_channels != 1:
                print(
                    f"rig: {address} is published {infos[0].n_channels} channels "
                    f"wide; this contract is one channel. Not opening it."
                )
                continue
            self._inlets[address] = StreamInlet(infos[0])
            self._inlets[address].open_stream()

    def _apply(self, address: str, value: float) -> None:
        """Apply one sample, or refuse it. THIS is where a value becomes motion."""
        if not LO <= value <= HI:  # a NaN fails this comparison too
            if address not in self._refused:
                self._refused.add(address)
                print(
                    f"rig: {address} sent {value!r}, which is not a finite value in "
                    f"[{LO:+.1f}, {HI:+.1f}] — ignored (reported once)."
                )
            return
        self._refused.discard(address)
        self._fresh[address] = time.monotonic()
        # Call your actuator here instead of storing the value.
        self.pose[address] = value

    def _read(self) -> None:
        """Read every stream and apply each value as it arrives."""
        while not self._stop.is_set():
            try:
                missing = [a for a in ADDRESSES if a not in self._inlets]
                if missing:
                    self._open(missing)
                for address, inlet in self._inlets.items():
                    chunk, _ = inlet.pull_chunk(timeout=0.0)
                    if chunk is not None and len(chunk):
                        self._apply(address, float(chunk[-1][0]))
                if self._rest_after_s is not None:
                    stale = time.monotonic() - self._rest_after_s
                    for address in ADDRESSES:
                        if self._fresh[address] < stale:
                            self.pose[address] = REST
                self._stop.wait(0.005)
            except Exception as exc:  # noqa: BLE001 - this thread must survive
                print(f"rig: lost an inlet ({type(exc).__name__}: {exc}), re-resolving")
                for inlet in self._inlets.values():
                    with suppress(Exception):
                        inlet.close_stream()
                self._inlets.clear()
                self._stop.wait(1.0)  # `resolve_streams` can raise too — back off

    # --- showing what happened ------------------------------------------------

    def _status(self) -> str:
        """One line naming every address's current value and the held state."""
        axes = "  ".join(f"{a.removeprefix('rig.')}={self.pose[a]:+.2f}" for a in ADDRESSES)
        return f"rig: {axes}  mode={self.mode}"

    def _watch(self) -> None:
        """Print the driven state whenever it changes."""
        last = None
        while not self._stop.is_set():
            line = self._status()
            if line != last:
                last = line
                print(line)
            self._stop.wait(0.05)


class Antique(Rig):
    """The same rig, reporting the vocabulary MyoGestic no longer drives."""

    def GetControlManifest(self, request, context):  # noqa: N802
        """The manifest above, with its version walked back to 1."""
        manifest = super().GetControlManifest(request, context)
        manifest.vocabulary_version = "1"
        return manifest


if __name__ == "__main__":
    # `--rest-after 1.0` arms the liveness policy in stage 5; without it the rig holds its
    # last commanded value for ever, which is the default and the other valid choice.
    rest_after = None
    if "--rest-after" in sys.argv:
        rest_after = float(sys.argv[sys.argv.index("--rest-after") + 1])
    rig = Antique() if "--antique" in sys.argv else Rig(rest_after_s=rest_after)
    print(f"{type(rig).__name__} on 127.0.0.1:50051 — Ctrl-C to stop")
    rig.serve()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        rig.stop()
```

### `my-rig.toml`

```toml
# my-rig.toml
[dofs]
grip = "rig.gripper.closure"
twist = "rig.wrist.pronation"
mode = { target = "rig.mode", debounce_s = 0.1 }
```

### `drive.py`

In your own application the `push` loop is `@pipeline.predict` and the `select` calls are
button handlers. The wiring above them is the same.

```python
"""drive.py — the MyoGestic side."""

import os
import time
import tomllib

from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import InterfaceSpec, RemoteTarget

rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

#: Held, not built inline: `link.stop()` deliberately leaves the client alive so the link
#: can be re-used, so this is the only reference that can ever shut its worker thread and
#: gRPC channel down.
client = rig.control_client()

with open("my-rig.toml", "rb") as handle:  # "rb" — tomllib requires binary
    control_map = load_control_map(tomllib.load(handle))

link = ControlLink(control_map, [RemoteTarget(client=client, interface=rig)], hz=32)

try:
    print(f"producer PID: {os.getpid()}", flush=True)
    bus = link.ensure()
    print(bus)
    if bus is not None:
        for _ in range(80):
            bus.push({"grip": 1.0, "twist": -1.0})
            time.sleep(0.05)

        print(bus.select("mode", "active"))
        time.sleep(0.5)
        print(bus.select("mode", "rest"))
        time.sleep(0.5)
        print(bus.select("mode", "banana"))
finally:
    link.stop()
    client.stop()
```

## What you have

The tutorial covers the contract and four operational checks that a client cannot perform
for the target.

[`examples/synthetic/reference_target.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/reference_target.py)
is a shorter reference with six addresses, no discrete controls, hold-last and a minimal
inlet reader. Compare its omissions with the operational checks above and their failure costs.

## See also

- [Drive a remote target](../how-to/drive-a-remote-target.md) - the contract as a table, and the
  reference implementation in full
- [Concepts › Controls](../concepts/controls.md) - aliases, addresses, and the signed
  convention
- [Drive your own device](../how-to/add-a-target.md) - the in-process route, if you do not
  need a wire between two processes
- `myogestic/remote/_proto/remote_control.proto` - the wire contract; generate stubs from it for
  any language other than Python
