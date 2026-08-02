# Integrate your own interface

You have a device — a gripper, a prosthesis, a robot arm, a game — and you want MyoGestic to
drive it. This builds the thing that makes that happen, in seven stages, each ending in
something you run and watch.

!!! note "This page is about a **renderer**"
    A renderer is a **separate application**, reached over gRPC for its manifest and LSL for
    its values. If your device is a Python object you can `import` — a serial motor
    controller, a cursor, a library — you want a **target** instead: three methods, no
    processes, no wire. See [Drive your own device](../how-to/add-a-target.md). [Concepts ›
    Controls](../concepts/controls.md) explains the fork if you have not taken it yet.

The device here is a two-axis rig: a gripper that closes and opens, and a wrist that rotates.
Substitute your own. Nothing below depends on what the axes *are* — there is exactly one
method where a value becomes motion, and it is marked.

You will end with two files: `my_renderer.py`, which is your device's side, and `my-rig.toml`,
which is the map. Everything runs with:

```bash
uv run --extra grpc python my_renderer.py
```

## First, the naming

MyoGestic's adapter for a renderer is called `VhiTarget`, and it speaks the proto in
`myogestic/vhi/_proto/myogestic_vhi.proto`. That is history, not a requirement: it is the
**generic** renderer adapter, and the Virtual Hand happens to be the renderer that shipped
first. Your rig is not a hand, will not use `virtual_hand()`, and has no Godot binary to
launch. It still uses all three of these:

```python
from myogestic.vhi import InterfaceSpec, VhiTarget

#: Your endpoint and your outlet settings. `process=[]` because nothing launches this —
#: you start your own device. `output_hz` is how fast MyoGestic re-sends each value.
rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

target = VhiTarget(client=rig.control_client(), interface=rig)
```

That is the whole MyoGestic-side wiring, and it does not change again. `virtual_hand()` is
just this call with VHI's numbers filled in and a Godot path resolved.

`name=` looks cosmetic and is not: every stream this spec publishes carries the `source_id`
`myogestic:<name>:<address>`, which is what lets your renderer find the same stream again
after a restart. Stage 5 is where changing it bites.

## Stage 1 — A manifest, and a direct probe

A renderer's one obligation is `GetControlManifest`. Serve that and nothing else, and a
client can already learn everything about your device. No LSL yet.

```python
"""my_renderer.py — stage 1."""

from __future__ import annotations

import threading
from concurrent import futures

import grpc

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto import myogestic_vhi_pb2_grpc as pb2_grpc

#: Your addresses, in your own namespace. The first segment namespaces the device, so
#: `rig.*` cannot collide with `vhi.*` or `keyboard.*` in one map. The address is also the
#: name of the LSL stream that carries it — there is no second name to keep in step.
ADDRESSES = ["rig.gripper", "rig.wrist.rotation"]


class RigRenderer(pb2_grpc.VhiControlServicer):
    """Two axes. Holds the last value it was sent, per address."""

    def __init__(self, port: int = 50051) -> None:
        self.pose = dict.fromkeys(ADDRESSES, 0.0)
        self._port = port
        self._server: grpc.Server | None = None

    def GetControlManifest(self, request, context):  # noqa: N802 - gRPC's spelling
        """What this rig exports. The only call a client must be able to make."""
        manifest = pb2.ControlManifest(target_name="rig", vocabulary_version="2")
        for address in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(
                    address=address, kind=pb2.CONTINUOUS, lo=-1.0, hi=1.0, rest=0.0
                )
            )
        return manifest

    def serve(self) -> None:
        """Start the gRPC server."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_VhiControlServicer_to_server(self, self._server)
        self._server.add_insecure_port(f"127.0.0.1:{self._port}")
        self._server.start()

    def stop(self) -> None:
        """Stop the gRPC server."""
        if self._server is not None:
            self._server.stop(grace=None)


if __name__ == "__main__":
    rig = RigRenderer()
    print("rig renderer on 127.0.0.1:50051 — Ctrl-C to stop")
    rig.serve()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        rig.stop()
```

`vocabulary_version="2"` is not decoration — see the negative below. `lo=-1.0, hi=1.0,
rest=0.0` is the [signed convention](../concepts/controls.md#the-one-convention-a-device-may-not-redefine):
`+1` is the direction the address *name* denotes, so `rig.gripper` at `+1` closes.

### Checkpoint

Leave it running in one terminal. In another, ask it what it exports — through the real
client, so the answer you see is the one MyoGestic will get:

```python
"""probe.py"""

from myogestic.vhi import virtual_hand

client = virtual_hand(grpc_port=50051).control_client()
for cap in client.capabilities():
    print(f"{cap.address:20s} {cap.kind}  [{cap.lo:+.1f}, {cap.hi:+.1f}]  rest={cap.rest:+.1f}")
client.stop()
```

```
rig.gripper          continuous  [-1.0, +1.0]  rest=+0.0
rig.wrist.rotation   continuous  [-1.0, +1.0]  rest=+0.0
```

(`virtual_hand(grpc_port=…)` is used here only because it is the shortest way to a client on
a port. The `InterfaceSpec` from the previous section gives the same thing.)

!!! warning "Not `tools/inspect_control.py`"
    It looks like the tool for this and it is not. It takes no arguments and always loads
    `examples/controls/hand.toml`, which demands six `vhi.prediction.*` addresses plus
    `vhi.control.gesture`. A two-address rig therefore *cannot* satisfy it, and the failure
    is an uncaught traceback out of `resolve()`, seven errors long:

    ```
    ValueError: [dofs] 'fist': this target does not export 'vhi.prediction.thumb.flexion'.
        It exports: rig.gripper, rig.wrist.rotation
    ```

    Had it got past that it would have built LSL outlets and gone looking for VHI's own
    `VHI_Predict` read-back stream. It is a walkthrough of the *Virtual Hand*, not a probe.
    The next stage introduces `tools/inspect_control_map.py`, which is the one that takes a
    path.

### The negative: an old renderer is refused by name

MyoGestic and your renderer are installed separately, so nothing guarantees a matching pair.
A renderer speaking vocabulary 1 waits for a wide pose stream nobody publishes any more; it
logs nothing and the device simply never moves. The client refuses it instead. Report the
wrong version on purpose, once:

```python
class Antique(RigRenderer):
    def GetControlManifest(self, request, context):  # noqa: N802
        manifest = super().GetControlManifest(request, context)
        manifest.vocabulary_version = "1"
        return manifest
```

`client.capabilities()` now raises `ValueError`:

```
rig speaks control vocabulary 1, and MyoGestic needs 2 or newer. Vocabulary 2 publishes one
LSL stream per control, named for that control's own address and one channel wide;
vocabulary 1 read a single wide pose stream that MyoGestic no longer sends. Paired with this
client such a renderer would report no error and never move. Update rig.
```

It names *your* renderer, because "update VHI" would be advice about a different program.
See it here, at the direct probe — from stage 3 onwards this exception is caught and turned
into a `None`, and you would never read it.

## Stage 2 — The map, and a typo

The map pairs your model's output names with the addresses the rig declared. Left side yours,
right side the device's.

```toml
# my-rig.toml
[dofs]
grip = "rig.gripper"
twist = "rig.wrist.rotation"
```

### Checkpoint

`tools/inspect_control_map.py` takes a path. It calls only `capabilities()` and `resolve()` —
it builds no target and publishes no stream, so it cannot move anything:

```bash
uv run --extra grpc python tools/inspect_control_map.py my-rig.toml
```

```
──────────────────────────────────────────────────────────────────────────────
Resolved against a live target
──────────────────────────────────────────────────────────────────────────────
  The target exports 2 controls.

  grip   NUMBER  [-1.0, +1.0]
           x1.0   -> rig.gripper
  twist  NUMBER  [-1.0, +1.0]
           x1.0   -> rig.wrist.rotation

  Every kind, range and state above came from the target, not the file.

my-rig.toml is usable against this target.
```

It reaches your renderer at `127.0.0.1:50051` — set `VHI_GRPC_PORT` if you moved it. With
nothing running it still checks the file and says so, and exits `0`; that is the "structurally
valid" answer, not a pass.

Now break it. Change `rig.wrist.rotation` to `rig.wrist.rotate` and run it again:

```
  This map cannot be used against that target:

  [dofs] 'twist': this target does not export 'rig.wrist.rotate'. Did you mean: rig.wrist.rotation?
      It exports: rig.gripper, rig.wrist.rotation
```

Exit status `1`, and the refusal goes to stderr. Note what is in it: the address, the near
miss, and **everything the rig exports**. `resolve()` raises rather than binding the one
address it understood, because a silently dropped control is indistinguishable from a control
that works and holds still — you would move, see nothing, and go looking at your model.

The "Did you mean" hint is the addresses sharing the longest dotted prefix with what you
wrote, so it is absent only when nothing matches even the namespace. Here is that refusal
with no renderer running at all, resolved against a manifest written by hand:

<!--docs:run-->
```python
from myogestic.controls import Capability, load_control_map, resolve

rig_manifest = [
    Capability("rig.gripper", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability("rig.wrist.rotation", "continuous", lo=-1.0, hi=1.0, rest=0.0),
]

try:
    resolve(load_control_map({"dofs": {"twist": "rig.wrist.rotate"}}), rig_manifest)
except ValueError as exc:
    assert "Did you mean: rig.wrist.rotation" in str(exc)
    assert "It exports: rig.gripper, rig.wrist.rotation" in str(exc)

# Nothing shares even the namespace, so there is no near miss to offer.
try:
    resolve(load_control_map({"dofs": {"twist": "arm.wrist.rotation"}}), rig_manifest)
except ValueError as exc:
    assert "Did you mean" not in str(exc)
```

## Stage 3 — `ControlLink`, and what a bus does *not* prove

Fix the typo. Now build the MyoGestic side: a map, one `VhiTarget`, and a
[`ControlLink`][myogestic.controls.ControlLink] holding the retry.

```python
"""drive.py — the MyoGestic side, and it does not change again."""

import tomllib

from myogestic.controls import ControlLink, load_control_map
from myogestic.vhi import InterfaceSpec, VhiTarget

rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0, grpc_port=50051)

with open("my-rig.toml", "rb") as handle:   # "rb" — tomllib requires binary
    control_map = load_control_map(tomllib.load(handle))

link = ControlLink(control_map, [VhiTarget(client=rig.control_client(), interface=rig)], hz=32)
print(link.ensure())
```

### Checkpoint

With the renderer stopped, `ensure()` prints `None`. Start it and run again, and you get a
`ControlBus`.

**A bus proves less than it looks like it proves.** It means the manifest resolved and one
LSL outlet per address was constructed. Your renderer has not read a single sample — it has
no inlet code yet. Do not read "bus" as "connected".

Three outcomes, and they are easy to confuse:

| situation | `link.ensure()` |
|---|---|
| renderer unreachable | `None` |
| renderer reachable, address wrong | raises `ValueError` |
| renderer too old | logs the refusal, returns `None` |

Rows one and three both hand you `None`, and that is the trap: "too old, forever" looks
exactly like "not started yet, try again in a second", and an application built around the
retry will retry for ever. The refusal is a `logging.WARNING` on the `myogestic.controls`
logger —

```
VhiTarget refused the handshake: rig speaks control vocabulary 1, and MyoGestic needs 2 or newer. …
```

— which reaches stderr even with logging unconfigured, but in a GUI application stderr is a
terminal behind the window. Pass `ctx=` so it lands in the app's own log panel instead:

```python
link = ControlLink(control_map, [target], ctx=ctx, hz=32)
```

Here are all three, with nothing launched — the branch `connect_controls` actually takes is
decided entirely by what a target's `capabilities()` does:

<!--docs:run-->
```python
from myogestic.controls import Capability, ControlLink, load_control_map

control_map = load_control_map({"dofs": {"grip": "rig.gripper"}})
manifest = [Capability("rig.gripper", "continuous", lo=-1.0, hi=1.0, rest=0.0)]


class Unreachable:
    """Not started. `None` — never an empty list, which would mean 'renders nothing'."""

    def capabilities(self):
        return None


class TooOld:
    """Answered, and the client refused the answer."""

    def capabilities(self):
        raise ValueError("rig speaks control vocabulary 1, and MyoGestic needs 2 or newer.")


class Reachable:
    """Answers, binds, and renders."""

    claims = frozenset({"grip"})

    def capabilities(self):
        return manifest

    def bind(self, controls): ...
    def send(self, values, changed): ...
    def stop(self): ...


assert ControlLink(control_map, [Unreachable()]).ensure() is None
assert ControlLink(control_map, [TooOld()]).ensure() is None      # logged, not raised
assert ControlLink(control_map, [Reachable()]).ensure() is not None

# Reachable, but the map names something it does not export: this one raises.
wrong = load_control_map({"dofs": {"grip": "rig.griper"}})
try:
    ControlLink(wrong, [Reachable()]).ensure()
except ValueError as exc:
    assert "does not export 'rig.griper'" in str(exc)
```

## Stage 4 — Read the streams

Now the half that moves. MyoGestic publishes **one LSL stream per address, named for that
address, one channel wide**. Add an inlet thread and a status printer to `my_renderer.py`:

```python
from contextlib import suppress

from mne_lsl.lsl import StreamInlet, resolve_streams


class RigRenderer(pb2_grpc.VhiControlServicer):   # ...continued

    def _read(self) -> None:
        """Read every stream and apply each value as it arrives.

        One thread, not one per stream: `resolve_streams` is a multicast sweep of the whole
        network, and one sweep already answers for every stream still missing an inlet.
        """
        inlets: dict[str, StreamInlet] = {}
        while not self._stop.is_set():
            # Resolving is inside the `try` too: an outlet can vanish between the resolve
            # and the open. Outside it, that ordinary race kills this thread while the gRPC
            # server keeps answering the manifest — a client would bind successfully
            # against a renderer that never reads another sample.
            try:
                missing = [a for a in ADDRESSES if a not in inlets]
                if missing:
                    found = {s.name: s for s in resolve_streams(timeout=1.0)}
                    for address in missing:
                        info = found.get(address)
                        if info is None:
                            continue
                        if info.n_channels != 1:
                            print(
                                f"rig: {address} is published {info.n_channels} channels "
                                f"wide; this contract is one channel. Not opening it."
                            )
                            continue
                        inlets[address] = StreamInlet(info)
                        inlets[address].open_stream()
                for address, inlet in inlets.items():
                    chunk, _ = inlet.pull_chunk(timeout=0.0)
                    if chunk is not None and len(chunk):
                        # One channel, so there is nothing to unpack: `chunk[-1][0]` is the
                        # whole sample. THIS is where a value becomes motion — call your
                        # actuator here instead of storing it.
                        self.pose[address] = float(chunk[-1][0])
                self._stop.wait(0.005)
            except Exception as exc:  # noqa: BLE001 - this thread must survive
                print(f"rig: lost an inlet ({type(exc).__name__}: {exc}), re-resolving")
                for inlet in inlets.values():
                    with suppress(Exception):
                        inlet.close_stream()
                inlets.clear()
                self._stop.wait(1.0)   # `resolve_streams` can raise too — back off
```

…plus a `threading.Event()` named `self._stop` in `__init__`, a
`threading.Thread(target=self._read, daemon=True).start()` in `serve()`, `self._stop.set()`
in `stop()`, and a second thread printing `self.pose` whenever it changes so you can see
what is happening.

**Refuse the wrong width; do not read element zero of it.** That `n_channels != 1` check is
the difference between a loud failure and a silent one. An out-of-date client publishing one
nine-channel pose stream would otherwise render its first value onto every axis, and say
nothing about it.

### Checkpoint 1: routing, not motion

Drive the two axes to **opposite** values:

```python
import time

bus = link.ensure()
for _ in range(80):
    bus.push({"grip": 1.0, "twist": -1.0})
    time.sleep(0.05)
```

```
rig: gripper=+1.00  wrist.rotation=-1.00
```

Both, with the right signs on the right axes. Equal values on both would prove nothing —
`+1` and `+1` looks identical whether the streams are correctly wired or crossed, or whether
one value is being written onto both. That is why
`tests/test_reference_renderer.py` drives its two DOFs to `1.0` and `-1.0` and not to the
same number.

### Checkpoint 2: the wrong width, refused

Publish a nine-channel stream under one of your addresses and start the renderer:

```python
import numpy as np

from myogestic.outputs import LSLOutlet

wide = LSLOutlet(name="rig.gripper", n_channels=9, hz=32)
wide.push(np.ones(9, dtype=np.float32))
```

```
rig: rig.gripper is published 9 channels wide; this contract is one channel. Not opening it.
```

Once per resolve sweep, for as long as the bad producer is up. Loud, which is the point.

## Stage 5 — Stopping, and reconnecting

MyoGestic's outlets **re-send their last value continuously** at `output_hz`, and your
renderer deliberately holds the last value it read when nothing arrives. Those two together
mean "the device stopped moving" carries no information at all: it is what a healthy idle
system and a dead producer both look like. So check the shutdown.

### Checkpoint 1: stop returns the device to rest

```python
link.stop()
```

```
rig: gripper=+0.00  wrist.rotation=+0.00
```

That is [`ControlBus.stop`][myogestic.controls.ControlBus.stop] delivering the neutral frame
*before* tearing the targets down, and `VhiTarget` pushing **and flushing** each stream's
declared rest before it releases the outlet. The send loop is paced, so a pushed-but-unflushed
rest would sit unsent while the outlet went away.

**An unclean exit does none of this.** Kill the producer with `SIGKILL`, pull its network
cable, let it segfault, and your rig keeps holding the last thing it was told — a gripper
closed with nothing behind it. That is not a bug you can fix in the renderer; it is why
whatever safety interlock your hardware needs belongs in the hardware, not in this file.

### Checkpoint 2: it reconnects

Stop the producer, then start a fresh one — leaving the renderer up throughout — and drive
the axes the other way:

```
rig: gripper=+1.00  wrist.rotation=-1.00
rig: gripper=+0.00  wrist.rotation=+0.00
rig: gripper=-1.00  wrist.rotation=+1.00
```

Check this on its own, because a renderer can work perfectly on its first inlet and fail for
ever after a restart, and nothing says so when it does.

It works here for a reason worth knowing. Your `_read` loop never re-resolved: `inlets`
still held both addresses, so `missing` was empty and no sweep happened. What reconnected is
**liblsl's own inlet recovery**, which matches a returning outlet by `source_id` — and
`InterfaceSpec.stream_outlet` gives every stream a stable one, `myogestic:<spec name>:<address>`.

!!! danger "Change `InterfaceSpec(name=…)` and reconnection stops, silently"
    The `source_id` is built from that name, so a producer that comes back under a different
    one is, to liblsl, a *different stream*. The renderer's inlet is not broken — it is alive
    and recovering, waiting for a `source_id` that will never return — so `pull_chunk` yields
    empty for ever, `missing` stays empty, no sweep is triggered, nothing raises, and nothing
    is printed. Running the same rig under `name="rig"` and then `name="rig-renamed"`, the
    second producer moves nothing at all and says nothing about it.

    Pick one name per device and keep it.

The `except` around the loop is still doing real work — it is what keeps the reader thread
alive through the ordinary race where an outlet vanishes between the resolve and the open.
Take it out and the thread dies while the gRPC server keeps cheerfully answering the
manifest: a client binds successfully against a renderer that will never read another sample.

## Stage 6 — The sign check

Look at the device.

Command `grip = +1.0` and watch the gripper with your own eyes. It must **close**, because
that is what the name `rig.gripper` denotes at `+1`. Then `-1.0`, and it must open. Same for
`rig.wrist.rotation`, in whichever direction its name claims.

This is the first checkpoint a person has to make, and it is the only one that cannot be
automated, because **a device and its own read-back agree whichever way they point**. Wire
the gripper backwards and it opens on `+1`; if it published a read-back stream that stream
would report exactly the opening it performed; every contract test would pass. This
repository shipped that exact bug with a green suite throughout. If your rig is inverted,
fix it *inside your renderer* — flip the sign where the value becomes motion. Do not flip it
in the map with a `weight = -1.0`, and do not advertise a second address for the other
direction: the range you declared already has both halves, and the next person to write a map
against your manifest will read the name and expect it to mean what it says.

## Stage 7 — Discrete state

An amount and a held state are different things. A state does not belong on a per-tick
stream — re-sending "clamped" at 32 Hz is 32 commands a second, not one held state — so it
travels over gRPC on change only. Add a mode to the manifest and implement `SetControl`:

```python
MODES = ("rest", "active")

#: One more capability, appended in `GetControlManifest` after the continuous loop:
#: `manifest.capabilities.append(MODE_CAPABILITY)`.
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


class RigRenderer(pb2_grpc.VhiControlServicer):   # ...continued

    def SetControl(self, request, context):  # noqa: N802 - gRPC's spelling
        """Apply held states. Refuse by name anything this rig cannot do."""
        rejected = {}
        for key, state in request.discrete.items():
            if state in MODES:
                self.mode = state
            else:
                rejected[key] = f"{state!r} is not one of {list(MODES)}"
        return pb2.ControlAck(applied=not rejected, rejected=rejected)
```

Then add the alias to `my-rig.toml`. `debounce_s` is how long a state must hold before it
counts — a property of *your control loop*, not of the rig, which is why it lives in the map
and not in the manifest:

```toml
# my-rig.toml
[dofs]
grip = "rig.gripper"
twist = "rig.wrist.rotation"
mode = { target = "rig.mode", debounce_s = 0.1 }
```

!!! warning "Neither side notices that you edited those two files"
    [`ControlLink.ensure()`][myogestic.controls.ControlLink.ensure] returns its cached bus
    without a second handshake once it has one, and `VhiTarget` caches what it resolved and
    has no detection of a changed manifest. Restarting your renderer is not enough; the
    running MyoGestic side will keep driving the old two-address contract for ever.

    Call `link.stop()` and build a new `ControlLink` from a freshly-loaded map. (`stop()`
    alone makes the *link* re-handshake, but it still holds the `ControlMap` object it was
    constructed with, so a change to the TOML needs a new one either way.)

`kind` is yours and only yours. The map never says whether an address takes a number or a
held state, and cannot — change your build so a control becomes discrete and the same map
file keeps working:

<!--docs:run-->
```python
from myogestic.controls import Capability, load_control_map, resolve

manifest = [
    Capability("rig.gripper", "continuous", lo=-1.0, hi=1.0, rest=0.0),
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
                "grip": "rig.gripper",
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

```python
print(bus.select("mode", "active"))
print(bus.select("mode", "rest"))
print(bus.select("mode", "banana"))
```

```
True
True
False
```

and on the renderer:

```
rig: gripper=+0.00  wrist.rotation=+0.00  mode=active
rig: gripper=+0.00  wrist.rotation=+0.00  mode=rest
```

**`True` is a weaker claim than it looks.** `set_control` is fire-and-forget on a worker
thread — it never blocks the predict thread and never raises — so `select()` returning `True`
says only that the state was one this DOF declares and that a frame was queued. Whether the
rig applied it is a fact on the *renderer's* side, which is why the renderer prints the state
it applied. `banana` never reaches the wire at all: the bus checks it against the states your
manifest declared and drops it locally.

To see a populated `rejected`, send a state the rig does not have without going through the
bus — which is exactly what some other program on the network would do:

```
applied: False  rejected: {'mode': "'banana' is not one of ['rest', 'active']"}
```

A rejection is logged by the client as `VHI rejected control values: {…}` and nothing raises;
the frame is simply not applied.

!!! note "The key in `request.discrete` is the client's **alias**, not your address"
    MyoGestic forwards the map's *left-hand* name — `mode`, not `rig.mode`. You cannot match
    those keys against the addresses you advertised, and that is why the code above resolves
    on the **state** and uses the key only to report a rejection. VHI does the same. With
    more than one discrete control this is genuinely ambiguous today, so keep to one, or
    give your states names that are unique across them.

## What you have

A renderer that declares its own vocabulary, is bound against by name, reads one stream per
axis, refuses a wrong-width producer, comes back after a restart, moves in the direction its
names claim, and holds a state. That is the entire contract.

The shortest possible version of all of it is
[`examples/synthetic/reference_renderer.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/synthetic/reference_renderer.py)
— eighty lines, six addresses, no discrete controls. Read it now that you know why each part
is there.

## See also

- [Build a renderer](../how-to/build-a-renderer.md) — the contract as a table, and the
  reference implementation in full
- [Concepts › Controls](../concepts/controls.md) — aliases, addresses, and the signed
  convention
- [Drive your own device](../how-to/add-a-target.md) — the in-process route, if a renderer
  turns out to be more than you need
- `myogestic/vhi/_proto/myogestic_vhi.proto` — the wire contract; generate stubs from it for
  any language other than Python
