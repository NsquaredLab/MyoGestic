---
title: "Concepts"
---
Read [Anatomy of an app](../anatomy.md) first. It walks through a complete app in the order
you write it and introduces the runtime model these pages assume. These pages explain its components. Use the [guides](../how-to/index.md) for tasks and the [API reference](../api/index.md) for symbols.

- [Architecture](architecture.md) - the runtime: sources → streams → context → render / predict / output threads.
- [Streams](streams.md) - the ring buffer, `get_window` vs `get_display`, channels-first convention.
- [Pipeline](pipeline.md) - `extract` / `train` / `predict` decorators, `TrainingData`, the predict thread.
- [Controls](controls.md) - the control map, the `[-1, 1]` standard, in-process vs. remote targets, deferred binding.
- [Recording](recording.md) - sessions, label tracks, the `.mg.zip` archive layout.
- [File names](file-names.md) - `<ID>_<YYYYMMDD-HHMM>_<what>.mg.zip`, gesture codes, model names.
- [Widgets](widgets.md) - the construct-once `.ui()` contract, ImGui immediate mode, `Grid` layout.
- [Threading](threading.md) - daemon threads, GIL release, the GPU contention rule.
- [Design principles](design-principles.md) - the eight rules the codebase keeps to.
- [Visual language](visual-language.md) - the type, colour, panel and state-cue tokens every widget uses.
