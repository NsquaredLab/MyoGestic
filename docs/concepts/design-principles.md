---
title: "Design principles"
---
The eight rules that guide the public API.

1. No required application base class. Compose objects instead of subclassing the app. Sources, targets and filters need no inherited base or plugin registry. Control maps are plain data, often kept in TOML files. The one exception is [`Outlet`][myogestic.outputs.Outlet]. Anything you write against a *shape* is a
   structural `Protocol` and needs no base. This applies to `Source`, `Target` and `VectorFilter`. `Outlet` is a
   base class because it contains shared running code. It is not a shape. It provides a paced daemon
   thread with compensated timing, a latest-wins slot and per-error-kind deduplication.
   The alternative to inheriting it is copying it once per transport. Subclass it to add `_send`.
   Nothing else in the library asks you to subclass anything.
2. User code is plain functions, `extract()`, `train()`, `predict()`.
3. Every public function has typed arguments and a typed return.
4. One name, one meaning. No overloaded types.
5. Errors tell you what to write. A description of what went wrong is insufficient.
6. The entire public API fits on one page.
7. Each widget is a plain public class with a `.ui()` method, no widget base class. Implementation may be split into a private subpackage of `_<aspect>.py` helpers (state, plot, controls) when a widget grows beyond ~200 LOC. See [`widgets/signals/viewer.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/widgets/signals/viewer.py) plus its [`_state.py` / `_plot.py` / `_controls.py` helpers](https://github.com/NsquaredLab/MyoGestic/tree/main/myogestic/widgets/signals) for the reference pattern. Aim to keep the public entry file under 200 lines and any single helper under ~350.
8. Immediate-mode rendering. Widget state lives on the instance or in a private helper module keyed by widget identity.

These rules keep application code small. Compose the framework objects, keep domain logic in functions, and draw each widget through `.ui()` without a required widget base class.
