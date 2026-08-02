# Design principles

The eight rules the codebase keeps to:

1. **No base classes. No inheritance.** No registration. No config files. **One exception,
   named:** [`Outlet`][myogestic.outputs.Outlet]. Anything you write against a *shape* is a
   structural `Protocol` and needs no base — `Source`, `Target`, `VectorFilter`. `Outlet` is a
   base class because it is not a shape: it is sixty lines of running code — a paced daemon
   thread with compensated timing, a latest-wins slot, per-error-kind deduplication — and the
   alternative to inheriting it is copying it once per transport. Subclass it to add `_send`.
   Nothing else in the library asks you to subclass anything.
2. User code is **plain functions**: `extract()`, `train()`, `predict()`.
3. Every public function has **typed arguments and a typed return**.
4. **One name, one meaning.** No overloaded types.
5. Errors tell you **what to write**, not what went wrong.
6. The entire public API **fits on one page**.
7. Each widget is a **single public function**, no inheritance. Implementation may be split into a private subpackage of `_<aspect>.py` helpers (state, plot, controls) when a widget grows beyond ~200 LOC. See [`widgets/signals/viewer.py`](https://github.com/NsquaredLab/MyoGestic/blob/main/myogestic/widgets/signals/viewer.py) plus its [`_state.py` / `_plot.py` / `_controls.py` helpers](https://github.com/NsquaredLab/MyoGestic/tree/main/myogestic/widgets/signals) for the reference pattern. Aim to keep the public entry file under 200 lines and any single helper under ~350.
8. **Immediate-mode rendering.** Widget state, when needed, is keyed by widget identity and lives in a private `_<widget>_state.py` module.

These aren't aesthetic preferences. They're a **hard contract**: a library small enough to fit in one LLM context window, where every widget is a single function with no class hierarchy.
