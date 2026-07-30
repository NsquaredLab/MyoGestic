# Integrate the Virtual Hand Interface

The **Virtual Hand Interface (VHI)** is the Godot-based 3-D hand
visualisation that ships alongside MyoGestic. It can be driven on two
planes at once:

* **LSL data plane** - high-rate continuous values. Continuous DOFs stream
  every tick; VHI renders them on the *predicted hand*.
* **gRPC control plane** - the negotiation, discrete state, and verification.
  `Declare` agrees a control space by *name*, `SetControl` carries held
  states, and a separate recording aid gates a session and drives training
  trajectories.

You don't have to pick one, and mostly you don't choose at all: declare what
you control and hand it to a
[`ControlBus`](../api/controls.md) with a `VhiTarget`. The target negotiates,
puts continuous values on LSL, and sends discrete states over gRPC.

!!! tip "Watch it happen first"
    `uv run --extra grpc python tools/inspect_control.py` walks the whole
    path end to end and prints what reaches the wire. It needs no Virtual Hand, and
    tells you which contract yours speaks if you have one running.

## Start with a control file

Declare what your application controls in a TOML file. Copy
[`examples/controls/hand.toml`](https://github.com/NsquaredLab/MyoGestic/blob/main/examples/controls/hand.toml)
and edit it:

```toml
[dofs]
# Left side: your model's output names. Right side: controls VHI declares.
my_thumb_spread = "vhi.prediction.thumb.abduction"

fist = [                                       # one output, fanned out
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },   # ...with a per-target gain
  { target = "vhi.prediction.index" },
  { target = "vhi.prediction.middle" },
  { target = "vhi.prediction.ring" },
  { target = "vhi.prediction.little" },
]

gesture = { target = "vhi.control.gesture", debounce_s = 0.1 }

# Equal weights need no tables:  grip = ["vhi.prediction.ring", "vhi.prediction.little"]
# One control may take only one output, so no two entries may name the same address.
```

Load it, and hand the result to a bus with a `VhiTarget`:

```python
import tomllib

from myogestic.controls import ControlBus, load_control_map, resolve
from myogestic.vhi import VhiTarget, virtual_hand

vhi = virtual_hand()
vhi_control = vhi.control_client()

with open("hand.toml", "rb") as f:            # "rb" — tomllib requires binary
    CONTROL_MAP = load_control_map(tomllib.load(f))

bus = None            # built once VHI can say what it exports


def ensure_vhi() -> None:
    """Resolve the map once VHI is up. Call from a button handler, never from predict."""
    global bus
    if bus is not None:
        return
    capabilities = vhi_control.capabilities()
    if capabilities is None:
        return                                # not reachable yet; try again later
    controls = resolve(CONTROL_MAP, capabilities)
    target = VhiTarget(vhi.outlet(), client=vhi_control)
    bus = ControlBus(controls, targets=[target], hz=32)
```

The bus is built **lazily** because resolution needs a live target: VHI declares whether
each address is a number or a held state, and an app that launches VHI from its own UI
necessarily starts before it exists. `capabilities()` blocks on an RPC, so call
`ensure_vhi()` from a UI handler and let `predict` no-op while `bus is None`.

That is the whole setup. `bus.push({"fist": 0.8})` from inside `@pipeline.predict` —
using *your* alias, the left side of the file — and the target negotiates the wire,
encodes, and sends.

!!! note "The file is yours; the library never reads it"
    `load_control_map` takes a **Mapping**, not a path — so MyoGestic reads no configuration
    files, and your declaration can equally live in JSON, a dict literal, or a config
    system you already run. TOML is what a human wants to edit, which is why the shipped
    example is TOML and why the snippet above opens it itself.

!!! tip "Declare DOFs, don't push channels"
    The rest of this page shows the transport underneath, which is worth
    understanding when something misbehaves. But application code should not
    contain channel indices or sign flips — that is what `VhiTarget` is for,
    and the four wrong pose tables this project fixed all came from hand-written
    channel maps.

![VHI dual-plane integration](../images/vhi-integration.svg){ align=center }

## The one-liner that wires it up

```python
from myogestic.vhi.interfaces import virtual_hand

vhi = virtual_hand()                  # resolves install path + gRPC endpoint
vhi_outlet = vhi.outlet()             # 9-ch LSL outlet @ 32 Hz
vhi_control = vhi.control_client()   # negotiates the control space (v2)
recording = vhi.recording_client()     # recording session gate + trajectory playback
```

`virtual_hand()` looks at `$VHI_PATH`, the per-user install root, and the
local git checkout in that order. It reads `$VHI_GRPC_HOST` /
`$VHI_GRPC_PORT` for the control endpoint (defaults `127.0.0.1:50051`).
The returned `InterfaceSpec` knows everything - outlet name, channel
count, send rate, gRPC target, launcher argv - so the example code stays
boilerplate-free.

If VHI isn't installed yet, see **[Install the Virtual Hand](install-vhi.md)**.

## Launching the VHI process

Drop the launcher into your `ProcessLauncher` panel and the user gets
a Start/Stop button for VHI:

```python
import sys
from myogestic.widgets import ProcessLauncher

PROCESSES = [
    ("EMG Generator", [sys.executable, "-m", "myogestic.tools.emg_generator",
                       "--name", "TestEMG1", "--channels", "8", "--fs", "2048"]),
    *vhi.launcher(),
]

launcher = ProcessLauncher(PROCESSES)

@app.ui
def ui(ctx):
    with grid[0, 0]:
        launcher.ui()
```

`vhi.launcher()` prefers a packaged binary install when present and
falls back to `godot --path <project>` for source-mode development. Set
`$VHI_LAUNCH_MODE=binary` or `=godot` to force one.

If VHI is not installed, `launcher()` raises `FileNotFoundError` with the
exact `install_vhi` command to run. Surface this as a status message:

```python
try:
    PROCESSES = [*base, *vhi.launcher()]
except FileNotFoundError as e:
    print(f"[demo] {e}", file=sys.stderr)
    PROCESSES = base       # demo still runs; VHI button just absent
```

## Plane 1 - continuous pose over LSL

!!! tip "Prefer the control standard"
    Everything below describes the **legacy** wire, kept for builds that predate
    the v2 contract. New work should declare DOFs by name and let
    [`VhiTarget`](../api/controls.md) negotiate — then none of these channel
    numbers appear in your code at all.

VHI subscribes to a 9-channel float32 outlet, interpreted in `[-1, 1]`. The
mapping below was read out of VHI's own consumer (`PredictedHandSkeleton`) and
confirmed against recorded sessions:

| Index | Joint            | Notes                                    |
|-------|------------------|------------------------------------------|
| 0     | Thumb flexion    | bones 1/2/3, X axis                      |
| 1     | Thumb abduction  | bones 1/2/3, Z axis                      |
| 2     | Index flexion    |                                          |
| 3     | Middle flexion   |                                          |
| 4     | Ring flexion     |                                          |
| 5     | Little flexion   |                                          |
| 6-8   | Wrist flexion, abduction, rotation | bone 0, which parents every digit |

Two corrections to what this page used to say, both verified rather than assumed:

* Channel 0 is thumb **flexion**, not thumb rotation, and channel 1 is thumb
  **abduction**, not thumb flexion. A recorded fist has channel 1 at exactly
  `-1.0`, which is what settled it.
* Channels 6-8 **do** drive the wrist. They read `0` in every reference
  recording because no archived session predates wrist support — a fact about
  that corpus, not about the renderer; see `myogestic.vhi.legacy` for the
  reader that still has to account for it.

`0` is rest and `-1` is full flexion on this wire — the sign is the renderer's,
not the standard's. Push every predict tick: `vhi_outlet` runs its own send
thread at `hz`, so only the latest push is sent.

```python
@pipeline.predict
def predict(model, features):
    pose = model.compose_pose(features)            # np.float32, shape (9,)
    vhi_outlet.push(pose)
    return {"pose": pose}
```

Pair it with a smoothing filter - raw model output looks twitchy on a
60 fps render:

```python
from myogestic.widgets import PostProcessor
import time

pose_filter = PostProcessor(hz=20.0)

@pipeline.predict
def predict(model, features):
    pose = pose_filter(model.compose_pose(features), timestamp=time.monotonic())
    vhi_outlet.push(pose)
    return {"pose": pose}

@app.ui
def ui(ctx):
    with grid[6, 0]:
        pose_filter.ui()
```

See [Post-process predictions](post-process-output.md) for filter tuning.

## Classification: the same mapping a regressor uses

A classifier does not need its own path to the hand. It produces an **activation** —
open or closed — and an activation is just a control value, so it travels the mapping
you already have. Add a `threshold_fraction` — the probability cutoff — to say the input
is a classifier's confidence rather than a position:

```toml
fist = { targets = [
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },
  { target = "vhi.prediction.index" },
  { target = "vhi.prediction.middle" },
], threshold_fraction = 0.5 }
```

Push the probability and the bus gates it before anything else sees it:

```python
@pipeline.predict
def predict(model, features):
    proba = model.predict_proba(features.reshape(1, -1))[0]
    bus.push({"fist": float(proba[1])})
    return {"class": int(np.argmax(proba))}
```

Three separate decisions happen, in this order. `threshold_fraction` decides **whether**
the
hand is closed, giving a 0 or a 1. The weights decide **how much of that** each digit
gets — the thumb 0.6, the fingers all of it. `ControlBus(smoothing=...)` then decides
**how fast** the change is allowed to look. So VHI receives continuous per-control
values, the same ones a regressor would send, and drop the `threshold_fraction` and the
identical
mapping serves a regressor emitting 0..1 directly.

The gate matters because a continuous address is a *position*. Streaming a raw `0.73`
into one says the finger is 73% curled, which is not what a 73%-confident classifier
meant. `examples/synthetic/emg_classification.py` with
`examples/controls/classification.toml` is this end to end.

## Plane 2 - discrete state and negotiation over gRPC

Some controls are genuinely discrete: a preset, a keypress, a mode — things that *are* a
state rather than an amount. VHI declares those addresses discrete, and then the right
primitive is "hold state X, and change it only when the class has actually settled".
Reach for this for events, not for fingers; a hand closing is the activation above.

Declare it in the file — `debounce_s` is the gate, in seconds:

```toml
gesture = { target = "vhi.control.gesture", debounce_s = 0.1 }
```

VHI declares `vhi.control.gesture` discrete and supplies its states, so you do not write
them. `debounce_s` *is* yours to write: it is a property of your control loop, not of the
hand.

Then command it by name, using the `bus` built above:

```python
@pipeline.predict
def predict(model, features):
    class_idx = int(np.argmax(model.predict_proba(features)))
    bus.push({"gesture": CLASSES[class_idx]})
    return {"class": class_idx}
```

The states come from the manifest, so push one of *those* names, not a name of your own.
`debounce_s` is declared on the DOF rather than wrapped around the client, because
it is a property of the control: a classifier flickering tick-to-tick must produce
*no* transition until one state holds. Use `bus.select(...)` for a deliberate click
— it delivers immediately and rebases the gate so the next predict ticks don't
re-fire.

!!! warning "Never low-pass filter a discrete control"
    Smoothing is three separate mechanisms and mixing them up is a bug:

    | Layer | Where | Applies to |
    |---|---|---|
    | Continuous smoothing | `ControlBus(smoothing=...)` | continuous DOFs |
    | Debounce / hysteresis | declared on the DOF | discrete DOFs |
    | Presentation blending | `control_client().set_presentation(...)` | appearance only |

    Averaging "rest" and "fist" would interpolate through a state nobody selected,
    so the bus never passes a discrete value through a filter — the filter only
    ever sees the continuous vector. And renderer blending, while worth having,
    cannot make an unstable prediction stable: with blending on and no debounce a
    hand still jumps between states, just smoothly.

### The clients

Both gRPC clients are constructed from the interface spec. Absence is reported rather
than raised — a call returns `None` when VHI is not up — so a UI stays responsive while
the renderer starts:

| Call | Effect |
|---|---|
| `control_client().declare(controls)` | Negotiate. Returns `None` when VHI has not answered; `VhiTarget` defers and retries. A build that answers without the v2 service is refused. |
| `control_client().set_control(...)` | Command a frame. Fire-and-forget; safe from the predict thread. |
| `control_client().sweep(name)` | Drive one DOF across its range and report which bones moved, in signed degrees. Verification only — it animates a joint. |
| `control_client().set_presentation(blend=...)` | Renderer blending. Appearance only. |
| `recording.set_recording_session(True / False)` | Gate VHI's local keyboard so a recording has one movement source. |
| `recording.start_trajectory(movement, frequency_hz=...)` | Cycle the control hand to generate a training trajectory. |
| `recording.state()` | Movements, current movement, whether a trajectory is running. |

`declare`, `sweep` and the aid's calls are **synchronous** — they are setup, teardown
and verification, and a caller needs the answer. `set_control` is fire-and-forget on a
worker thread, so it never blocks a 60 fps render loop.

!!! note "Recording is not control"
    A recording trajectory deliberately keeps the control hand *moving*, which is the
    opposite of what a discrete DOF means. That is exactly why it lives in a separate
    service: collecting training data must not redefine "hold this state". While a
    trajectory runs it owns the control hand, and discrete DOFs are refused with the
    reason rather than silently interrupting the trajectory a recording is aligned
    against.

## A ready-made movement palette

`VhiMovementPanel` packages "fetch control-hand state in the background, render the
movement buttons, dispatch clicks" into one widget. It reads the recording aid for
state and takes the click handler explicitly — wire it to a control-standard DOF, because
dispatching straight at the renderer would bypass the debounce:

```python
from myogestic.widgets.vhi.panel import VhiMovementPanel

panel = VhiMovementPanel(
    recording,
    lambda state: bus.select("gesture", state),
)

@app.ui
def ui(ctx):
    with grid[8, 0]:
        panel.ui()
```

The handler is where you layer side-effects on a click — snap a session label, drive
a fake generator, whatever the experiment needs:

```python
def _on_movement_click(name: str) -> None:
    ctrl_outlet.push_sample(...)                    # e.g. drive the EMG generator
    bus.select("gesture", name)                     # deliver + rebase the debounce
```

`bus.select` is the important part: it delivers the state immediately *and* rebases
the DOF's stability gate, so the next predict ticks — still carrying the old
sliding-window class — do not re-fire what the button just did.

## Driving the control hand as a recording target

Some workflows — continuous regression, where the control hand is the *target* the
model learns — want the control hand to move on its own so the recorded kinematics
sweep a range. That is what the **recording aid** is for:

```python
recording.start_trajectory("Fist", frequency_hz=0.7)   # cycles, producing a trajectory
...
recording.stop_trajectory()                            # stops and rests the hand
```

A recording trajectory is deliberately *not* a control primitive. It exists so that
collecting data never has to redefine what a discrete DOF means: a discrete DOF holds
a state, and a trajectory sweeps — two different jobs, two different vocabularies.
While a trajectory runs it owns the control hand and discrete DOFs are refused with
the reason.

Wrap a recording in the session gate so VHI's local keyboard cannot compete as a
movement source:

```python
def _on_record() -> None:
    app.start_recording()
    if not recording.set_recording_session(True):
        app.ctx.log("no VHI recording gate — the keyboard is not blocked")
```

It returns `False` rather than raising when the aid is unavailable, because whether an
ungated recording is acceptable is a judgement about experiment integrity and not the
client's to make.

## Testing without VHI

`print` is the cheapest viewer:

```python
@pipeline.predict
def predict(model, features):
    pose = model.compose_pose(features)
    print(f"pose: {[f'{v:+.2f}' for v in pose]}")
    return {"pose": pose}
```

Or attach `pylsl`'s `lslviewer.py` to the `MyoGestic_Output` stream. For
the gRPC plane, the standard `grpcurl` works against the local server
when VHI is running - the proto is at
`myogestic/vhi/_proto/myogestic_vhi.proto`.

## Common mistakes

See the full **[Troubleshooting](../troubleshooting.md)** index for
symptom-organised debugging.

* **Building the wire frame by hand.** Map your names onto addresses and let
  `VhiTarget` encode. A hand-built frame hard-codes a channel number and a sign, and
  both are the renderer's to declare — the two pose streams do not even share a
  convention, so one hand-built frame is silently inverted on one of them.
* **Numerically filtering a discrete control.** It interpolates through states nobody
  selected. Declare `debounce_s` on the DOF instead; see the smoothing table above.
* **Relying on renderer blending to steady a classifier.** It cannot. Blending changes
  how a commanded value looks, not whether it is stable.
* **Forgetting `set_recording_session(False)` on session end.** VHI keeps ignoring its
  own keyboard until you toggle it back.
* **Leaving a recording trajectory running.** It keeps the control hand moving and
  refuses discrete DOFs. `stop_trajectory()` is idempotent — call it in teardown
  regardless.
* **Forgetting `pose_filter.reset()` on retrain.** The first few smoothed
  frames blend the new model's first prediction with the old model's
  last; looks like a brief pose drift on every train cycle.

## See also

* [Install the Virtual Hand](install-vhi.md) - the installer CLI.
* [Edge trigger](../concepts/edge-trigger.md) - fire-on-change pattern.
* [Examples directory](../tutorials/examples-index.md) - every shipped
  example wires VHI either via LSL, gRPC, or both.
* [`myogestic.vhi.interfaces.virtual_hand`](../api/core.md) - full signature.
* [`myogestic.widgets.vhi.panel.VhiMovementPanel`](../api/widgets.md) -
  movement palette API.
