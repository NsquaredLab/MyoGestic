# Start here — complete protocols

Whole applications, ready to run a real session with. Open one of these first.
Never run anything before? [WINDOWS.md](WINDOWS.md) walks from an empty
Windows machine to a recorded force-ramps session, no programming assumed.

```bash
uv run python examples/start_here/force_ramps.py
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
uv run --extra examples --extra grpc python examples/start_here/pong.py
```

`myocontrol.py` and `pong.py` ask for two extras because they train a model and
speak to the Virtual Hand. `force_ramps.py` needs neither, and `pong.py` plays
with no Virtual Hand at all — the wrist there only mirrors the paddle.

In `myocontrol.py`, set a participant ID, then follow Connect → Record → Train → Drive; recordings and trained models are saved under `sessions/<ID>/`.

The Source card includes stream chips and a **+** action for adding another amplifier;
the generated target stays separate from device selection. In `force_ramps.py`, follow
Connect → Track in the header. Connect shows the signal and the Source picker with
EMG and force stream chips. Track shows the complete force-tracking card, including
calibration, target settings and Start, beside the recording control. In `pong.py`, follow
Connect → Record → Train → Play in the header. The subject sees Signal during Connect
and the Pong court in the remaining steps. One step card contains Source and the
optional hand mirror in Connect, the cursor or gesture protocol in Record, model mode
and features in Train, and court settings, smoothing and prediction in Play. Sessions
and the activity log remain visible; the signal, step, sessions and log stack when the
window is narrow. A recording continues when another step is open. All three apps
keep acquisition, participant and the session folder in a footer; Myocontrol and
Pong also show the fitted or saved model there.

The narrow force-ramps layout reserves height for the complete tracking card, so
the target stays visible; its step and sessions cards scroll when space is tight.

The rest of `examples/` answers "how do I do X": [`panels/`](../panels) stands
up one widget at a time, and [`synthetic/`](../synthetic) and
[`otb/`](../otb) each demonstrate one technique against one kind of signal.
These do not demonstrate anything. Each is a protocol — acquisition, the task,
and the recording of both — that you could take to a subject unmodified.

| Script | Protocol | What you get |
|--------|----------|--------------|
| `force_ramps.py` | Isometric force ramps | Any supported amplifier, a trapezoidal target to track at a set %MVC, and a session holding the EMG, the force and the target side by side |
| `myocontrol.py` | Myocontrol: record, train, drive | Any supported amplifier, Rest/Fist trials shown on the control hand, a classifier or a regressor trained from them, and the prediction hand driven by whichever one you trained |
| `pong.py` | Pong: graded wrist control | Any supported amplifier, Down/Rest/Up trials cued on the paddle, a regressor trained on one signed `[-1, +1]` command, and a rally that only comes back if the contraction is graded |

Every one of them picks its hardware from a dropdown rather than naming it in
the source, so the same file runs against a Muovi, a Quattrocento, an LSL
outlet, or the synthetic amplifier when there is no hardware to hand. See
[Pick a device](../../docs/how-to/pick-a-device.md).

## Adding one

The bar is that somebody could run a study with it and change nothing. That
means it names no hardware, records every stream the analysis will need
(including whatever the subject was *asked* to do, not only what they did), and
its settings are all reachable from the UI. Anything narrower belongs in
`panels/`, `synthetic/` or `otb/` — a file here that has to be edited before it
is useful is a demo that has wandered into the wrong folder.
