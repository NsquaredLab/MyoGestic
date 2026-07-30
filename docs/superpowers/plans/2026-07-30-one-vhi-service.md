# One VHI Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse VHI's two gRPC services into one, remove the word "canonical" from the protocol and both codebases, and delete the rig-units encoding so a control value has exactly one meaning.

**Architecture:** The proto is the source of truth and exists twice, byte-identical, in both repos. Every task edits the proto first, regenerates both sets of stubs, then updates the C# server and the Python client together. The semantic split between *controlling* the hand and *coordinating a recording* survives as two Python façades over one wire service — the boundary that is real, without a service boundary that buys nothing.

**Tech Stack:** protobuf 3 / gRPC, Python 3.13 + `grpc_tools`, C# / .NET on Godot 4, `uv` for Python, `dotnet build` for the renderer.

## Global Constraints

- **This is a wire break.** Both repos must ship together; there is no compatibility window and none is wanted. Approved by the maintainer on 2026-07-30.
- **The two proto copies must stay byte-identical**: `MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto` and `Virtual-Hand-Interface/proto/myogestic_vhi.proto`. Copy, never re-type.
- **The word "canonical" must not survive** in either repo's code, proto, docs, tool names or comments. The one exception is CHANGELOG entries describing past releases.
- **The word "raw", and rig units as a concept, must not survive** on the wire or in the client. `decode_pose` is out of scope — it reads archived *recordings*, not the wire.
- Python style: 4-space indent, double quotes, NumPy-style docstrings. `uv run ruff check .` is CI-enforced (pydocstyle `D` included).
- Tests: `uv run --extra dev pytest -q`. `tests/test_stream_lsl.py::test_stream_reconnect_swaps_buffers_atomically` is a known flake under full-suite load — it is not your change.
- Docs are executed: `tests/test_docs.py` runs Python blocks in `docs/` marked `<!--docs:run-->`. `uv run --locked --extra docs --extra grpc --extra serial properdocs build` must stay clean.
- Never add AI attribution to commits.
- **Naming, settled — use these exact strings:**

  | old | new |
  |---|---|
  | `service VhiCanonicalControl` + `service VhiTrainingAid` | `service VhiControl` (one) |
  | `myogestic_vhi_v2.proto` | `myogestic_vhi.proto` |
  | `VhiCanonicalClient` | `VhiControlClient` |
  | `VhiTrainingAidClient` | `VhiRecordingClient` |
  | `myogestic/vhi/_client_v2.py` | `myogestic/vhi/_control.py` |
  | `myogestic/vhi/_training.py` | `myogestic/vhi/_recording.py` |
  | `InterfaceSpec.canonical_client()` | `InterfaceSpec.control_client()` |
  | `InterfaceSpec.training_client()` | `InterfaceSpec.recording_client()` |
  | `StartTrainingProgram` | `StartRecordingTrajectory` |
  | `StopTrainingProgram` | `StopRecordingTrajectory` |
  | `GetTrainingState` | `GetRecordingSessionState` |
  | `TrainingAck` | `RecordingAck` |
  | `TrainingState` | `RecordingSessionState` |
  | `StartTrainingProgramRequest` | `StartRecordingTrajectoryRequest` |
  | `StopTrainingProgramRequest` | `StopRecordingTrajectoryRequest` |
  | `GetTrainingStateRequest` | `GetRecordingSessionStateRequest` |
  | `VhiCanonicalControlService.cs` + `VhiTrainingAidService.cs` | `VhiControlService.cs` (one) |
  | Python `start_program` / `stop_program` | `start_trajectory` / `stop_trajectory` |
  | `tools/verify_canonical_direction.py` | `tools/verify_control_direction.py` |

- **`SetRecordingSession` keeps its name.** It was already correct.

---

## Why the encoding field cannot simply be deleted

`DeclareRequest.control_pose_encoding` is doing **two** jobs today. Besides naming an encoding, `EncodingUnspecified` is the signal for *"I am not declaring the control-pose stream"* — and declaring nothing is what releases it. See `Virtual-Hand-Interface/src/VhiCanonicalControlService.cs:447`, `:506`, `:526`.

So the enum's deletion must be paired with an explicit replacement for the presence signal, or declaring will silently stop releasing the stream. Task 2 replaces it with `bool control_pose`.

`ControlCapability.encoding` and `DeclareReply.continuous_encoding` have no second job and are deleted outright.

---

## File Structure

**Virtual-Hand-Interface**
- Rename: `proto/myogestic_vhi_v2.proto` → `proto/myogestic_vhi.proto` — the shared contract
- Rename + merge: `src/VhiCanonicalControlService.cs` + `src/VhiTrainingAidService.cs` → `src/VhiControlService.cs` — one service implementation
- Modify: `src/GrpcControlServer.cs` — registers one service instead of two
- Modify: `src/ControlHandSkeleton.cs` — drop `ControlPoseCanonical`, fix the unconditional rest
- Modify: `VHI_godot.csproj` — the `<Protobuf Include=…>` path

**MyoGestic-main**
- Rename: `myogestic/vhi/_proto/myogestic_vhi_v2.proto` → `myogestic_vhi.proto` (+ the three generated files)
- Rename: `myogestic/vhi/_client_v2.py` → `myogestic/vhi/_control.py` — the control façade
- Rename: `myogestic/vhi/_training.py` → `myogestic/vhi/_recording.py` — the recording façade
- Modify: `myogestic/vhi/interfaces.py` — the two factories
- Modify: `myogestic/vhi/target.py` — delete every sign/encoding branch
- Modify: `myogestic/vhi/__init__.py` — the lazy re-exports
- Modify: `myogestic/widgets/vhi/panel.py`, `palette.py` — client type names
- Modify: 6 examples, `tools/`, `docs/`, `CHANGELOG.md`

---

### Task 1: Rename the proto file and the service, in both repos

**Files:**
- Rename: `Virtual-Hand-Interface/proto/myogestic_vhi_v2.proto` → `proto/myogestic_vhi.proto`
- Rename: `MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi_v2.proto` → `myogestic_vhi.proto`
- Modify: `Virtual-Hand-Interface/VHI_godot.csproj:27`

**Interfaces:**
- Consumes: nothing
- Produces: `service VhiControl` containing exactly the five RPCs it has today (`Declare`, `SetControl`, `SweepControl`, `SetPresentation`, `GetControlManifest`). `VhiTrainingAid` still exists at the end of this task; Task 3 folds it in.

- [ ] **Step 1: Rename both copies with git so history follows**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface
git mv proto/myogestic_vhi_v2.proto proto/myogestic_vhi.proto
cd /Users/oj98yqyk/code/MyoGestic-main
git mv myogestic/vhi/_proto/myogestic_vhi_v2.proto myogestic/vhi/_proto/myogestic_vhi.proto
```

- [ ] **Step 2: Rename the service in the VHI copy**

In `Virtual-Hand-Interface/proto/myogestic_vhi.proto`, line 29, change `service VhiCanonicalControl {` to `service VhiControl {`. In the comment block above it, replace every occurrence of "canonical" — the standard's units are now just "standard values", and a "canonical DOF" is a "control".

- [ ] **Step 3: Point the csproj at the new filename**

`VHI_godot.csproj:27` becomes:

```xml
    <Protobuf Include="proto/myogestic_vhi.proto" GrpcServices="Server" />
```

- [ ] **Step 4: Copy the proto to MyoGestic, byte-for-byte**

```bash
cp /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
   /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
diff -q /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
        /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
```

Expected: no output. Any output means the copies have diverged — fix before continuing.

- [ ] **Step 5: Commit both repos**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface && git add proto VHI_godot.csproj && \
  git commit -m "refactor!: one control service, and drop the version from the filename"
cd /Users/oj98yqyk/code/MyoGestic-main && cd /Users/oj98yqyk/code/MyoGestic-main && git add myogestic/vhi/_proto && \
  git commit -m "refactor!: one control service, and drop the version from the filename"
```

---

### Task 2: Delete the encoding enum, replacing the presence signal

**Files:**
- Modify: `Virtual-Hand-Interface/proto/myogestic_vhi.proto:258-278` (the enum), `:69-119` (`ControlCapability`), `:204-234` (`DeclareRequest`), `:280-314` (`DeclareReply`)

**Interfaces:**
- Consumes: `service VhiControl` from Task 1
- Produces: `DeclareRequest.control_pose` (`bool`), `DeclareReply.control_pose` (`bool`). `ContinuousEncoding`, `ControlCapability.encoding`, `DeclareRequest.control_pose_encoding`, `DeclareReply.continuous_encoding` and `DeclareReply.control_pose_encoding` no longer exist.

- [ ] **Step 1: Delete the enum**

Remove the whole `enum ContinuousEncoding { … }` block at `:258`, including its comment. There is one encoding now: a control value means what the control's name says, `+1` in the direction the name denotes.

- [ ] **Step 2: Delete the two fields that only named an encoding**

In `ControlCapability`, delete `ContinuousEncoding encoding = 8;`. In `DeclareReply`, delete `ContinuousEncoding continuous_encoding = 6;`. Do **not** renumber the remaining fields — field numbers are wire identity and reusing them later is a trap. Add `reserved 8;` to `ControlCapability` and `reserved 6;` to `DeclareReply`.

- [ ] **Step 3: Replace the presence signal with a bool**

In `DeclareRequest`, replace `ContinuousEncoding control_pose_encoding = 4;` with:

```proto
  // Whether this client also drives the control hand's pose stream. False releases it:
  // a client that stops declaring the stream gives it back, which is what lets a later
  // client take it. Separate from the DOF list because the two hands are separate.
  bool control_pose = 4;
```

In `DeclareReply`, replace `ContinuousEncoding control_pose_encoding = 10;` with `bool control_pose = 10;` and a comment saying it echoes what was granted.

- [ ] **Step 4: Copy to MyoGestic and verify identical**

```bash
cp /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
   /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
diff -q /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
        /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
```

Expected: no output.

- [ ] **Step 5: Commit both repos**

```bash
git -C /Users/oj98yqyk/code/Virtual-Hand-Interface add proto
git -C /Users/oj98yqyk/code/Virtual-Hand-Interface commit -m "refactor!: one encoding, so the wire no longer carries a sign convention"
git -C /Users/oj98yqyk/code/MyoGestic-main add myogestic/vhi/_proto
git -C /Users/oj98yqyk/code/MyoGestic-main commit -m "refactor!: one encoding, so the wire no longer carries a sign convention"
```

---

### Task 3: Fold the recording RPCs into the one service

**Files:**
- Modify: `Virtual-Hand-Interface/proto/myogestic_vhi.proto` — move the four RPCs, rename them and their messages, delete `service VhiTrainingAid`

**Interfaces:**
- Consumes: `service VhiControl` from Task 1
- Produces: `VhiControl` with nine RPCs. New names: `SetRecordingSession(SetRecordingSessionRequest) returns (RecordingAck)`, `StartRecordingTrajectory(StartRecordingTrajectoryRequest) returns (RecordingAck)`, `StopRecordingTrajectory(StopRecordingTrajectoryRequest) returns (RecordingAck)`, `GetRecordingSessionState(GetRecordingSessionStateRequest) returns (RecordingSessionState)`.

- [ ] **Step 1: Move the four RPCs into `VhiControl` under a comment banner**

Inside `service VhiControl`, after the existing RPCs, add:

```proto
  // --- recording session ---------------------------------------------------
  // Not control: these coordinate VHI's participation in a recording session that
  // something else owns. They live here because they drive the same hand through the
  // same state machine — a second service implied an independence the renderer does
  // not have, and the arbitration between them is already cross-cutting.

  // Mark a recording session active or finished. While active, VHI ignores its own
  // keyboard so the recording has a single movement source.
  rpc SetRecordingSession (SetRecordingSessionRequest) returns (RecordingAck);

  // Start cycling the control hand through a movement, so the recorded pose stream
  // sweeps a continuous range instead of snapping between held states. Refused if a
  // trajectory is already running.
  rpc StartRecordingTrajectory (StartRecordingTrajectoryRequest) returns (RecordingAck);

  // Stop the trajectory. Rests the hand only if one was running.
  rpc StopRecordingTrajectory (StopRecordingTrajectoryRequest) returns (RecordingAck);

  // Session state, plus the movement names a trajectory may use.
  rpc GetRecordingSessionState (GetRecordingSessionStateRequest) returns (RecordingSessionState);
```

- [ ] **Step 2: Delete `service VhiTrainingAid` and rename its messages**

Delete the `service VhiTrainingAid { … }` block at `:399` and the banner comment above it. Rename in place: `StartTrainingProgramRequest` → `StartRecordingTrajectoryRequest`, `StopTrainingProgramRequest` → `StopRecordingTrajectoryRequest`, `GetTrainingStateRequest` → `GetRecordingSessionStateRequest`, `TrainingAck` → `RecordingAck`, `TrainingState` → `RecordingSessionState`. Inside `RecordingSessionState`, rename the fields `program_running` → `trajectory_running` and `program_movement` → `trajectory_movement`, keeping their field numbers.

- [ ] **Step 3: Copy to MyoGestic and verify identical**

```bash
cp /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
   /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
diff -q /Users/oj98yqyk/code/Virtual-Hand-Interface/proto/myogestic_vhi.proto \
        /Users/oj98yqyk/code/MyoGestic-main/myogestic/vhi/_proto/myogestic_vhi.proto
```

- [ ] **Step 4: Commit both repos**

```bash
git -C /Users/oj98yqyk/code/Virtual-Hand-Interface add proto
git -C /Users/oj98yqyk/code/Virtual-Hand-Interface commit -m "refactor!: recording RPCs join the control service under recording names"
git -C /Users/oj98yqyk/code/MyoGestic-main add myogestic/vhi/_proto
git -C /Users/oj98yqyk/code/MyoGestic-main commit -m "refactor!: recording RPCs join the control service under recording names"
```

---

### Task 4: Regenerate the Python stubs

**Files:**
- Delete: `myogestic/vhi/_proto/myogestic_vhi_v2_pb2.py`, `_pb2.pyi`, `_pb2_grpc.py`
- Create: `myogestic/vhi/_proto/myogestic_vhi_pb2.py`, `_pb2.pyi`, `_pb2_grpc.py`

**Interfaces:**
- Consumes: the finished proto from Task 3
- Produces: `myogestic.vhi._proto.myogestic_vhi_pb2` and `…_pb2_grpc` with `VhiControlStub`.

- [ ] **Step 1: Regenerate**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
uv run --extra grpc python -m grpc_tools.protoc \
  -I myogestic/vhi/_proto \
  --python_out=myogestic/vhi/_proto \
  --pyi_out=myogestic/vhi/_proto \
  --grpc_python_out=myogestic/vhi/_proto \
  myogestic_vhi.proto
```

- [ ] **Step 2: Fix the generated import to be package-relative**

`grpc_tools` emits `import myogestic_vhi_pb2 as …`, which fails inside a package. The committed file uses a relative import — restore it:

```bash
python3 - <<'EOF'
import pathlib
p = pathlib.Path("myogestic/vhi/_proto/myogestic_vhi_pb2_grpc.py")
t = p.read_text()
t = t.replace("import myogestic_vhi_pb2 as", "from . import myogestic_vhi_pb2 as", 1)
p.write_text(t)
EOF
grep -n "^from \. import" myogestic/vhi/_proto/myogestic_vhi_pb2_grpc.py
```

Expected: one line, `from . import myogestic_vhi_pb2 as myogestic__vhi__pb2`.

- [ ] **Step 3: Remove the old generated files**

```bash
git rm myogestic/vhi/_proto/myogestic_vhi_v2_pb2.py \
       myogestic/vhi/_proto/myogestic_vhi_v2_pb2.pyi \
       myogestic/vhi/_proto/myogestic_vhi_v2_pb2_grpc.py
```

- [ ] **Step 4: Verify the stub imports and carries the new surface**

```bash
uv run --extra grpc python -c "
from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2, myogestic_vhi_pb2_grpc as rpc
assert hasattr(rpc, 'VhiControlStub')
assert not hasattr(rpc, 'VhiTrainingAidStub')
assert not hasattr(pb2, 'ContinuousEncoding')
assert 'control_pose' in pb2.DeclareRequest.DESCRIPTOR.fields_by_name
print('stub surface ok')
"
```

Expected: `stub surface ok`.

- [ ] **Step 5: Commit**

```bash
git add myogestic/vhi/_proto && git commit -m "chore: regenerate the stubs for the single service"
```

---

### Task 5: Merge the two C# services into one

**Files:**
- Create: `Virtual-Hand-Interface/src/VhiControlService.cs` (from the two existing files)
- Delete: `src/VhiCanonicalControlService.cs`, `src/VhiTrainingAidService.cs`
- Modify: `src/GrpcControlServer.cs:36,50`

**Interfaces:**
- Consumes: the regenerated C# stubs (built by `dotnet` from the proto)
- Produces: `VhiControlService : VhiControl.VhiControlBase` implementing all nine RPCs.

- [ ] **Step 1: Create the merged service**

`git mv src/VhiCanonicalControlService.cs src/VhiControlService.cs`, rename the class to `VhiControlService`, change its base to `VhiControl.VhiControlBase`, then move the four RPC override methods out of `VhiTrainingAidService.cs` into it verbatim, renaming each to its new RPC name and its ack/state types. Delete `src/VhiTrainingAidService.cs`. Rewrite the class doc-comment: it no longer contrasts itself with v1.

- [ ] **Step 2: Register one service**

In `GrpcControlServer.cs`, replace the two `MapGrpcService<…>()` registrations at `:36` and `:50` with a single `MapGrpcService<VhiControlService>()`.

- [ ] **Step 3: Build**

```bash
cd /Users/oj98yqyk/code/Virtual-Hand-Interface && dotnet build
```

Expected: build succeeds. Any reference to `ContinuousEncoding` or `ControlPoseCanonical` will fail here — that is Task 6.

- [ ] **Step 4: Commit**

```bash
git add src proto && git commit -m "refactor!: one service implementation"
```

---

### Task 6: Delete rig units from the renderer, and fix the unconditional rest

**Files:**
- Modify: `Virtual-Hand-Interface/src/ControlHandSkeleton.cs:488,501,546,551-560`
- Modify: `src/VhiControlService.cs` (the `ControlPoseEncoding` reads at old lines `:447,506,526,556,561`)

**Interfaces:**
- Consumes: `bool control_pose` from Task 2
- Produces: a renderer with no encoding concept; `StopRecordingTrajectory` that rests only when a trajectory was running.

- [ ] **Step 1: Delete the `ControlPoseCanonical` property and its writes**

Remove the property at `:488`, the assignment at `:501`, and the reset at `:546`. The control-pose stream is always in standard values now, so `ToCanonical`-style conversion is unconditional. Rename any `canonical`-named local, method or comment while you are in the file (`ToCanonical` → `ToStandard`, `CanonicalPose` → `StandardPose`).

- [ ] **Step 2: Switch the declare path to the bool**

In `VhiControlService.cs`, every `request.ControlPoseEncoding == ContinuousEncoding.EncodingUnspecified` becomes `!request.ControlPose`, and `!= …EncodingUnspecified` becomes `request.ControlPose`. The reply assignment becomes `reply.ControlPose = true;`.

- [ ] **Step 3: Rest only when a trajectory was running**

`ControlHandSkeleton.cs:551` currently rests unconditionally, which erases a held state set through `SetControl` whenever a teardown path calls stop defensively. Guard it:

```csharp
	public void StopRecordingTrajectory()
	{
		// Rest only if a trajectory was actually running. Teardown paths call this
		// without knowing, and resting regardless erased a held state the control
		// path had set — the caller asked to stop a trajectory, not to move the hand.
		bool wasRunning = TrainingProgramActive;
		TrainingProgramActive = false;
		TrainingProgramMovement = "";
		if (!wasRunning)
			return;
		// A trajectory stopped mid-cycle would otherwise leave the hand holding a
		// half-flexed pose, and the recording that follows would start from somewhere
		// arbitrary.
		SetMovement("Rest", false);
	}
```

Rename `TrainingProgramActive` → `RecordingTrajectoryActive` and `TrainingProgramMovement` → `RecordingTrajectoryMovement` throughout, including the read in the discrete-control refusal.

- [ ] **Step 4: Build and smoke-test by hand**

```bash
dotnet build && /Applications/Godot.app/Contents/MacOS/Godot --path /Users/oj98yqyk/code/Virtual-Hand-Interface
```

Expected: VHI starts and prints its usual startup log. Leave it running for Task 9.

- [ ] **Step 5: Commit**

```bash
git add src && git commit -m "fix!: one encoding, and stop resting a hand no trajectory was moving"
```

---

### Task 7: Rename the Python clients and delete the sign machinery

**Files:**
- Rename: `myogestic/vhi/_client_v2.py` → `myogestic/vhi/_control.py`
- Rename: `myogestic/vhi/_training.py` → `myogestic/vhi/_recording.py`
- Modify: `myogestic/vhi/target.py:35,424,502,514,576`, `myogestic/vhi/interfaces.py:167,194`, `myogestic/vhi/__init__.py`
- Test: `tests/test_vhi_target.py`, `tests/test_interfaces.py`

**Interfaces:**
- Consumes: `myogestic_vhi_pb2_grpc.VhiControlStub` from Task 4
- Produces: `VhiControlClient` (methods unchanged except `set_control`, `capabilities`, `declare`, `sweep`, `stop`), `VhiRecordingClient` with `set_recording_session`, `start_trajectory`, `stop_trajectory`, `state`, `available_movements`, `stop`. `InterfaceSpec.control_client()` and `InterfaceSpec.recording_client()`.

- [ ] **Step 1: Rename the modules and classes**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
git mv myogestic/vhi/_client_v2.py myogestic/vhi/_control.py
git mv myogestic/vhi/_training.py myogestic/vhi/_recording.py
```

In `_control.py`, rename `VhiCanonicalClient` → `VhiControlClient` and point the stub at `VhiControlStub`. In `_recording.py`, rename `VhiTrainingAidClient` → `VhiRecordingClient`, point it at the same `VhiControlStub`, and rename `start_program` → `start_trajectory`, `stop_program` → `stop_trajectory`.

- [ ] **Step 2: Delete the sign machinery in `target.py`**

Remove `_ENCODING_CANONICAL` / `_ENCODING_NEGATED` at `:35`, the `sign` computation at `:424`, the `encoding not in (…)` refusal at `:502`, the `_negate` assignment at `:514`, the `_negate` slot, and the `sign = -1.0 if self._negate else 1.0` at `:576`. A value goes out as it came in. The `_routed` slot tuple loses its `sign` element — update its construction and every unpack.

- [ ] **Step 3: Write the failing test for the deleted sign machinery**

`tests/test_vhi_target.py` already has `FakeOutlet` (records frames pushed to the wire),
`FakeReply` and `FakeClient` (a duck-typed renderer). Delete `UNSPECIFIED, CANONICAL,
NEGATED` and both `*_encoding` fields from `FakeReply` — the reply no longer carries them —
then add:

```python
def test_a_value_reaches_the_wire_with_the_sign_it_was_given():
    """There is one encoding now, so nothing may flip a value on the way out."""
    outlet = FakeOutlet()
    controls = build_controls(["index.flexion"])
    target = VhiTarget(outlet, client=FakeClient(FakeReply(
        continuous_channel_order=("index.flexion",),
    )))
    target.bind(controls)
    target.send({"index.flexion": 1.0}, {})

    assert outlet.last[0] == pytest.approx(1.0), "the value was negated on the way out"

    target.send({"index.flexion": -1.0}, {})
    assert outlet.last[0] == pytest.approx(-1.0)
```

- [ ] **Step 4: Run it**

Run: `uv run --extra dev --extra grpc pytest tests/test_vhi_target.py -q`
Expected: PASS once Step 2 is complete. Before Step 2 it fails at import or at the
`FakeReply(...)` call, because the encoding fields still exist.

- [ ] **Step 5: Rename the two factories**

In `interfaces.py`, `canonical_client()` → `control_client()` at `:167` and `training_client()` → `recording_client()` at `:194`, with their docstrings and `>>>` Examples updated. In `myogestic/vhi/__init__.py`, update `__all__` and the lazy `__getattr__` branches to the new class names.

- [ ] **Step 6: Run the full suite and ruff**

```bash
uv run --extra dev pytest -q && uv run ruff check .
```

Expected: only the known `test_stream_lsl` flake.

- [ ] **Step 7: Commit**

```bash
git add myogestic/vhi tests/test_vhi_target.py tests/test_interfaces.py && \
  git commit -m "refactor!: VhiControlClient and VhiRecordingClient, and no sign convention"
```

---

### Task 8: Sweep the word out of examples, tools, widgets and docs

**Files:**
- Modify: `examples/synthetic/emg_classification.py`, `emg_classification_grpc.py`, `emg_regression.py`, `emg_regression_raulnet.py`, `emg_32ch_multi_model.py`, `emg_popout_layout.py`, `vhi_control_hand.py`, `control_map_studio.py`
- Modify: `myogestic/widgets/vhi/panel.py`, `palette.py`, `control_map_editor.py`
- Rename: `tools/verify_canonical_direction.py` → `tools/verify_control_direction.py`; `tools/inspect_canonical_control.py` → `tools/inspect_control.py`
- Modify: `tests/test_verify_canonical_direction.py` → `tests/test_verify_control_direction.py`
- Modify: `docs/api/controls.md`, `docs/how-to/integrate-vhi.md`, `docs/concepts/*.md`, `docs/tutorials/*.md`, `myogestic/controls.py`, `CHANGELOG.md`, `.vscode/launch.json`

**Interfaces:**
- Consumes: everything from Task 7
- Produces: zero occurrences of "canonical" outside historical CHANGELOG entries.

- [ ] **Step 1: Rename the call sites mechanically**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
git grep -l "canonical_client\|VhiCanonicalClient\|training_client\|VhiTrainingAidClient\|start_program\|stop_program" \
  -- '*.py' '*.md' '*.json' | while read -r f; do
  sed -i '' \
    -e 's/canonical_client/control_client/g' \
    -e 's/VhiCanonicalClient/VhiControlClient/g' \
    -e 's/training_client/recording_client/g' \
    -e 's/VhiTrainingAidClient/VhiRecordingClient/g' \
    -e 's/start_program/start_trajectory/g' \
    -e 's/stop_program/stop_trajectory/g' \
    -e 's/vhi_canonical/vhi_control/g' \
    -e 's/training_aid/recording/g' "$f"
done
```

- [ ] **Step 2: Rename the two tools and their test**

```bash
git mv tools/verify_canonical_direction.py tools/verify_control_direction.py
git mv tests/test_verify_canonical_direction.py tests/test_verify_control_direction.py
git mv tools/inspect_canonical_control.py tools/inspect_control.py
git grep -l "verify_canonical_direction\|inspect_canonical_control" | while read -r f; do
  sed -i '' -e 's/verify_canonical_direction/verify_control_direction/g' \
            -e 's/inspect_canonical_control/inspect_control/g' "$f"
done
```

`.vscode/launch.json` references both by path — check it changed.

- [ ] **Step 3: Rewrite the remaining prose by hand**

`sed` cannot fix sentences. Read every remaining hit and rewrite it:

```bash
git grep -n "canonical\|Canonical\|CANONICAL" -- ':!CHANGELOG.md'
```

Replace "canonical value" with "control value", "the canonical standard" with "the control standard", "a canonical DOF" with "a control". Where a sentence exists only to contrast with rig units, delete the sentence — there is nothing to contrast with any more.

- [ ] **Step 4: Verify nothing survives**

```bash
test -z "$(git grep -i canonical -- ':!CHANGELOG.md')" && echo "clean" || git grep -in canonical -- ':!CHANGELOG.md'
```

Expected: `clean`.

- [ ] **Step 5: Run everything**

```bash
uv run --extra dev pytest -q
uv run ruff check .
uv run --locked --extra docs --extra grpc --extra serial properdocs build
```

Expected: only the known flake; ruff clean; docs build with no unresolved references.

- [ ] **Step 6: Commit**

```bash
git add myogestic examples tools tests docs .vscode && \
  git commit -m "refactor!: say control, not canonical"
```

---

### Task 9: Prove it end to end against the running renderer

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything
- Produces: a verified release note.

- [ ] **Step 1: Start the renderer**

```bash
/Applications/Godot.app/Contents/MacOS/Godot --path /Users/oj98yqyk/code/Virtual-Hand-Interface &
```

- [ ] **Step 2: Run the direction gate**

```bash
cd /Users/oj98yqyk/code/MyoGestic-main
uv run --extra grpc python tools/verify_control_direction.py
```

Expected: exit 0 and `✓ +1 flexes, reads back as +1, and does so identically under every declaration`. A non-zero exit means the encoding deletion changed the sign — stop and fix before continuing.

- [ ] **Step 3: Prove the recording RPCs still work on the merged service**

```bash
uv run --extra grpc python -c "
from myogestic.vhi import virtual_hand
r = virtual_hand().recording_client()
assert r.set_recording_session(True), 'the session gate did not apply'
print('movements:', r.available_movements()[:5])
assert r.stop_trajectory(), 'stop refused'
assert r.set_recording_session(False)
r.stop()
print('recording RPCs ok on the single service')
"
```

Expected: `recording RPCs ok on the single service`.

- [ ] **Step 4: Prove the unconditional-rest fix**

```bash
uv run --extra grpc python -c "
from myogestic.vhi import virtual_hand
v = virtual_hand(); c = v.control_client(); r = v.recording_client()
caps = {x.address: x for x in (c.capabilities() or [])}
held = next(a for a, x in caps.items() if x.kind == 'discrete')
c.set_control(discrete={held: [s for s in caps[held].states if s != caps[held].rest_state][0]})
import time; time.sleep(0.5)
r.stop_trajectory()          # no trajectory is running: must not move the hand
st = r.state(); print('trajectory_running:', st.trajectory_running)
c.stop(); r.stop()
"
```

Expected: `trajectory_running: False`, and the hand visibly stays in its held state rather than snapping to rest.

- [ ] **Step 5: Kill the renderer**

```bash
pkill -f "Godot --path.*Virtual-Hand-Interface"
```

- [ ] **Step 6: Write the CHANGELOG entry and commit**

Add one bullet under `## [Unreleased]` → `### Changed (breaking)` naming all four breaks: one service, recording RPC names, no encoding field, renamed clients. State that MyoGestic and VHI must be updated together.

```bash
git add CHANGELOG.md && git commit -m "docs: changelog for the single-service break"
```

---

## Self-Review

**Spec coverage.** Rename off "canonical" — Tasks 1, 7, 8. Fold the aid in — Tasks 3, 5. Delete rig units — Tasks 2, 6, 7. Fix the unconditional rest — Task 6. Both repos in lockstep — every proto task copies and diffs. Verification — Task 9.

**Known gaps, deliberately out of scope.** `decode_pose` and `LEGACY_POSE_DOFS` stay: they read archived recordings, which are in rig units and cannot be re-recorded. The session gate's over-promise (`SessionActive` only stops the local keyboard, not other gRPC clients) is left alone — fixing it means deciding an ownership policy, which is a separate decision. `GetRecordingSessionState` still leaks general control-hand discovery, which `palette.py:166` depends on; moving that to `GetControlManifest` is a follow-up.

**Ordering risk.** Between Task 3 and Task 6 the renderer will not build, and between Task 4 and Task 7 the Python client will not import. That is expected: this is one release, not nine. Do not ship a partial sequence.
