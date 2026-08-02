# Your first remote target

!!! danger "Most devices do not need this page"
    This builds a **separate program** that MyoGestic reaches over gRPC and LSL. You need it
    only if your device already is its own program — a game, a simulator, something in another
    language, something on another machine.

    **If you can `import` your device and call it from Python** — a prosthesis on a serial
    port, a motor controller, a cursor, a vendor library — you want
    **[Drive your own device](../how-to/add-a-target.md)** instead: three methods, one
    process, no wire, and a copyable example that runs in a few seconds.

This builds a remote target in seven stages, each ending in something you run and watch. The
device is a two-axis rig: a gripper that closes and opens, and a wrist that rotates.

**Everything happens in a MyoGestic checkout**, because the stages call `tools/` scripts by
relative path:

```bash
git clone https://github.com/NsquaredLab/MyoGestic && cd MyoGestic
uv sync --extra grpc          # `grpc` because a remote target speaks gRPC
```

Create your files in that directory. You will write **five**, of which three are the result and
two are throwaway probes:

| file | side | what it is |
|---|---|---|
| `my_target.py` | yours | the target: the manifest, the inlets, the held state |
| `my-rig.toml` | shared | the map, pairing your model's output names with the rig's addresses |
| `drive.py` | MyoGestic's | the producer: a stand-in for your application, the thing that publishes |
| `probe.py` | throwaway | stage 1, asks the target what it exports |
| `wide.py` | throwaway | stage 4, publishes a deliberately wrong stream |

The three that matter are listed in full at [the end of the page](#the-finished-files). From
stage 3 on, two of them run at once, in two terminals:

```bash
uv run --extra grpc python my_target.py        # terminal 1 — your target
uv run --extra grpc python drive.py            # terminal 2 — MyoGestic
```

MyoGestic writes and your target reads, so running only the target publishes nothing and
nothing moves.

### Making it your device

The rig is a stand-in. To drive your own hardware you change these, and nothing else:

| | what | where |
|---|---|---|
| **1** | the addresses your device exports | `ADDRESSES`, and the right-hand side of `my-rig.toml` |
| **2** | **the one line where a value becomes motion** | in `_apply`, marked with a comment |
| **3** | the device's name, used to find its streams again after a restart | `target_name=` and `InterfaceSpec(name=…)` — the *same* string in both, and see the warning in stage 5 before you change it |

## First, the wiring

The MyoGestic side is two objects, and it is the same two for every remote target:

```python
from myogestic.remote import InterfaceSpec, RemoteTarget

#: Your endpoint and your outlet settings. `process=[]` because nothing launches this —
#: you start your own device. `output_hz` is how fast MyoGestic re-sends each value.
rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

target = RemoteTarget(client=rig.control_client(), interface=rig)
```

Those two objects are the whole MyoGestic-side wiring, and they do not change again.
`virtual_hand()` is this same call with VHI's numbers filled in and a Godot path resolved. You
will not use it, because your rig is not a hand and has no Godot binary to launch.

`name=` looks cosmetic and is not: every stream this spec publishes carries the `source_id`
`myogestic:<name>:<address>`, which lets your target find the same stream again after a
restart. Stage 5 is where changing it breaks reconnection.

## Stage 1 — Serve a manifest, and read it back

A remote target's one obligation is `GetControlManifest`. Serve that and nothing else, and a
client can already learn everything about your device. No LSL yet.

**Save this as `my_target.py`:**

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
                pb2.ControlCapability(
                    address=address, kind=pb2.CONTINUOUS, lo=LO, hi=HI, rest=REST
                )
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

`vocabulary_version="2"` is the compatibility gate, and the negative below is what it catches.
`lo=-1.0, hi=1.0, rest=0.0` is the [signed convention](../concepts/controls.md#the-one-convention-a-device-may-not-redefine):
`+1` is the direction the address *name* denotes, so `rig.gripper.closure` at `+1` is
closed and `rig.wrist.pronation` at `+1` is pronated.

!!! tip "End each address in a word that has an opposite"
    `+1` means the direction the address name says, so the name has to say one.
    `rig.gripper` is a part: is `+1` open or closed? `rig.wrist.rotation` is a motion with
    two directions and picks neither. In both cases there is no correct answer for stage 6's
    sign check to compare against, and whoever writes the next map guesses. `closure` and
    `pronation` each have an opposite; `gripper` and `rotation` do not.

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

!!! warning "Not `tools/inspect_control.py`"
    It looks like the tool for this and it is not. It takes no arguments and always loads
    `examples/controls/hand.toml`, which demands six `vhi.prediction.*` addresses plus
    `vhi.control.gesture`. A two-address rig therefore *cannot* satisfy it, and the failure
    is an uncaught traceback out of `resolve()`:

    ```
    ValueError: [dofs] 'fist': this target does not export 'vhi.prediction.thumb.flexion'.
        It exports: rig.gripper.closure, rig.wrist.pronation
    ```

    Had it got past that it would have built LSL outlets and gone looking for VHI's own
    `VHI_Predict` read-back stream. It is a walkthrough of the *Virtual Hand*, not a probe. The
    next stage introduces `tools/inspect_control_map.py`, the one that takes a path.

### The negative: an old target is refused by name

MyoGestic and your target are installed separately, so nothing guarantees a matching pair.
A target speaking vocabulary 1 waits for a wide pose stream nobody publishes any more; it
logs nothing and the device simply never moves. The client refuses it instead. Stop the
target and start the one that reports the wrong version:

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

That message is **one line**: a single string, wrapped here only by your terminal. It names
*your* target, because "update VHI" would be advice about a different program. See it here, at
the direct probe: from stage 3 onwards this exception is caught and turned into a `None`, and
you would never read it.

Restart without `--antique` before going on.

## Stage 2 — Write the control map, and see a bad address refused

The map pairs your model's output names with the addresses the rig declared. Left side yours,
right side the device's. Each line under `[dofs]` declares one **DOF**, one [degree of
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
nothing running the second section says so instead, and it still exits `0`; that is the
"structurally valid" answer, not a pass.

Now break it. Change `rig.wrist.pronation` to `rig.wrist.pronate` and run it again. The
first section prints unchanged, and the second becomes:

```
  This map cannot be used against that target:

  [dofs] 'twist': this target does not export 'rig.wrist.pronate'. Did you mean: rig.wrist.pronation?
      It exports: rig.gripper.closure, rig.wrist.pronation

my-rig.toml was refused.
```

Exit status `1`. The refusal names the address, the near miss, and everything the rig exports,
and it goes to **stderr**, so it can appear above the stdout section it belongs to. `resolve()`
refuses the whole map rather than binding the part it understood: a dropped control is
indistinguishable from one that works and holds still.

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

## Stage 3 — Bind the map with `ControlLink`

Fix the typo. Now build the MyoGestic side, the third file. In your own application this is
whatever calls `bus.push()` from inside `@pipeline.predict`; here it is a script, so there is
something to run.

```python
"""drive.py — the MyoGestic side. Stage 3: just the handshake."""

import tomllib

from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import InterfaceSpec, RemoteTarget

rig = InterfaceSpec(
    name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051
)

#: Held in a variable, not built inline. `link.stop()` deliberately leaves the client
#: alive so the link can be re-used, so this is the only reference that will ever be able
#: to shut its worker thread and gRPC channel down. See the end of stage 5.
client = rig.control_client()

with open("my-rig.toml", "rb") as handle:   # "rb" — tomllib requires binary
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

A bus means the manifest resolved and one LSL outlet per address exists. Your target has not
read a sample yet - it has no inlet code until stage 4, so "bus" here is a long way short of
"connected".

Three outcomes, and they are easy to confuse:

| situation | `link.ensure()` |
|---|---|
| target unreachable | `None` |
| target reachable, address wrong | raises `ValueError` |
| target too old | logs the refusal, returns `None` |

Rows one and three both return `None`: "too old, forever" looks exactly
like "not started yet, try again in a second", and an application built around the retry will
retry forever. Run `drive.py` against `my_target.py --antique` and you get row three, a
`logging.WARNING` on the `myogestic.controls` logger:

```
RemoteTarget refused the handshake: rig speaks control vocabulary 1, and MyoGestic needs 2 or newer. …
```

That reaches stderr even with logging unconfigured, but in a GUI application stderr is a
terminal behind the window. Pass `ctx=` so it lands in the app's own log panel instead:

```python
link = ControlLink(control_map, [target], ctx=ctx, hz=32)
```

## Stage 4 — Read the streams

Now the half that moves. MyoGestic publishes **one LSL stream per address, named for that
address, one channel wide**.

`my_target.py` gains imports, five fields, and seven methods, all inside the **`Rig` class you
already have** — do not start a second `class` statement. `_open`, `_apply`, `_read`,
`_status` and `_watch` are new; **`serve` and `stop` replace the stage-1 versions**, because
both now start and stop the reader thread as well as the gRPC server. If anything below lands
ambiguously, [the finished file](#my_targetpy) is at the end of the page.

New imports:

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

Applying one sample. **This is the one method where a value becomes motion**:

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
                self._stop.wait(1.0)   # `resolve_streams` can raise too — back off
```

And something to watch, because a rig you cannot see is a rig you cannot check:

```python
    def _status(self) -> str:
        """One line naming every address's current value."""
        axes = "  ".join(
            f"{a.removeprefix('rig.')}={self.pose[a]:+.2f}" for a in ADDRESSES
        )
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

**Refuse the wrong width; do not read element zero of it.** That `n_channels != 1` check buys
you a loud failure instead of a quiet one. An inlet is looked up by its address's *stream
name*, so a nine-channel stream called `rig.gripper.closure` reaches only that one address -
and element zero of somebody's nine-channel whole-pose frame is a different DOF's value
entirely (a thumb, say). Read it and your gripper spends the session tracking a thumb,
plausibly, in range, and completely wrong.

### Checkpoint 1: routing, not motion

Add `import time` at the top of `drive.py`, and replace the bare `print(link.ensure())`
inside the `try:` with a loop that drives the two axes to **opposite** values. It stays
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

The first line is the rest frame `RemoteTarget` puts on the wire the moment negotiation
settles; the second is your loop. Both axes, with the right signs on the right ones. The
opposite values are the whole point - `+1` on both would look identical whether the streams
were wired straight, crossed, or one value written onto both. `tests/test_reference_target.py`
drives its two DOFs to `1.0` and `-1.0` for that reason.

### Checkpoint 2: the wrong width, refused

Stop `drive.py` and the target, so nothing is publishing these addresses legitimately. Then
publish one of them at the wrong width, from a script that **stays up**. A producer that pushes
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

Once per resolve sweep, for as long as the bad producer is up. Loud, on purpose. The same
script with `n_channels=1` and *two* outlets under one name gets you the other refusal:

```
rig: rig.gripper.closure is published by 2 outlets at once. One address, one producer — not opening any of them.
```

Order matters, and it is the limit `_open`'s docstring names: a second producer that starts
*after* the target already holds that inlet is not detected at all, and the rig keeps obeying
whichever one it bound to first.

And a one-channel stream carrying a value the rig never agreed to accept gets the third:

```
rig: rig.wrist.pronation sent nan, which is not a finite value in [-1.0, +1.0] — ignored (reported once).
```

Three different producers can be wrong in three different ways, and none of them is your
device's fault. All three say so.

## Stage 5 — Stopping, reconnecting, and staying alive

MyoGestic's outlets **re-send their last value continuously** at `output_hz`, and your
target as written holds the last value it read when nothing arrives. Those two together
mean "the device stopped moving" carries no information at all: it is what a healthy idle
system and a dead producer both look like. So check the shutdown.

### Checkpoint 1: stop returns the device to rest

```python
link.stop()
```

```
rig: gripper.closure=+0.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
```

You will often see two lines, and that is the contract working: the axes are *independent
streams*, so their rest samples arrive milliseconds apart and each applies the moment it lands.
Whether the printer catches the moment between them is luck - read the *last* line, never the
count.

Those lines are [`ControlBus.stop`][myogestic.controls.ControlBus.stop] delivering the neutral
frame *before* tearing the targets down, and `RemoteTarget` pushing **and flushing** each
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

Check this on its own, because a target can work perfectly on its first inlet and fail for
ever after a restart, and nothing says so when it does.

It works here for a reason worth knowing. Your `_read` loop never re-resolved: `_inlets` still
held both addresses, so `missing` was empty and no sweep happened. What reconnected is
**liblsl's own inlet recovery**, which matches a returning outlet by `source_id`.
`InterfaceSpec.stream_outlet` gives every stream a stable one,
`myogestic:<spec name>:<address>`.

!!! danger "Change `InterfaceSpec(name=…)` and reconnection stops, silently"
    The `source_id` is built from that name, so a producer that comes back under a different
    one is, to liblsl, a *different stream*. The inlet stays alive and recovering, waiting
    for a `source_id` that will never return - `pull_chunk` yields empty forever, `missing`
    stays empty, and nothing sweeps, raises or prints. Run the same rig under `name="rig"`
    and then `name="rig-renamed"` and the second producer moves nothing at all, quietly.

    Pick one name per device and keep it.

The `except` around the loop is what keeps the reader alive through the ordinary race where an
outlet vanishes between the resolve and the open. Without it the thread dies while the gRPC
server continues to answer the manifest, so a client binds against a target that will never
read another sample.

### Checkpoint 3: what an *unclean* exit does, and what you choose to do about it

`link.stop()` is the orderly path. If the producer is killed with `SIGKILL`, loses its network,
or crashes, none of it runs: no neutral frame, no flush, no outlet teardown. Under a hold-last
policy the target then retains the last values it received.

Holding is a **policy decision, and it is yours**. Pick one of three and state it in your docs:

| policy | what the rig does when samples stop | when |
|---|---|---|
| hold-last | keeps the last value forever | a display, a simulation, anything that cannot hurt anyone |
| timed rest | returns to `REST` after a declared timeout | a rig with force behind it, driven over a network |
| device deadman | the hardware itself releases without a heartbeat | anything that can injure someone |

The middle one is a *software deadman* and it is about six lines. Take a timestamp whenever a
sample is accepted (`_apply` already does, in `self._fresh`) and add an optional timeout to
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

Restart the rig with the policy armed, then kill the producer mid-grip:

```bash
uv run --extra grpc python my_target.py --rest-after 1.0    # terminal 1
uv run --extra grpc python drive.py                          # terminal 2, then Ctrl-C it
```

The rig lets go on its own about a second later:

```
rig: gripper.closure=+1.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=-1.00
rig: gripper.closure=+0.00  wrist.pronation=+0.00
```

Set the timeout well above your producer's tick interval: at `output_hz=32.0` a sample is due
every 31.25 ms, so one second is about 32 missed samples. A software deadman is not a safety
interlock, and it is not the same job as stream recovery — see
[Design notes](../how-to/drive-a-remote-target.md#design-notes).

## Stage 6 — The sign check

**This is the one stage on this page that cannot be run here.** It needs your device and
your eyes; there is no output to quote and nothing to automate. Everything below is the
procedure, and you perform it.

Command `grip = +1.0` and watch the gripper. It must **close**, because `closure` is what
the name `rig.gripper.closure` denotes at `+1`. Then `-1.0`, and it must open. Command
`twist = +1.0` and the wrist must **pronate**, because that is what `rig.wrist.pronation`
denotes at `+1`; `-1.0` supinates.

This is the first checkpoint a person has to make, and the only one no machine can take
over. Wire the gripper backwards and it opens on `+1` while every automated check stays
green - a read-back of its own would report exactly the opening it performed. This
repository shipped that exact bug with a green suite throughout; [Concepts ›
Controls](../concepts/controls.md#the-one-convention-a-device-may-not-redefine) is where
that rule lives.

The check works at all because the names commit to a direction, which is what stage 1's
naming rule buys: with an address like `rig.gripper`, "is it inverted?" has no answer.

If your rig is inverted, fix it *inside your target*. Flip the sign in `_apply`, where the
value becomes motion. Do not flip it in the map with a `weight = -1.0`, and do not advertise a
second address for the other direction: the range you declared already has both halves, and the
next person to write a map against your manifest will read the name and expect it to mean what
it says.

## Stage 7 — Discrete state

An amount and a held state are different things. A state does not belong on a per-tick stream:
re-sending "clamped" at 32 Hz is 32 commands a second, not one held state. So it travels over
gRPC on change only. Add a mode to the manifest and implement `SetControl`.

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

Then, on `Rig` again (the same class, gaining a field and a method):

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
    running MyoGestic side will keep driving the old two-address contract forever.

    Call `link.stop()` and build a new `ControlLink` from a freshly loaded map. (`stop()` alone
    makes the *link* re-handshake, but it still holds the `ControlMap` object it was
    constructed with, so a change to the TOML needs a new one either way.) Restarting
    `drive.py` does both, so this page is built out of scripts you re-run.

`kind` is yours and only yours. The map never says whether an address takes a number or a held
state, and cannot: change your build so a control becomes discrete and the same map file keeps
working:

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
assert mode.states == ("rest", "active")   # the rig said so; the map never mentioned states
assert mode.rest == "rest"
assert mode.debounce_s == 0.1              # this one the map did say
```

### Checkpoint

Add this to `drive.py` **inside the same `if bus is not None:` block**, after the `for` loop.
Eight spaces of indent, not four:

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

and on the target, **four** lines, in this order, every run:

```
rig: mode -> rest
rig: mode -> active
rig: mode -> rest
rig: mode -> rest
```

The middle two are your `select` calls. The first is the push loop: `mode` is absent from what
you push, so it settles on its declared rest and is delivered once, as an edge. The last is
`link.stop()` delivering the neutral frame.

`select()` returns `True` once the state is one this DOF declares and a frame is queued. It is
fire-and-forget on a worker thread, so it never blocks the predict thread and never raises;
whether the rig *applied* it is a fact on the target's side, which is why the target prints
what it applied. `banana` never reaches the wire: the bus checks it against your declared
states and drops it locally. Delivery timing is not guaranteed — see
[Design notes](../how-to/drive-a-remote-target.md#design-notes).

!!! note "The key in `request.discrete` is your **address**, not the client's alias"
    `rig.mode`, not `mode`. `continuous` is keyed the same way, and so are your
    streams. The alias is the *left*-hand side of somebody else's map: a name they
    invented, which you have never seen and could not interpret. So match the key against
    the addresses you advertised and refuse one you did not, exactly as the code above does.

    This is what lets a rig have more than one discrete control. Give two of them a state
    called `hold` and a command still says which one it is for. The key does, and only the key
    can.

## The finished files

Everything above, assembled. If you have been typing along, this is what you should be
holding; if you have not, this is where you start.

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
                pb2.ControlCapability(
                    address=address, kind=pb2.CONTINUOUS, lo=LO, hi=HI, rest=REST
                )
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
        axes = "  ".join(
            f"{a.removeprefix('rig.')}={self.pose[a]:+.2f}" for a in ADDRESSES
        )
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

import time
import tomllib

from myogestic.controls import ControlLink, load_control_map
from myogestic.remote import InterfaceSpec, RemoteTarget

rig = InterfaceSpec(
    name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051
)

#: Held, not built inline: `link.stop()` deliberately leaves the client alive so the link
#: can be re-used, so this is the only reference that can ever shut its worker thread and
#: gRPC channel down.
client = rig.control_client()

with open("my-rig.toml", "rb") as handle:  # "rb" — tomllib requires binary
    control_map = load_control_map(tomllib.load(handle))

link = ControlLink(control_map, [RemoteTarget(client=client, interface=rig)], hz=32)

try:
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

The whole contract, plus the four things running one asks for that no client can check.

The shortest possible version of all of it is
[`examples/synthetic/reference_target.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/reference_target.py):
eighty lines, six addresses, no discrete controls, hold-last and nothing else. Read it now
that you know why each part is there, and what each part it leaves out would have cost.

## See also

- [Drive a remote target](../how-to/drive-a-remote-target.md) - the contract as a table, and the
  reference implementation in full
- [Concepts › Controls](../concepts/controls.md) - aliases, addresses, and the signed
  convention
- [Drive your own device](../how-to/add-a-target.md) - the in-process route, if you do not
  need a wire between two processes
- `myogestic/remote/_proto/remote_control.proto` - the wire contract; generate stubs from it for
  any language other than Python
