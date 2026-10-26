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

Use **+** in the Source card to add another amplifier; generated targets are
excluded from device selection. In `force_ramps.py`, follow Connect → Track to
connect EMG and force streams, calibrate, and record tracking blocks. In `pong.py`,
follow Connect → Record → Train → Play; the signal view gives way to the court
after Connect. The hand mirror is optional.

Sessions and the activity log stay visible, and recordings continue across steps.
Cards stack in narrow windows; force ramps keeps its tracking target visible while
the step and sessions cards scroll. Each app's footer shows acquisition, participant
and session folder; Myocontrol and Pong also show the fitted or saved model.

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

## Trying Pong without hardware

In `pong.py`, connect **Synthetic wrist (dummy follows the cursor)**. During a
cursor block the dummy follows the recorded cursor automatically. After training,
hold **↑** to flex up or **↓** to flex down; the drive ramps from rest to full
effort in 150 ms. Release the keys, or hold both, to return to rest. You can also
press and hold the arrow keycaps in **Simulated EMG** with the mouse.

Arrows and **Space** act only while the app has focus and no text field is active.
The simulated card appears only for a connected dummy wrist. With real hardware,
your contractions drive the model. **Space** or **Serve** starts a fresh game;
first to 11 ends it. **Play again** resets the court, and **Harder** moves to the
next opponent level when one is available.

## Adding one

The bar is that somebody could run a study with it and change nothing. That
means it names no hardware, records every stream the analysis will need
(including whatever the subject was *asked* to do, not only what they did), and
its settings are all reachable from the UI. Anything narrower belongs in
`panels/`, `synthetic/` or `otb/` — a file here that has to be edited before it
is useful is a demo that has wandered into the wrong folder.
