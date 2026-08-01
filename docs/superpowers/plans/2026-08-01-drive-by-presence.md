# Drive by Presence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make driving VHI's control hand work the way driving its predicted hand already does — publish the stream and it renders — so `Declare` has nothing load-bearing left and a new renderer's minimum contract is one RPC and a socket.

**Architecture:** VHI's control hand only consumes `MyoGestic_ControlPose` when `DriverMode == Stream`, and the only way into that mode is a `Declare(control_pose=true)` RPC whose side effect is `SetDriverMode(Stream)`. The predicted hand has no such gate: publish `MyoGestic_Output` and it renders. This plan makes the control hand follow the same rule — mode follows inlet presence — then removes `Declare` from both repos, because everything else it returns (`continuous_channel_order`, `accepted`, verdicts) is derivable from `GetControlManifest`, which MyoGestic already fetches and already validates against.

**Tech Stack:** C# / Godot 4.6 (.NET 8 SDK at `~/.dotnet/dotnet`), Python 3.12+ / `uv`, gRPC + protobuf, Lab Streaming Layer (liblsl 1.16.2 via SharpLSL).

## Global Constraints

- **Land the two existing branches first.** This plan assumes `fixes/vhi-lifecycle-and-manifest` (MyoGestic) and `refactor/one-control-service` (VHI) are merged to their `main`s. Both carry a direction fix and a pose-convention wire break; stacking a third wire break on unreviewed work is what this plan exists to avoid. Do not start Task 1 until both are merged.
- **Both repos land together.** MyoGestic stops calling `Declare`; VHI stops serving it. Either alone leaves a client that hangs on a missing RPC or a renderer nobody talks to.
- **Build VHI with `~/.dotnet/dotnet build`** — the repo pins SDK 8.0.0 in `global.json` and the Homebrew `dotnet` on this machine is 10.x.
- **Run the MyoGestic suite with VHI *not* running.** LSL contention fails ~1–7 tests otherwise, and has crashed VHI. Clean baseline is 1595 passed.
- **Never run a concurrent LSL resolve loop on this machine.** It kernel-panicked it on 2026-07-31 (`panic-full-2026-07-31-193403`, configd watchdog). Single producer + single consumer only.
- **Direction convention is settled and must not regress:** `+1` is the direction a DOF's name denotes; a fist is `[1, -1, 1, 1, 1, 1, 0, 0, 0]` on both `VHI_Control` and `VHI_Predict`.
- **No AI attribution in commit messages.**

## File Structure

| File | Responsibility after this plan |
|---|---|
| `Virtual-Hand-Interface/src/LSLCommunicationController.cs` | Owns both inlets. Gains a control-pose staleness timer mirroring the prediction one, and a public `ControlPoseLive` the control hand reads. |
| `Virtual-Hand-Interface/src/ControlHandSkeleton.cs` | Driver mode follows `ControlPoseLive` instead of an RPC. `AcceptControlPoseStream` / `ReleaseControlPoseStream` deleted. |
| `Virtual-Hand-Interface/src/VhiControlService.cs` | `Declare` handler deleted. Manifest, `SetControl`, `SweepControl`, `SetPresentation` and the four recording RPCs stay. |
| `Virtual-Hand-Interface/proto/myogestic_vhi.proto` | `rpc Declare`, `DeclareRequest`, `DeclareReply`, `DofDeclaration`, `DofVerdict` removed. |
| `MyoGestic/myogestic/vhi/_control.py` | `VhiControlClient.declare` and `declare_request` deleted; `unimplemented` flag deleted with them. |
| `MyoGestic/myogestic/vhi/target.py` | `_negotiate_routed` / `_negotiate_by_name` resolve from `capabilities()` alone. |
| `MyoGestic/examples/synthetic/reference_renderer.py` | **New.** ~80-line renderer proving the minimum contract: serve `GetControlManifest`, read the LSL stream. |
| `MyoGestic/docs/how-to/build-a-renderer.md` | **New.** The missing guide, with the reference renderer as its executable body. |

---

### Task 1: The control-pose inlet reports whether it is live

VHI drops a *prediction* inlet that has gone quiet, on a 5 s timer. The control-pose inlet has no such timer — it is dropped only when a pull raises. Presence-driven mode needs a release signal, so it needs the same timer.

**Files:**
- Modify: `Virtual-Hand-Interface/src/LSLCommunicationController.cs`
- Test: `Virtual-Hand-Interface/tests/test_v2_contract.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `public bool ControlPoseLive { get; private set; }` on `LSLCommunicationController` — `true` while the control-pose inlet has delivered a sample within `ControlPoseStaleAfterSeconds`. Task 2 reads it.

- [ ] **Step 1: Write the failing test**

Add to `Virtual-Hand-Interface/tests/test_v2_contract.py`:

```python
def test_the_control_hand_follows_the_control_pose_stream(v2, control_inlet):
    """Publish MyoGestic_ControlPose and the control hand renders it. No handshake.

    The predicted hand has always worked this way — publish MyoGestic_Output and it
    moves. The control hand required a Declare(control_pose=true) whose only effect was
    a mode flip, so the same idea needed a ceremony on one stream and not the other.
    """
    pylsl = pytest.importorskip("pylsl")
    info = pylsl.StreamInfo("MyoGestic_ControlPose", "Control", 9, 60, "float32", "presence")
    outlet = pylsl.StreamOutlet(info)
    frame = [0.0] * 9
    frame[2] = 1.0  # index flexion
    sample = None
    try:
        deadline = time.time() + 25.0
        while time.time() < deadline:
            outlet.push_sample(frame)
            control_inlet.flush()
            time.sleep(0.5)
            sample, _ = control_inlet.pull_sample(timeout=2.0)
            if sample and sample[2] > 0.9:
                break
        assert sample, "VHI_Control never delivered a sample"
    finally:
        del outlet
    assert sample[2] == pytest.approx(1.0, abs=0.05), f"index not driven: {sample}"
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface
pkill -9 -f "Godot.app"; sleep 2
uv run --group test pytest tests/test_v2_contract.py -q -k "follows_the_control_pose"
```

Expected: FAIL on `assert sample[2] == approx(1.0)` — the control hand stays in Movement mode and reports its own animation, not the stream.

- [ ] **Step 3: Add the staleness timer and the liveness flag**

In `src/LSLCommunicationController.cs`, beside `PredictionStaleAfterSeconds`:

```csharp
	/// <summary>Silence after which the control-pose inlet is assumed gone.</summary>
	/// <remarks>
	/// The prediction inlet has had one of these; this one had not, and was dropped only
	/// when a pull raised. Presence is now what puts the control hand into Stream mode, so
	/// "the producer stopped" needs to be observable rather than inferred from an error
	/// that a quiet-but-alive outlet never raises.
	/// </remarks>
	[Export] public float ControlPoseStaleAfterSeconds = 5.0f;

	/// <summary>Whether the control-pose stream is delivering right now.</summary>
	/// <remarks>
	/// `ControlHandSkeleton` reads this to decide whether to render the stream or run its
	/// movement state machine. It is the whole of the old `Declare(control_pose=true)`
	/// handshake: publish the stream and the hand follows it, exactly as the predicted
	/// hand has always followed `MyoGestic_Output`.
	/// </remarks>
	public bool ControlPoseLive { get; private set; }

	private DateTime lastControlPoseSample = DateTime.Now;
```

Replace the control-pose pull block (currently `if (controlPoseInlet != null) { try { while (LSLWrapper.PullSample(...)) ... } catch ... }`) with:

```csharp
		if (controlPoseInlet != null)
		{
			try
			{
				int got = 0;
				while (LSLWrapper.PullSample(controlPoseInlet, controlPoseBuffer, 0.0) > 0)
				{
					receivedDataControl = [.. controlPoseBuffer];
					got++;
				}
				if (got > 0)
					lastControlPoseSample = DateTime.Now;
			}
			catch (Exception e)
			{
				GD.PrintErr($"Error pulling LSL control-pose sample: {e.Message}");
				DropInlet(ref controlPoseInlet);
				receivedDataControl.Clear();
			}
		}

		// Presence, evaluated every frame: an inlet that exists but has gone quiet is a
		// producer that stopped, and the hand should go back to its own movements rather
		// than hold the last streamed pose forever.
		ControlPoseLive =
			controlPoseInlet != null
			&& (DateTime.Now - lastControlPoseSample).TotalSeconds < ControlPoseStaleAfterSeconds;
```

- [ ] **Step 4: Build**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface
~/.dotnet/dotnet build 2>&1 | grep -E "error|^Build succeeded"
```

Expected: `Build succeeded.`

- [ ] **Step 5: Confirm the test still fails, for the right reason**

```bash
pkill -9 -f "Godot.app"; sleep 2
uv run --group test pytest tests/test_v2_contract.py -q -k "follows_the_control_pose"
```

Expected: still FAIL. `ControlPoseLive` is now correct but nothing reads it — that is Task 2. Confirming the failure has not changed shape is the point of this step.

- [ ] **Step 6: Commit**

```bash
git add src/LSLCommunicationController.cs tests/test_v2_contract.py
git commit -m "feat(vhi): the control-pose inlet reports whether it is live

The prediction inlet has had a staleness timer; this one was dropped only when a
pull raised, which a quiet-but-alive outlet never does. Presence is about to be
what puts the control hand into Stream mode, so 'the producer stopped' has to be
observable.

The test that wants this is committed failing: nothing reads ControlPoseLive yet."
```

---

### Task 2: The control hand follows the stream, not a handshake

**Files:**
- Modify: `Virtual-Hand-Interface/src/ControlHandSkeleton.cs`
- Test: `Virtual-Hand-Interface/tests/test_v2_contract.py` (the test from Task 1)

**Interfaces:**
- Consumes: `LSLCommunicationController.ControlPoseLive` (Task 1).
- Produces: `ControlHandSkeleton` no longer exposes `AcceptControlPoseStream()` or `ReleaseControlPoseStream()`. Task 3 deletes their only callers.

- [ ] **Step 1: Make `_Process` choose its branch from presence**

In `src/ControlHandSkeleton.cs`, replace the `switch (DriverMode)` block in `_Process` with:

```csharp
	public override void _Process(double delta)
	{
		// Presence decides, not a handshake. A control-pose stream that is delivering is a
		// client driving this hand; one that is not is a client that stopped, or was never
		// there. The predicted hand has always worked this way — it renders whatever arrives
		// on MyoGestic_Output — and the two hands differing on that was the whole reason
		// Declare had a side effect.
		if (communicationController != null && communicationController.ControlPoseLive)
		{
			currentData = communicationController.GetReceivedDataControl();
			// Standard values mean +1 is the direction the channel's name denotes. They stay
			// standard from here: MoveBonesFromStream multiplies by StandardPose.AtPlusOne,
			// so only the domain clamp is owed.
			StandardPose.Clamp(currentData);
			if (currentData.Count >= 9 && skeleton != null)
				MoveBonesFromStream();
			return;
		}

		HandleMovementInput();
		UpdateMovementAnimation((float)delta);
	}
```

- [ ] **Step 2: Delete the two acquisition methods**

Delete `AcceptControlPoseStream()` and `ReleaseControlPoseStream()` and their doc comments from `src/ControlHandSkeleton.cs`. Leave `SetDriverMode` and the `DriverMode` field alone for now — Task 3 removes their last callers, and deleting them here would break the build mid-task.

- [ ] **Step 3: Build**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface
~/.dotnet/dotnet build 2>&1 | grep -E "error|^Build succeeded"
```

Expected: errors in `VhiControlService.cs` — `AcceptControlPoseStream` / `ReleaseControlPoseStream` no longer exist. Comment out those two call sites to get a build, then Task 3 removes the whole handler. Record which lines you commented; Task 3 deletes them.

- [ ] **Step 4: Run the Task 1 test**

```bash
pkill -9 -f "Godot.app"; sleep 2
uv run --group test pytest tests/test_v2_contract.py -q -k "follows_the_control_pose"
```

Expected: PASS. Publishing `MyoGestic_ControlPose` now drives the control hand with no RPC at all.

- [ ] **Step 5: Verify the release direction too**

```bash
pkill -9 -f "Godot.app"; sleep 2
uv run --group test pytest tests/test_v2_contract.py -q -k "named_flexion or named_fist"
```

Expected: PASS (6 tests). These hold a *movement* on the control hand, which only works if the hand returns to its state machine when no control-pose stream is present — i.e. that the release half of presence works.

- [ ] **Step 6: Commit**

```bash
git add src/ControlHandSkeleton.cs src/VhiControlService.cs
git commit -m "feat(vhi): the control hand follows its stream, like the predicted one

AcceptControlPoseStream was SetDriverMode(Stream) and nothing else, reachable
only through Declare. So driving the control hand needed a gRPC handshake while
driving the predicted hand needed only an LSL outlet — the same idea, one of them
with a ceremony.

Mode follows presence now: a control-pose stream that is delivering drives the
hand, and one that has gone quiet for ControlPoseStaleAfterSeconds gives it back
to the movement state machine."
```

---

### Task 3: Delete `Declare` from VHI

**Files:**
- Modify: `Virtual-Hand-Interface/src/VhiControlService.cs`
- Modify: `Virtual-Hand-Interface/proto/myogestic_vhi.proto`
- Modify: `Virtual-Hand-Interface/tests/test_v2_contract.py`
- Modify: `Virtual-Hand-Interface/src/ControlHandSkeleton.cs`

**Interfaces:**
- Consumes: Task 2's presence-driven mode.
- Produces: a service with 8 RPCs. `GetControlManifest`, `SetControl`, `SweepControl`, `SetPresentation` and the four recording RPCs are unchanged.

- [ ] **Step 1: Delete the 16 Declare tests**

In `tests/test_v2_contract.py`, delete every test that calls `_declare(`, and the `_declare` helper itself. Find them with:

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface
grep -n "_declare(" tests/test_v2_contract.py
```

Delete the whole `# --- Declare ---` section and the discrete-DOF tests that declare. **Keep** `test_a_pose_frame_lands_on_the_channel_the_manifest_names` — rewrite its first line from `assert _declare(stub, pb2, "vhi.prediction.index", "vhi.prediction.middle").accepted` to a comment saying no declaration is needed, since that is now the claim.

- [ ] **Step 2: Delete the handler**

In `src/VhiControlService.cs`, delete the entire `public override Task<DeclareReply> Declare(...)` method, the `Aliases`-filtered `AdvertisedOrder` usages that only fed it (`PredictionOrder`, `ControlPoseOrder` — check with `grep -n "PredictionOrder\|ControlPoseOrder" src/VhiControlService.cs` and delete any left with no callers), and the two call sites commented out in Task 2.

- [ ] **Step 3: Delete `DriverMode` plumbing left with no callers**

```bash
grep -rn "SetDriverMode\|ControlHandDriverMode" src/ | grep -v "^src/MovementDefinitions.cs"
```

Delete `SetDriverMode`, the `[Export] public ControlHandDriverMode DriverMode` field, and the `ControlHandDriverMode` enum in `src/MovementDefinitions.cs`, if and only if that grep shows no remaining readers. Mode is now derived from presence every frame, so a stored mode is a second source of truth.

- [ ] **Step 4: Remove Declare from the proto**

In `proto/myogestic_vhi.proto`, delete `rpc Declare (DeclareRequest) returns (DeclareReply);` and the `DeclareRequest`, `DeclareReply`, `DofDeclaration`, `DofVerdict` messages. Leave the field numbers of surviving messages untouched.

- [ ] **Step 5: Build and run the whole contract suite**

```bash
~/.dotnet/dotnet build 2>&1 | grep -E "error|^Build succeeded"
pkill -9 -f "Godot.app"; sleep 2
uv run --group test pytest tests/test_v2_contract.py -q
```

Expected: `Build succeeded.` and all remaining tests pass. The suite regenerates its stubs from `proto/` at session start, so the deleted messages disappear from the generated code automatically.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor!: Declare is gone; the manifest is the contract

MyoGestic read four fields off DeclareReply: accepted, verdicts, and the two
channel orders. The orders are the manifest minus aliases, sorted by channel —
derivable by anyone holding the manifest, which every client fetches first. The
accept/refuse half was validation MyoGestic already does itself against that same
manifest, raising its own error for an address no capability carries.

That left one load-bearing effect, the control-pose mode flip, and Task 2 made
that follow the stream's presence instead.

So a renderer's contract is GetControlManifest and an LSL inlet. SetControl if it
wants discrete DOFs; SweepControl, SetPresentation and the recording RPCs remain
optional extras."
```

---

### Task 4: MyoGestic stops declaring

**Files:**
- Modify: `MyoGestic/myogestic/vhi/_control.py`
- Modify: `MyoGestic/myogestic/vhi/target.py`
- Test: `MyoGestic/tests/test_vhi_target.py`

**Interfaces:**
- Consumes: a VHI with no `Declare` (Task 3).
- Produces: `VhiTarget._negotiate_routed` and `_negotiate_by_name` resolve from `self.capabilities()` alone. `VhiControlClient` no longer has `declare` or `unimplemented`.

- [ ] **Step 1: Write the failing test**

Add to `MyoGestic/tests/test_vhi_target.py`:

```python
def test_a_target_binds_without_declaring():
    """The manifest is the whole contract. A client that cannot Declare still binds.

    Declare's reply was accepted/verdicts plus two channel orders. The orders are the
    manifest sorted by channel; the verdicts were validation this target already does
    against `by_address`, raising its own error for an address no capability carries.
    """
    class ManifestOnlyClient:
        """A renderer that serves GetControlManifest and nothing else."""

        def __init__(self, manifest):
            self.manifest = manifest

        def capabilities(self):
            return self.manifest

    outlet = FakeOutlet()
    target = VhiTarget(outlet, client=ManifestOnlyClient(MANIFEST))
    target.bind(_controls("index.flexion"))
    target.send({"index.flexion": 1.0}, {})
    assert outlet.last[2] == 1.0
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
uv run --extra dev pytest tests/test_vhi_target.py -q -k "without_declaring"
```

Expected: FAIL with `AttributeError: 'ManifestOnlyClient' object has no attribute 'declare'`.

- [ ] **Step 3: Drop the declare call from `_negotiate_routed`**

In `myogestic/vhi/target.py`, delete these lines from `_negotiate_routed`:

```python
        declaring = (
            controls
            if len(mine) == len(controls.dofs)
            else dataclasses.replace(
                controls,
                dofs={a: d for a, d in controls.dofs.items() if a in mine},
                routes={a: r for a, r in routes.items() if a in mine},
            )
        )
        reply = self._client.declare(declaring, client_name="myogestic", control_pose=pose)
        if reply is None:
            return False
        if not reply.accepted:
            refused = {v.name: v.message for v in reply.verdicts if not v.renderable}
            raise ValueError(
                f"this target declined part of the control space: {refused}. Rendering "
                f"only what it accepted would leave the rest looking like controls that "
                f"work and hold still."
            )
```

and replace with:

```python
        # No declaration: the manifest above is the contract. Every check the reply
        # carried is made below against `by_address` — an address this stream does not
        # carry raises there, naming the address, which is what a verdict said.
```

Delete the now-unused `pose = self._stream == "control_pose"` line if nothing else reads it (`grep -n "\bpose\b" myogestic/vhi/target.py`).

- [ ] **Step 4: Do the same in `_negotiate_by_name`**

That path used `reply.continuous_channel_order` for `order`. Replace the declare call and the `order` assignment with the manifest-derived equivalent:

```python
        capabilities = self.capabilities()
        self._answered = capabilities is not None
        if capabilities is None:
            return False
        wanted = (
            "MyoGestic_ControlPose" if self._stream == "control_pose" else "MyoGestic_Output"
        )
        order = tuple(
            cap.address
            for cap in sorted(
                (c for c in capabilities
                 if c.channel >= 0
                 and (not getattr(c, "stream_name", "") or c.stream_name == wanted)),
                key=lambda c: c.channel,
            )
        )
```

- [ ] **Step 5: Delete `declare` from the client**

In `myogestic/vhi/_control.py`, delete `VhiControlClient.declare`, the module-level `declare_request` helper, and the `self.unimplemented` attribute with every reference to it (`grep -rn "unimplemented" myogestic/`).

- [ ] **Step 6: Run the tests**

```bash
uv run ruff check .
pkill -9 -f "Godot.app"; sleep 2
uv run --extra dev pytest -q
```

Expected: ruff clean; the new test passes. Any other test that asserted on declare behaviour must be deleted, not weakened — its subject no longer exists.

- [ ] **Step 7: Verify live, against the real renderer**

```bash
nohup /Applications/Godot.app/Contents/MacOS/Godot --path /Users/oj98yqyk/code/Virtual-Hand-Interface > /tmp/vhi.log 2>&1 &
sleep 15
uv run --extra grpc python tools/verify_control_direction.py
```

Expected: exit 0. This is the gate that proves `+1` still flexes end to end over LSL, with no declaration anywhere in the path.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor!: bind from the manifest, without declaring

VhiTarget asked the renderer to confirm a layout it had already computed from the
manifest it fetched a line earlier. The reply's two channel orders are that
manifest sorted by channel; its verdicts duplicated the check this target makes
against by_address, which raises naming the address a capability does not carry.

So the negotiation is the manifest fetch. A renderer that serves
GetControlManifest and reads an LSL stream can now be driven."
```

---

### Task 5: The reference renderer

The point of the whole plan: show that the contract is small by writing something that satisfies it.

**Files:**
- Create: `MyoGestic/examples/synthetic/reference_renderer.py`
- Test: `MyoGestic/tests/test_reference_renderer.py`

**Interfaces:**
- Consumes: a `VhiTarget` that binds without declaring (Task 4).
- Produces: `ReferenceRenderer` — a class with `serve()`, `stop()`, and a `pose` attribute holding the last frame it rendered.

- [ ] **Step 1: Write the failing test**

Create `MyoGestic/tests/test_reference_renderer.py`:

```python
"""The reference renderer is the claim 'the contract is small', made executable."""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

RENDERER = (
    pathlib.Path(__file__).parent.parent
    / "examples" / "synthetic" / "reference_renderer.py"
)


@pytest.fixture(scope="module")
def renderer_module():
    pytest.importorskip("grpc")
    spec = importlib.util.spec_from_file_location("reference_renderer", RENDERER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_control_bus_drives_the_reference_renderer(renderer_module):
    """Serve a manifest, read a stream, get driven. No Declare in the path."""
    from myogestic.controls import connect_controls, load_control_map
    from myogestic.vhi import VhiTarget, virtual_hand

    renderer = renderer_module.ReferenceRenderer(port=50099)
    renderer.serve()
    try:
        vhi = virtual_hand(grpc_port=50099)
        client = vhi.control_client()
        target = VhiTarget(vhi.outlet(), client=client)
        control_map = load_control_map({"dofs": {"close": "vhi.prediction.index"}})
        bus = connect_controls(control_map, [target], hz=32)
        assert bus is not None, "the renderer's manifest did not resolve"

        deadline = time.time() + 10.0
        while time.time() < deadline and renderer.pose[2] < 0.9:
            bus.push({"close": 1.0})
            time.sleep(0.1)
        assert renderer.pose[2] == pytest.approx(1.0, abs=0.05), renderer.pose
        bus.stop()
        client.stop()
    finally:
        renderer.stop()
```

- [ ] **Step 2: Run it and watch it fail**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
uv run --extra grpc --extra dev pytest tests/test_reference_renderer.py -q
```

Expected: FAIL — `examples/synthetic/reference_renderer.py` does not exist.

- [ ] **Step 3: Write the renderer**

Create `MyoGestic/examples/synthetic/reference_renderer.py`:

```python
"""The smallest thing MyoGestic can drive.

Serve one RPC, read one stream. That is the whole contract — everything else in
`myogestic_vhi.proto` is an extra a renderer may offer and a client may use.

Run it, then point any control map at `vhi.prediction.*`:

    uv run --extra grpc python examples/synthetic/reference_renderer.py
"""

from __future__ import annotations

import threading
from concurrent import futures

import grpc
import numpy as np
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto import myogestic_vhi_pb2_grpc as pb2_grpc

#: What this renderer exports. The address is yours to name; its first segment is the
#: namespace, so `vhi.*` here means a map written for a Virtual Hand drives this too.
#: `channel` is the position on the wire — a channel *is* an address, and this table is
#: the only place that says so. `ControlCapability.channel` is field 11 and
#: `stream_name` field 10; both are required for a client to place a value.
ADDRESSES = [
    ("vhi.prediction.thumb.flexion", 0),
    ("vhi.prediction.thumb.abduction", 1),
    ("vhi.prediction.index", 2),
    ("vhi.prediction.middle", 3),
    ("vhi.prediction.ring", 4),
    ("vhi.prediction.little", 5),
]

POSE_WIDTH = 9


class ReferenceRenderer(pb2_grpc.VhiControlServicer):
    """A renderer in eighty lines. Holds the last pose it was sent."""

    def __init__(self, port: int = 50051, stream: str = "MyoGestic_Output") -> None:
        self.pose = np.zeros(POSE_WIDTH, dtype=np.float32)
        self._port = port
        self._stream = stream
        self._server: grpc.Server | None = None
        self._stop = threading.Event()

    # --- the one required RPC -------------------------------------------------

    def GetControlManifest(self, request, context):
        """What this renderer exports. The only thing a client must be able to ask."""
        manifest = pb2.ControlManifest(target_name="reference", vocabulary_version="1")
        for address, channel in ADDRESSES:
            manifest.capabilities.append(
                pb2.ControlCapability(
                    address=address,
                    kind=pb2.CONTINUOUS,
                    lo=-1.0,
                    hi=1.0,
                    rest=0.0,
                    channel=channel,
                    stream_name=self._stream,
                    description=f"{address}, signed and normalised",
                )
            )
        return manifest

    # --- lifecycle ------------------------------------------------------------

    def serve(self) -> None:
        """Start the gRPC server and the inlet reader."""
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        pb2_grpc.add_VhiControlServicer_to_server(self, self._server)
        self._server.add_insecure_port(f"127.0.0.1:{self._port}")
        self._server.start()
        threading.Thread(target=self._read, name="reference-inlet", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.stop(grace=None)

    def _read(self) -> None:
        """Read the pose stream. Positional: a channel is an address."""
        inlet = None
        while not self._stop.is_set():
            if inlet is None:
                found = [s for s in resolve_streams(timeout=1.0) if s.name == self._stream]
                if not found:
                    continue
                inlet = StreamInlet(found[0])
                inlet.open_stream()
                continue
            try:
                chunk, _ = inlet.pull_chunk(timeout=0.5)
                if chunk is not None and len(chunk):
                    self.pose = np.asarray(chunk[-1], dtype=np.float32)
            except Exception:
                inlet = None


if __name__ == "__main__":
    renderer = ReferenceRenderer()
    renderer.serve()
    print("reference renderer on 127.0.0.1:50051 — Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        renderer.stop()
```

- [ ] **Step 4: Run the test**

```bash
pkill -9 -f "Godot.app"; sleep 2
uv run --extra grpc --extra dev pytest tests/test_reference_renderer.py -q
```

Expected: PASS. `virtual_hand` takes `grpc_port=` (verified at `myogestic/vhi/interfaces.py:427`); the registry resolves explicit arguments before env vars and defaults, so this points the client at the reference renderer rather than a real VHI.

- [ ] **Step 5: Run the whole suite and lint**

```bash
uv run ruff check .
uv run --extra dev pytest -q
```

Expected: ruff clean, everything passes.

- [ ] **Step 6: Commit**

```bash
git add examples/synthetic/reference_renderer.py tests/test_reference_renderer.py
git commit -m "feat(examples): a renderer in eighty lines

The claim that a renderer's contract is small, made executable: serve
GetControlManifest, read MyoGestic_Output positionally, get driven by a real
ControlBus. The test pushes +1 and asserts the pose moved.

Everything else in the proto is an extra. This file is what a new renderer should
be started from — copy it, change ADDRESSES, render the numbers."
```

---

### Task 6: The guide

**Files:**
- Create: `MyoGestic/docs/how-to/build-a-renderer.md`
- Modify: `MyoGestic/properdocs.yml`
- Modify: `MyoGestic/docs/how-to/index.md`
- Modify: `MyoGestic/docs/how-to/add-a-target.md`

**Interfaces:**
- Consumes: `examples/synthetic/reference_renderer.py` (Task 5).
- Produces: nothing code depends on.

- [ ] **Step 1: Write the page**

Create `MyoGestic/docs/how-to/build-a-renderer.md`. It must contain, in this order:

1. **What a renderer is** — a separate application that MyoGestic drives, as opposed to a [target](../../how-to/add-a-target.md), which is the in-process object a `ControlBus` calls. One sentence each, with the link.
2. **The contract**, as a table stating exactly this:

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

3. **The whole renderer**, embedded from the example with a `--8<--` snippet include, matching how `docs/tutorials/emg-regression-with-vhi.md` embeds its blocks.
4. **The standard**, verbatim: values are `[-1, 1]`, `0` is rest, `+1` is the direction the DOF's name denotes. A fist is `[1, -1, 1, 1, 1, 1, 0, 0, 0]` — five flexions and an *ad*ducted thumb, because that is what a fist does with a thumb.
5. **The warning**, stated plainly: a backwards sign survives every test you would think to write, because a renderer and its own read-back agree whichever way they point. Check against something outside the loop — a person looking at the device. This repo shipped that bug and its own contract suite passed throughout.
6. **What changed**, so anyone holding an older renderer knows: `Declare` no longer exists; the manifest is the contract, and a control hand is driven by publishing to its stream rather than by asking permission.

- [ ] **Step 2: Add it to the nav**

In `properdocs.yml`, after the `Drive your own device` line:

```yaml
          - Build a renderer: how-to/build-a-renderer.md
```

In `docs/how-to/index.md`, after the `Drive your own device` bullet:

```markdown
- [Build a renderer](build-a-renderer.md) - a separate application MyoGestic drives, like the Virtual Hand: one RPC and a stream.
```

In `docs/how-to/add-a-target.md`, add to its "See also" list:

```markdown
- [Build a renderer](build-a-renderer.md) — for a separate application rather than an in-process object
```

- [ ] **Step 3: Build the docs**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
uv run --extra docs properdocs build 2>&1 | tail -3
```

Expected: builds, with no warning naming `build-a-renderer.md`.

- [ ] **Step 4: Run the doc tests**

```bash
uv run --extra dev pytest tests/test_docs.py -q
```

Expected: PASS. `tests/test_docs.py` parses every Python block in `docs/`, so a snippet include that points at a missing anchor fails here.

- [ ] **Step 5: Commit**

```bash
git add docs/how-to/build-a-renderer.md docs/how-to/index.md docs/how-to/add-a-target.md properdocs.yml
git commit -m "docs: how to build a renderer

The question this plan started from — how hard is it to make a new VHI — had no
answer anywhere. VHI's how-tos are about using VHI; MyoGestic's never mentioned
building one. A newcomer opened a nine-RPC proto next to a 4500-line Godot app and
drew the obvious conclusion.

Two RPCs and a socket, and now a page that says so with a working renderer in it."
```

---

## Self-Review

**Spec coverage.** The request was: make a new renderer easy, guide the user or their LLM, and stop having several ways to do one thing.

- *Easy* — Tasks 1–4 take the required contract from three RPCs to one by removing the handshake whose reply was derivable and whose only effect is now automatic.
- *Guide* — Task 5 is a working renderer under test; Task 6 is the page, with the contract as a table and the sign warning this repo earned.
- *One way* — Task 3 removes the second way to enter Stream mode (Declare's flag) leaving presence; Task 4 removes the second source of channel order (the reply) leaving the manifest.

**Known gaps, stated rather than hidden.**

- `_negotiate_by_name` in Task 4 Step 4 reconstructs `order` from capabilities. That code is written out, but it duplicates filtering `_negotiate_routed` also does — a later cleanup could share it. Not folded in here because it would widen a task that is already a wire change.
- Task 3 Step 3 deletes `ControlHandDriverMode` *conditionally*, on a grep. If `MovementConfigLoader` or the control panel still reads it, leave the enum and say so in the commit message.
- Task 5's test binds a real gRPC server on port 50099. If that port is busy the test fails loudly rather than skipping — deliberate; a silently skipped proof is worse than none.
- The reference renderer resolves LSL in a loop with a 1 s timeout. Single producer, single consumer, so it will not reproduce the resolve storm that panicked this machine — but do not raise its concurrency.

**Not covered, and deliberately.** The VHI-side docs (`docs/how-to/drive-from-myogestic.md`, `docs/concepts/grpc-control.md`) still describe `Declare`. Updating them belongs to whoever lands the VHI half; it is prose, not contract, and folding another repo's doc sweep into Task 3 would make one task span two doc sites.
