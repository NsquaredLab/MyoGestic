# Session

Read back an on-disk recording session: iterate labeled or aligned windows for training, or open the raw store. See [Record and replay](../how-to/record-and-replay.md).

## Reading sessions

Three window iterators, differing only in what each window is paired with. `iter_labeled_windows` gives a **class index** from the label track. `iter_target_windows` gives the value of a recorded [`TargetSource`][myogestic.sources.TargetSource] stream at the window's **end** — the causal choice, and the one to reach for whenever the target is graded rather than cued; see [Record for proportional control](../how-to/record-for-proportional-control.md). `iter_aligned_windows` gives a sample from one or more arbitrary streams nearest the window's **midpoint**.

::: myogestic.session.open_session_store

::: myogestic.session.iter_labeled_windows

::: myogestic.session.iter_target_windows

::: myogestic.session.iter_aligned_windows

::: myogestic.session.split_sessions_by_stream

::: myogestic.session.SessionSplit

## Data model

::: myogestic.session.Session
    options:
      summary:
        functions: true
        attributes: true

::: myogestic.session.LabelEvent

::: myogestic.session.Recording
