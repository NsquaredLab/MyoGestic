---
title: "Record good training data"
---
Record repeated activations and inspect the extracted trials before training. Overlapping windows from one hold provide limited variation.

## The failure mode

A typical first run looks like this:

1. Click Record → click Rest → wait → click Fist → click Stop.
2. Repeat for two more sessions.
3. Tick all three sessions in [`SessionManager`][myogestic.widgets.SessionManager], click Train.
4. Click Predict. Hand barely moves. Confidence numbers are mediocre. Single classes get confused with each other.

Each session above has two explicit label clicks (Rest, Fist), plus the selected gesture's initial label when capture starts. `iter_labeled_windows` slices every labelled segment into full windows, including the first. Several overlapping windows from one hold represent one activation.

## Cycle-style recording

Instead, do this in one Record→Stop session:

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

That's seven 3-second holds, ~21 seconds of data, in one session. A full 3-second segment yields 29 overlapping windows at `window_ms=200`, `hop_ms=100`. Repeated activations give the model several trials of each class.

## Cycle counts

Rough rules of thumb:

| Model | Minimum | Comfortable |
|-------|--------:|------------:|
| Classification (CatBoost / sklearn / XGBoost) | 1 session × 5 cycles = 5 activations/class | 3 sessions × 5 cycles = 15 activations/class |
| Regression (`iter_aligned_windows`) | 1 session × 60 s of continuous motion | 3 sessions × 60 s |

The "comfortable" column is the regime where models start performing within a few percent of their best-case on synthetic data. Add more if your hardware is noisy or if you want robustness across days.

## Verify before training

The `TemplateInspector` and `TrialPreview` widgets show the trials extracted from your selected sessions. The inspector reports how many templates are kept, with gesture-count chips to filter the list. Toggle a row's Kept / Out chip to include or exclude it from training; All and None apply to every template, including hidden rows. Click a source to preview its trial. Filtering keeps that preview selected until you select another source or remove its row.

Each row shows a gesture tag, source, energy bar and trial number. Gesture colours default to the categorical palette; custom `label_colors` tint the tags while their text follows the active theme. `TrialPreview` shows the selected window in seconds above the traces, with a translucent band marking the region of interest. Look at:

- Counts: at least 5 trials of each class for classification; more if your hardware is noisy.
- Per-trial preview pop-out: each trial should show a clean activation onset followed by sustained activity. If a "trial" lands on a flat baseline, your labelling went wrong (usually because the recording started with the user already gripping).

## Recording protocol checklist

- Hold each gesture for at least 2 seconds. This gives you several full training windows and a sustained activation to inspect. The pipeline does not add a smoothing window automatically.
- Return to rest between gestures. Don't transition gesture → gesture directly. Rest is the framework's reference; muddy rest segments degrade both training and prediction.
- Record several sessions on different days if you can. Cross-day variance is the largest noise source for surface EMG; one-day models often fail tomorrow.
- Check your signal viewer first. If the live signal looks like noise across all channels even when you flex, your electrode placement is wrong - fix it before recording.
- Use `RecordingControls`'s gesture buttons to label the take. Each button click writes a [`LabelEvent`][myogestic.session.LabelEvent]; the trial slicer needs those events to know where one trial ends and the next begins.

## Common mistakes

See [Troubleshooting](../troubleshooting.md) for errors by symptom.

- One-click sessions. A single labelled hold can yield many overlapping windows, but it supplies no repeated activations. Check trials as well as window counts.
- Forgetting to come back to rest. Label boundaries follow your clicks, not the participant's muscle activity. Leave room for a relaxed segment and check that the activation matches the cue.
- Recording before the signal stabilizes. EMG amplifiers settle for 1-2 seconds after starting. If you click Record immediately after Start, your first cycle is biased low.
- Mixing test mode with real recordings. The synthetic generator emits fundamentally different patterns from real EMG. A model trained on synthetic test data won't transfer.

See also: [Record and replay](record-and-replay.md), and
[Record for proportional control](record-for-proportional-control.md) if what you want is a
graded command. Cued classes provide three distinct target values; the estimator
determines interpolation between them.
