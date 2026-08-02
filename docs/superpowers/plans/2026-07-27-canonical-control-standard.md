# Canonical control standard — TOML-configured DOFs, target adapters, VHI v2

**Status: FROZEN 2026-07-27. Approved architecture; nothing implemented. Do not write
code for this until explicitly asked.**

Python blocks below are design sketches, not runnable code, so they carry
`<!--docs:skip-->` for the `tests/test_docs.py` harness.

---

## Context

MyoGestic apps currently hand-roll their output mapping. `examples/synthetic/emg_regression.py`
expands a 5-DOF regression into a 9-float vector with a literal negate at `:220` whose
inverse (`np.abs`, `:166`) lives in a different function; `emg_classification_grpc.py`
maps class indices to VHI movement names by hand; four separate examples carry
hand-written 9-float pose tables. `CLASSES` simultaneously means UI labels, recording
metadata, model label space, and VHI movement identifiers.

This plan replaces that with a **canonical, application-independent control standard**
that MyoGestic owns. VHI, keyboard, cursor and future applications become *adapters*.
Users configure DOFs in TOML without editing prediction code.

Two things are deliberately **not** in scope of the canonical layer: legacy VHI's
positional wire layout, and any licensing concern.

---

## 1. The canonical standard

New module `myogestic/controls.py`. Imports numpy, stdlib, and
`myogestic.outputs.edge_trigger` / `myogestic.outputs.filters` **by submodule** — never
`myogestic.outputs`, which re-exports `LSLOutlet` and pulls `mne_lsl`, breaking the
browser path. Zero VHI concepts, zero transport.

A **DOF** is one named thing a user controls. A **control** is one `[simultaneous]`
line. A **target** renders some DOFs. That is the whole standard.

<!--docs:skip-->
```python
STANDARD_VERSION = "1"        # versions the vocabulary format, NOT the archive layout

@dataclass(frozen=True, slots=True)
class Continuous:
    """A signed, normalized DOF. `+1` is the direction the name denotes."""
    name: str
    lo: float = -1.0
    hi: float = 1.0
    rest: float = 0.0
    label: str = ""

@dataclass(frozen=True, slots=True)
class Discrete:
    """A DOF holding exactly one of `states`. `rest` is the neutral state."""
    name: str
    states: tuple[str, ...]
    rest: str
    debounce_s: float = 0.0
    label: str = ""

Dof = Continuous | Discrete     # tagged union, no base class, exhaustive under `ty`

@dataclass(frozen=True, slots=True)
class ControlSet:
    """A validated configuration. `dofs` insertion order is the canonical wire order."""
    dofs: Mapping[str, Dof]
    simultaneous: Mapping[str, tuple[str, ...]]
    standard_version: str = STANDARD_VERSION
    # .continuous  .discrete  .n_concurrent  .channel_labels()  .as_dict()

def load_dofs(config: Mapping) -> ControlSet: ...
def substitute_rest(controls: ControlSet, values: Mapping) -> dict: ...
def clip(controls: ControlSet, values: Mapping) -> tuple[dict, tuple[str, ...]]: ...
def encode(controls: ControlSet, values: Mapping) -> np.ndarray: ...
def decode(controls: ControlSet, frame: Sequence[float]) -> dict[str, float]: ...
```

`encode`/`decode` derived from one declaration is what **deletes `np.abs()` from
training**: today the flip and its lossy inverse live in two independently-editable
places.

`load_dofs` takes a **Mapping, never a path**, so `tomllib` never enters `myogestic/`.
That is what keeps `docs/concepts/design-principles.md` rule 1 ("No config files")
satisfied: the library accepts a dict of experiment parameters whose provenance is the
user's business. No default path, no search order, no filename convention.

### Naming rule

Grammar: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`. Segment 1 is what is controlled
(`hand`, `wrist`, `cursor`, `chair`, `gripper`); segment 2+ is the function.

> **A continuous canonical name denotes the `+1` direction, and registers its `-1`
> antonym. If the antonym is not the plain opposite of the name, use an axis name.**

| use | avoid | why |
|---|---|---|
| `thumb.flexion` (−1 = extension) | | standard anatomical axis |
| `index.flexion`, `middle.flexion`, `ring.flexion`, `little.flexion` | | |
| `thumb.abduction` (−1 = adduction) | | |
| `hand.grip` (−1 = open) | `hand.close` | "close" is an action name doing an axis's job; `-1` would mean a different action, not "less closing" |
| `wrist.pronation` (−1 = supination) | `wrist.rotation` | "rotation" has no polarity; VHI's own vocabulary has Pronate/Supinate as separate movements |

Names are **not** validated against a list. A closed vocabulary is a registry
(design-principles rule 1) and would gate growth on a library release. The recommended
vocabulary is a docs page; disagreement surfaces as a machine-visible handshake result,
never as a silently wrong render.

---

## 2. The TOML

Mapping-first: one line per DOF, no boilerplate for normal controls.

```toml
[dofs]
"index.flexion"    = "continuous"                                 # [-1,1], rest 0
"thumb.flexion"    = "continuous"
"wrist.pronation"  = "continuous"
"hand.grasp"       = ["rest", "fist", "pinch"]                    # array => discrete
"grip.force"       = { kind = "continuous", range = [0.0, 1.0] }  # exceptional: unipolar

[simultaneous]
proportional = ["index.flexion", "thumb.flexion"]
grip         = ["hand.grasp"]
```

The simplest complete config is **one line**: `[dofs]` plus `"hand.grip" = "continuous"`.
It names no target identifier — no channel index, no `9`, no `-1`, no `"Fist"`. Point it
at a keyboard and the file does not change.

Loading is user code; `tomllib` is stdlib on the `>=3.12` floor:

<!--docs:skip-->
```python
CONTROLS = load_dofs(tomllib.loads(Path("controls.toml").read_text()))
```

### Value dispatch and its three parse hazards

`str | list | inline-table`, verified unambiguous against stdlib `tomllib`. Each hazard
below was confirmed by actually parsing it, and each needs a **named** error:

| hazard | what TOML does | required error |
|---|---|---|
| `"grip.force" = [0.0, 1.0]` | parses as **discrete with states `0.0`, `1.0`** — users will write this meaning a range, because that literal *is* the escalation form | *"arrays declare discrete states (strings); for a custom range write `{ kind = "continuous", range = [...] }`"* |
| `hand.grip = "continuous"` (quotes forgotten) | yields `{"hand": {"grip": ...}}` — a dict **structurally identical to the escalation form**, and it coexists with a quoted `"hand.grip"` **with no duplicate-key error**: two DOFs, one silently lost | a dict value carrying no key from `{kind, range, rest, states, debounce_s}` is a missing-quotes error |
| `["fist", "rest"]` | element 0 silently becomes the rest state | error if a state named `rest` appears at a non-zero index |

Inline tables cannot span lines in TOML 1.0, so a long escalation is one long line.
Accepted; document it.

Validation **accumulates every fault and raises once**, naming the offending key and
what to write. Voice follows `myogestic/outputs/filters.py:302`
(`Unknown filter {name!r}. Choose: ...`).

---

## 3. Continuous vs discrete

| | continuous | discrete |
|---|---|---|
| runtime value | `float` | `str` (a state name) |
| domain | `range = [lo, hi]`, default `[-1, 1]` | `states = [...]` |
| neutral | `rest`, default `0.0`, `lo <= rest <= hi` | `rest`, required, ∈ `states` |
| transport | one **labelled** LSL channel | one unary RPC / key event per edge |
| delivery | frame every tick, latest-wins | **edge only**, debounced |
| debounce | none (use `smoothing=`) | `debounce_s` seconds, converted at the bus |
| non-finite in | → declared `rest` | n/a |
| out of domain | clamped to declared range, counted + logged once per DOF | snapped to `rest` |
| events | n/a | **not expressible** — held state only |

Range shapes are constrained to `[-h, h]`, `[0, h]` or `[-h, 0]`, which guarantees
`rest` is expressible. This rejects `[-0.6, 1.0]`, which would park rest off-centre.

**No `unit` field.** With `[-1, 1]` mandated for every continuous DOF, `unit` is a
tautology and every `accept()` check would be `unit == "normalized"`. Targets own their
native units: px/s in `CursorTarget`'s constructor, degrees in a renderer's own gain
table. Honest cost: `[dofs]` no longer describes physical behaviour, so target-local
gain must be recorded in session provenance for a reproducible study. Upside: one DOF
can drive two targets at two gains.

**Discrete DOFs are never re-expressed as one-way regression targets.** Where a
regression example needs a directional target it uses a deliberate signed label
convention (`-1` rest→extension, `+1` rest→flexion, `0` rest) recorded in the session's
`control_space`, so the sign is declared rather than implied by a magnitude. This retires
`emg_regression.py:185`'s `np.ones(5)` / `np.zeros(5)`, which cannot express a negative
half at all.

---

## 4. `ControlBus` — the safety order

<!--docs:skip-->
```python
class ControlBus:
    """Sanitise once, fan out to every target. Owns the safety ORDER and the debounce.

    User-constructed and user-owned like every Output (`outputs/base.py:56-58`);
    register `stop` with `app.cleanup_hooks`.
    """
```

Order, and it is not optional:

```
substitute_rest -> clip to declared range -> smooth -> re-substitute rest
                -> CLIP AGAIN -> encode -> fan out
```

- `substitute_rest` first, because `np.clip(nan, lo, hi) == nan` and one NaN poisons
  `OneEuroFilter._x_prev` permanently (`filters.py:246`).
- **The final clip is safety-critical, not cosmetic.** With a unipolar DOF where
  `lo == rest == 0`, filter undershoot on a `1 -> 0` fall goes below `lo`, which under a
  signed encoder is a **sign flip into a direction the DOF declares does not exist**,
  rendered as real motion. Note what a signed range removes: the old
  `np.clip(pred, 0, 1)` at `emg_regression.py:214` was an *accidental sign-error net*.
- **Never raises on the predict thread — it fails to rest.** A raise there is logged
  with a full traceback on *every* tick, undeduped (`ml/pipeline.py:288-291`): at
  `predict_hz = 50` that is 50 tracebacks a second into a self-erasing 500-line log.
- `stop()` **delivers rest before stopping targets.**

### Zero-crossing dither — tunable, no default

Signed ranges put rest *interior*, so EMG noise around 0 chatters a bipolar DOF across
zero and produces rapid direction reversal on a real actuator. This ships as
`ControlBus(..., dead_zone=None, hysteresis=None)` with **no invented default** and a
documented measurement procedure.

```
# ponytail: no default until measured on real EMG. A universal constant here would be
# a guess dressed as a safety feature; the physical world needs tuning a minimal
# model cannot see.
```

---

## 5. The adapter protocol

Name-keyed, not positional — positional order is a wire fact that stays private to the
LSL target.

<!--docs:skip-->
```python
class Target(Protocol):
    """Render some canonical DOFs. One protocol for VHI, keyboard, cursor, anything."""

    def bind(self, controls: ControlSet) -> None:
        """Synchronous, offline validation. MAY raise — called before any frame exists."""

    def send(self, values: Mapping[str, float], changed: Mapping[str, str]) -> None:
        """Actuate one tick. Called on the predict thread."""

    def stop(self) -> None:
        """Release what this target owns. Idempotent."""
```

`bind()` is synchronous and may raise. Any **network** handshake is a retried,
**re-entrant** background worker — because VHI is launched and stopped by
`imgui.button` at `myogestic/widgets/panels/process_launcher.py:242,248`, so a
once-at-startup handshake is wrong at any call site.

New targets need no core change: `targets=(...)` is a typed constructor argument, not a
registration — no decorator, no import-time side effect, nothing global-mutable.
Keyboard and cursor live in `examples/`, not the library.

---

## 6. VHI v2 — the new contract

The vocabulary arrow **reverses**. Today `StateReply.available_movements` is
discovery-only, so MyoGestic must conform — the standing chore documented at
`emg_classification_grpc.py:62`. In v2, MyoGestic *declares* and VHI reports what it
cannot render.

Plane split by marginal cost:

| plane | wire | cost |
|---|---|---|
| declaration / handshake | new unary `Declare` | once; latency irrelevant |
| continuous per-tick | existing LSL outlet + channel names/units/`source_id` | **zero** — `<desc>` XML, fetched once at inlet open |
| discrete edges | unary `SetControl(dof, state)`, canonical names verbatim | one RPC per edge |

```proto
package myogestic.vhi.v2;      // the package IS the major-version handshake: gRPC routes
                               // on the full method name, so v1 and v2 coexist on one port
service VhiControl {
  rpc Declare      (DeclareRequest)      returns (DeclareReply);
  rpc SetControl   (SetControlRequest)   returns (CommandAck);
  rpc SweepControl (SweepControlRequest) returns (CommandAck);  // training-target generation
  rpc SetFrozen    (SetFrozenRequest)    returns (CommandAck);
  rpc SetChirality (SetChiralityRequest) returns (CommandAck);
  rpc SetSmoothing (SetSmoothingRequest) returns (CommandAck);
  rpc GetState     (GetStateRequest)     returns (StateReply);
}

enum Kind { KIND_UNSPECIFIED = 0; CONTINUOUS = 1; DISCRETE = 2; }

message ControlSpec {
  string name = 1;            // canonical, e.g. "index.flexion". NOT a VHI identifier.
  Kind   kind = 2;
  float  lo = 3; float hi = 4; float rest = 5;   // clamp to THIS, never a global rail
  uint32 lsl_channel = 6;     // equals declaration order; sent explicitly so a reordered
                              // config cannot silently re-map channels
  repeated string states = 7; // DISCRETE
  string rest_state = 8;      // DISCRETE. states[0] is not special.
  string label = 9;
}

message DeclareRequest {
  string standard_version = 1;  string client = 2;
  string lsl_stream_name = 3;   string lsl_source_id = 4;  float lsl_hz = 5;
  repeated ControlSpec  controls = 6;
  repeated ControlGroup simultaneous = 7;   // advisory; VHI MUST NOT make these exclusive
}

message DeclareReply {
  bool applied = 1;  string standard_version = 2;
  repeated string unsupported = 3;         // no renderer -> client HOLDS these at rest
  repeated string unsupported_states = 4;  repeated string clamped = 5;
  string message = 6;  string vhi_version = 7;
}
```

`SweepControl` drives a named DOF through its declared range so VHI's own kinematics
become a regression target; it absorbs v1's `SetMovementRequest.cycle` and `SetSpeed`.
Its acceptance test must verify **direction**, not just magnitude — four pose tables in
this repo already had the sign wrong, which is proof the team makes exactly this mistake.

### VHI-side implementation notes (verified in the VHI checkout)

- `src/VhiControlService.cs` is a clean `VhiControl.VhiControlBase` subclass with 8
  `public override Task<...>` methods. Registering a v2 service class alongside is
  trivial.
- `src/LSLWrapper.cs:333 SetChannelLabels` already writes `<channel><label>` into
  StreamInfo `<desc>`. There is **no reader** — v2 needs the `GetChannelLabels`
  counterpart, and the `get_Description` reflection plumbing is already there.
- `src/PredictedHandSkeleton.cs:184` guards `currentData.Count >= 9`. v2 either keeps
  9-wide frames or relaxes that guard.
- Movements are data-driven (`MovementConfigLoader` + JSON), not hardcoded, which suits
  a declared vocabulary.

---

## 7. The verified legacy channel map

Read from the VHI source at `/Users/oj98yqyk/code/Virtual-Hand-Interface`
(`src/PredictedHandSkeleton.cs:216-239`, `src/ControlHandSkeleton.cs:308-312`). Both
consumers read **only `currentData[0]`..`[5]`**.

| wire ch | what VHI actually does | canonical name |
|---|---|---|
| 0 | **thumb flexion** — bones 1/2/3 X axis, gains −45/−55/−80 | `thumb.flexion` |
| 1 | **thumb abduction** — bones 1/2/3 Z axis, gains +30/−35/0 | `thumb.abduction` |
| 2 | index flexion — bones 4,5,6 | `index.flexion` |
| 3 | middle flexion — bones 7,8,9 | `middle.flexion` |
| 4 | ring flexion — bones 10,11,12 | `ring.flexion` |
| 5 | pinky flexion — bones 13,14,15 | `little.flexion` |
| **6, 7, 8** | **never read by any consumer** | — nothing |

**`docs/how-to/integrate-vhi.md:78-95` is wrong** — it names ch0 "Thumb rotation",
ch1 "Thumb flexion", ch6-8 "Wrist (3 axes)". There are no wrist channels.
`VHI_DOF_INDICES = [0,2,3,4,5]` (`emg_regression.py:56`) is correct as *indices* (five
digit flexions, skipping thumb abduction) while its `WristRot` comment is wrong, as is
`emg_regression_raulnet.py:77`.

Two consequences:

1. **The positive half renders.** The receive path is
   `currentData = GetReceivedDataPredicted()` -> `Count >= 9` guard ->
   `SetBoneRotation(bone, currentData[i] * gain, ...)`. A pure linear multiply with **no
   clamping**. Flexion gains are negative, so legacy `-1` -> `+85°` = flexion and `+1`
   simply rotates the other way. The positive half is absent from the recordings because
   the operator never extended, **not** because VHI cannot render it. The write bridge
   therefore needs **no refusal and no clamping** on channels 0-5.
2. Channels 6-8 are **dead on both ends**, which is the real reason they are exactly
   `0.0` in all 6904 recorded samples.

---

## 8. Migration — the bridge is four artefacts; two get built

| | artefact | verdict |
|---|---|---|
| **B1** | legacy 9-ch recordings -> canonical | **BUILD, permanent** (~10 lines) |
| **B2** | canonical -> legacy 9-ch pose + `SetMovement` | **BUILD, delete-dated** one release after v2 |
| **B3** | permanent dual-stack VHI | **NO** — one-release coexistence instead |
| **B4** | trained-model translation | **NO** — retrain; add provenance forward |

<!--docs:skip-->
```python
_LEGACY = ("thumb.flexion", "thumb.abduction", "index.flexion",
           "middle.flexion", "ring.flexion", "little.flexion")   # ch 6-8: never read

def decode_pose(frame):
    """Legacy 9-ch `vhi_control` -> the six canonical DOFs VHI actually renders.

    Canonical `+1` is the named direction and VHI's flexion gains are negative, so the
    mapping is one negation. Exact and symmetric: rescaling would fabricate an extension
    half that was never recorded AND move rest off 0.0 - a rest-breaking error on a limb
    controller. Channels 6-8 are dropped; no VHI consumer reads them.
    """
    return {n: np.clip(-frame[..., i], -1.0, 1.0) for i, n in enumerate(_LEGACY)}
```

B1 decodes to **six** verified DOFs, not one. Rank-1 (see Evidence) is a property of the
**corpus**, not of the mapping — collapsing would destroy information and mis-decode any
future archive containing real per-finger data. `hand.grip` survives as a legitimate
*composed* canonical DOF that the VHI target fans out to the five flexion channels,
which is what the recorded corpus actually contains, and it counts as **one** control in
`[simultaneous]`.

B2 is a plain signed negation over six channels, padded to 9 for VHI's width guard. It
exists **for reversibility, not compatibility**: it lets the full canonical layer run
against an unmodified VHI binary before the second repo moves.

**The 31 archives are never rewritten.** A migration script was considered and rejected:
it sign-flips 6904 unrepeatable samples, leaves no marker distinguishing migrated from
original, and its only guard (`matrix_rank != 1` -> skip) would skip the 7 all-zero Rest
archives rather than any corrupt one. Instead: version the schema, ship B1, leave the
bytes alone.

---

## 9. Simultaneous control (commercial policy)

Designed separately and unchanged by this plan. Summary of the contract it needs from
here:

- **Defined DOFs are unlimited and never counted.** The counted unit is a **control** —
  one line in `[simultaneous]`, over one or more DOFs. `count = len(simultaneous)`.
- Definition: *two controls are active together if, within one session, the app will
  accept a command on both of them without the user first switching a mode.*
- `kind` is absent from the projection, so the policy **cannot** price continuous and
  discrete differently. Structural, not disciplinary.
- The policy consumes a target-independent `dict[str, tuple[str, ...]]` projection
  pushed from the loader to `Context`. Core never imports the DOF layer; mappers never
  see the policy. Two AST tests pin it.
- Startup-only, never per-tick. Unrestricted community default (`None`), so research,
  CI and all examples are unaffected with no env var and nothing to disable.
- **Opposing pairs are a load-time error**: `wrist.pronate` + `wrist.supinate` must be
  one signed DOF, so nobody doubles their count by splitting an axis.

---

## 10. Implementation sequence

Each step independently shippable and green alone. MyoGestic and VHI never need to
release together; step 4 is additive on both sides and is the only cross-repo step.

| step | change | its test | revert |
|---|---|---|---|
| **0** | Commit two verbatim fixture archives (~56 KB). Fix ch1 `0`->`-1` in the four pose tables. Fix the clip-before-filter bug at `emg_regression.py:214-224` | new `tests/test_vhi_legacy.py`, assertions at the **measured** values (see Evidence) | `git revert` |
| **1** | `myogestic/controls.py`: model, `load_dofs`, the three TOML hazard errors, `substitute_rest`/`clip`/`encode`/`decode`, `Target`, `ControlBus` (with the final clip + tunable dead zone). Plus `save_pickle(..., controls=)` sidecar and `LoadModelButton` refusal | `tests/test_controls.py`: accumulated-error text, the runtime invariants, `as_dict()` round-trip, sidecar mismatch refusal | delete one module |
| **2** | Self-describing wire + recordings: `LSLOutlet` channel names/units/`source_id`; `LSLSource.connect()` reads them back; `_META_SCHEMA_VERSION` 2->3 carrying per-channel `range` + `rest`; `iter_aligned_windows(..., with_names=True)` | loopback label round-trip; a schema-3 archive round-trips `control_space` through `load_dofs`; the step-0 fixture still loads | `git revert` |
| **3** | **Reversibility checkpoint, no second repo touched.** `myogestic/vhi/legacy.py` (B1 + B2), `myogestic/vhi/target.py`. Convert `emg_regression.py` and run it against the **unmodified** VHI binary | `decode_pose` over the fixture; B2 round-trip | revert one example + two modules |
| **4** | **VHI repo first**, additive: author `myogestic.vhi.v2`, implement `Declare`/`SetControl`/`SweepControl` + a channel-label reader, register **beside** v1. Re-vendor the proto, `uv run --extra grpc python tools/gen_proto.py`. `VhiTarget` probes v2; `UNIMPLEMENTED` -> B2, logged once | proto round-trip of `ControlSet`; fake v1 server exercises fallback; fake v2 exercises `unsupported` -> hold-at-rest and re-declare-after-relaunch. **Acceptance gate: `SweepControl` verifies direction** | both versions interoperate for the whole release |
| **5** | **Subtract**, one release later: delete B2, the four pose tables, `VHI_DOF_INDICES`; delete v1 + `ControlMode` + `SetMovement` from VHI. Rewrite `integrate-vhi.md:78-95` and the four `--8<--` snippet references **in the same commit** | full suite + `properdocs build`; `tests/test_docs.py` covers the rewritten pages | **the only irreversible step**, gated on step 4 |

`iter_aligned_windows` currently yields `dict[stream_name] -> channel-mean vector` and
**never surfaces `channel_names`** (`session/_windows.py:150-190`), so step 2 is a hard
prerequisite for any index-free training path.

Steps 0-2 are worth shipping even if VHI never moves: labelled outlets, self-describing
recordings and a name-resolving window iterator help every LSL consumer and every
training script.

Two knock-ons: **signed targets double target variance**, so any absolute RMSE/R²
threshold in examples or tests changes meaning; and `tests/test_docs.py` executes doc
blocks, so the `np.abs` narrative and `np.clip(pred, 0, 1)` lines must move in the same
commit as the code.

---

## 11. Evidence (measured, not inferred)

Over all 31 `vhi_control` archives in `sessions/` — 6904 samples of VHI's own output;
nothing in the repo publishes that stream, so these are the live app talking:

| measurement | value |
|---|---|
| archives / samples | 31 / 6904 |
| aggregate max | `1.412076e-15` (float noise; positive in **9 of 31**) — *not* exactly 0.0 |
| per-channel min | `[-0.99999994, -1.0, -0.9999998, -0.9999998, -0.9999998, -0.9999998, 0, 0, 0]` — only ch1 is exactly `-1.0` |
| per-session `matrix_rank` | `{0: 7, 1: 24}` — 7 all-zero Rest sessions, 24 rank-1 |
| `max abs(ch1..5 - ch0)` over Fist frames | `1.19e-07` — channels 0-5 move identically |
| ch1 in Fist frames | exactly `-1.0` in all 15 Fist-bearing sessions |
| channels 6-8 | exactly `0.0` throughout |

**The corpus is rank-1**: the recorded "5-DOF regression" contains one degree of freedom,
because the operator only ever opened and closed the whole hand. Fixture assertions must
use these values — `assert pose.max() == 0.0` and `matrix_rank == 1` are both **red**.

Four hand-written pose tables put ch1 at `0` for Fist (`emg_32ch_multi_model.py:78`,
`emg_popout_layout.py:74`, `emg_classification.py:43`, `emg_classification_grpc.py:56`);
the real VHI records `-1`. The data indicts the tables.

---

## 12. Parked as implementation-time migration work

Not reasons to reopen the architecture:

1. Correct `docs/how-to/integrate-vhi.md:78-95` and the four pose tables from §7's table
   — not from each other, and not from the existing docs.
2. Trace the optional `MyoGestic_ControlPose` inlet
   (`src/LSLCommunicationController.cs:20`) — VERIFY whether it shares the 6-live-channel
   layout before v2 touches it.
3. Decide whether VHI v2 keeps 9-wide frames or relaxes `currentData.Count >= 9`.
4. Measure dead-zone and hysteresis defaults on real EMG.
5. Outlet `hz`: default to `pipeline.predict_hz`; VERIFY VHI's consume rate first —
   pushing 50 Hz into a 32 Hz latest-wins outlet drops ~36% of frames.

**Explicitly skipped** until a real target needs them: per-target rates, `[simultaneous]`
runtime enforcement, a unit registry, an events kind, a blocking `wait_declared()`.
