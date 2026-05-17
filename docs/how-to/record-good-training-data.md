# Record good training data

Most "my model doesn't work" reports come down to bad training data, not bad modelling. The framework can't compensate for a one-click recording any more than scikit-learn can. This page covers what cycle-style recording is, why it matters, and how to verify your data before training.

## The failure mode

A typical first run looks like this:

1. Click **Record** → click **Rest** → wait → click **Fist** → click **Stop**.
2. Repeat for two more sessions.
3. Tick all three sessions in [`session_manager`][myogestic.widgets.session_manager], click **Train**.
4. Click **Predict**. Hand barely moves. Confidence numbers are mediocre. Single classes get confused with each other.

Each session above has **exactly two label events** (Rest, Fist) with maybe 3-5 seconds of data total. After framework processing, classification models see one window per class - far less than CatBoost / sklearn / etc. need, and the first segment is dropped anyway (the framework's "skip first" heuristic - it's usually onset noise).

## Cycle-style recording

Instead, do this in **one** Record→Stop session:

```text
[Record]
  [Rest]   3 s   "rest"
  [Fist]   3 s   "first activation"
  [Rest]   3 s
  [Fist]   3 s   "second activation"
  [Rest]   3 s
  [Fist]   3 s   "third activation"
  [Rest]   3 s
[Stop]
```

That's eight button clicks, ~24 seconds of data, in one session. After framework processing, classification models see ~12-15 overlapping windows per class (with the default `WIN_SECONDS=0.2`, `HOP_SECONDS=0.1`) - enough for the model to actually generalise.

## How many cycles

Rough rules of thumb:

| Model | Minimum | Comfortable |
|-------|--------:|------------:|
| Classification (CatBoost / sklearn / XGBoost) | 1 session × 5 cycles = 5-7 windows/class | 3 sessions × 5 cycles = 15-25 windows/class |
| Regression (`iter_aligned_windows`) | 1 session × 60 s of continuous motion | 3 sessions × 60 s |

The "comfortable" column is the regime where models start performing within a few percent of their best-case on synthetic data. Add more if your hardware is noisy or if you want robustness across days.

## Verifying before you train

The `template_inspector` and `trial_preview` widgets show the trials extracted from your selected sessions. Look at:

- **Counts**: at least 5 trials of each class for classification; more if your hardware is noisy.
- **Per-trial preview pop-out**: each trial should show a clean activation onset followed by sustained activity. If a "trial" lands on a flat baseline, your labelling went wrong (usually because the recording started with the user already gripping).

## Recording protocol checklist

- **Hold each gesture for at least 2 seconds.** Less and the predict thread's smoothing window (5 ticks @ 20 Hz = 250 ms) doesn't have time to commit a state flip during prediction.
- **Return to rest between gestures.** Don't transition gesture → gesture directly. Rest is the framework's reference; muddy rest segments degrade both training and prediction.
- **Record several sessions on different days** if you can. Cross-day variance is the largest noise source for surface EMG; one-day models often fail tomorrow.
- **Check your signal viewer first.** If the live signal looks like noise across all channels even when you flex, your electrode placement is wrong - fix it before recording.
- **Use `recording_controls`'s button strip, not just the Record button.** Each button click writes a [`LabelEvent`][myogestic.session.LabelEvent]; the trial slicer needs those events to know where one trial ends and the next begins.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **One-click sessions.** A session with two label events (Rest + Fist) yields one usable trial after the skip-first heuristic. Cycle-style is the only way to get useful data per session.
- **Forgetting to come back to rest.** Gesture → gesture transitions confuse the trial slicer; the second gesture's onset gets attributed to the first gesture's class.
- **Recording before the signal stabilises.** EMG amplifiers settle for 1-2 seconds after starting. If you click Record immediately after Start, your first cycle is biased low.
- **Mixing test mode with real recordings.** The synthetic generator emits fundamentally different patterns from real EMG. A model trained on synthetic test data won't transfer.

See also: [Record and replay](record-and-replay.md).
