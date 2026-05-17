# Concepts

Explanation of how MyoGestic v2 fits together. Read these once to understand the runtime model; the [how-to guides](../how-to/index.md) and [API reference](../api/index.md) become much easier afterwards.

If you haven't yet, read **[Anatomy of an app](../anatomy.md)** first - it walks through one complete tiny app in the order you write it and builds the mental model these deep-dive pages assume.

Drill in:

- [Architecture](architecture.md) - the runtime: sources → streams → context → render / predict / output threads.
- [Streams](streams.md) - the ring buffer, `get_window` vs `get_display`, channels-first convention.
- [Pipeline](pipeline.md) - `extract` / `train` / `predict` decorators, `TrainingData`, the predict thread.
- [Recording](recording.md) - sessions, label tracks, the `.session.zip` archive layout.
- [Widgets](widgets.md) - the stateless-function contract, ImGui immediate mode, `Grid` layout.
- [Threading](threading.md) - daemon threads, GIL release, the GPU contention rule.
- [Design principles](design-principles.md) - the eight rules the codebase keeps to.
