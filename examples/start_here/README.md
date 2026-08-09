# Start here — complete protocols

Whole applications, ready to run a real session with. Open one of these first.

```bash
uv run python examples/start_here/force_ramps.py
uv run --extra examples --extra grpc python examples/start_here/myocontrol.py
uv run --extra examples --extra grpc python examples/start_here/pong.py
```

`myocontrol.py` and `pong.py` ask for two extras because they train a model and
speak to the Virtual Hand. `force_ramps.py` needs neither, and `pong.py` plays
with no Virtual Hand at all — the wrist there only mirrors the paddle.

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
