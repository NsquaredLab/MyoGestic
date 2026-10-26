# Timed takes — Implementation Plan

> **For agentic workers:** one task, branched from `feat/myocontrol-ux`. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** besides start/stop, the Record step can take fixed-length takes: an optional warm-up
countdown with nothing recorded, then exactly N seconds, then an automatic stop and save. Start/stop
shows elapsed time while it records.

**Architecture:** `RecordingControls` gains an opt-in timed mode driven by a small pure state
machine (testable without ImGui), and a public read of that state. `myocontrol` opts in and draws
the countdown and progress over the signal from that read. Recording itself still goes through the
existing `on_record` / `on_stop` callbacks (`app.start_recording` / `app.stop_recording`).

**Tech Stack:** Python, imgui_bundle, pytest.

**Spec:** the approved canvas *Myocontrol Timed Takes*
(https://claude.ai/artifact/SPeB2QXNUbYBn8rcNJLAcX): the interactive workspace and the
"every state of a timed take" strip. This file restates every decision.

## Global Constraints

- `CLAUDE.md` in full: no colour literals outside `_theme.py` / `widgets/common.py` (use `DANGER`,
  `WARNING`, `SUCCESS`, `tinted_row`, `primary_button`, `segmented`, `push_selected`, `ui_px`,
  `display_font()`, `mono_font()`); NumPy docstrings; docs are tested.
- `uv run ruff check .` clean; `uv run --extra grpc --extra dev pytest -q` green.
- The Record step still fits the step cell (about 400 px) at 1280 × 828, in every state.
- Commits: no AI attribution of any kind.

## Review Focus

1. **Stopping on time:** the take stops on the first frame at or after the length; the saved
   duration is within one frame (≈ 17 ms) of N s. A slow frame never makes a take run on.
2. **State changes from outside** (a stream drops, `stop_recording` called by something else,
   the participant changes) during a warm-up or a timed take: the machine returns to idle and
   never calls `on_record` / `on_stop` twice or late.
3. **Warm-up Off:** recording starts on the press, no countdown frame.
4. **Cancel during warm-up** records and saves nothing (no `on_record` was ever called).
5. **Stop early** keeps the captured take (`on_stop`) and the saved row says *stopped early*.

---

### Task: Timed takes

**Files:**
- Modify: `myogestic/widgets/panels/recording.py` (`RecordingControls`, `_render_recording_controls`)
- Modify: `examples/start_here/myocontrol.py` — the `recording = RecordingControls(...)`
  construction, `record_ui`, and a new helper that draws the overlay in the signal cell
  (called from `myocontrol_ui` right after `viewer.ui(ctx)`)
- Tests: a new `tests/test_timed_takes.py` for the state machine; the existing recording-controls
  tests; `tests/test_myocontrol_wiring.py`
- Docs: `docs/widget-gallery.md` and the how-to page that documents `RecordingControls`

**Interfaces:**
- Produces: `RecordingControls(..., take_lengths: Sequence[float] = (), warmups: Sequence[float] = (0.0,))`.
  An empty `take_lengths` keeps today's start/stop only, so other apps are unchanged. With lengths,
  the widget draws a **Start / stop | Timed** switch.
- Produces: a public read of the take in progress, e.g. a `take` property returning a small frozen
  dataclass `TakeStatus(phase: Literal["idle", "warmup", "recording", "saved"], timed: bool,
  gesture: str | None, elapsed_s: float, length_s: float | None, warmup_left_s: float,
  saved_text: str)`. Name it to fit the module; `myocontrol` reads only this.

- [ ] **Step 1: Tests first** for the pure state machine (feed it `now` values; no ImGui):
  start with warm-up → `warmup` phase and no `on_record`; warm-up ends → `on_record` once, phase
  `recording`; reaching the length → `on_stop` once, phase `saved` with `"Saved · Fist · 5.0 s"`;
  `saved` returns to `idle` after ~2 s; warm-up Off starts recording at once; cancel in warm-up
  calls neither callback; stop early → `on_stop`, text ends `(stopped early)`; an outside stop
  (the app no longer recording) returns to idle without calling `on_stop`; start/stop mode reports
  `elapsed_s` counting up.
- [ ] **Step 2: The state machine** as a small class in `recording.py` using `time.monotonic()`
  (injectable for tests), advanced once per frame from `ui()`.
- [ ] **Step 3: Rendering** in the Record step, top to bottom:
  - the gesture tiles as today; during a timed warm-up or take, the tiles other than the active
    one are disabled (one gesture per timed take). Start/stop keeps switching gestures mid-take.
  - the **Start / stop | Timed** `segmented` across the row (disabled while a take runs).
  - Timed only: a two-column row, caption above each: **Take length** (`segmented`, e.g. `3 s` `5 s`
    `10 s` from `take_lengths`) and **Warm-up** (`Off` `1 s` `2 s` `3 s` from `warmups`), disabled
    while a take runs.
  - the action area, one row of the same height in every state:
    idle → the full-width red record button, labelled `Record Fist · 5 s` (timed) or `Record Fist`;
    warm-up → a `WARNING`-tinted row: the countdown digit in `display_font()`, **Get ready · Fist**
    over the muted mono `nothing recorded yet`, and **Cancel** at the right, with a thin
    `WARNING` progress line along its bottom edge;
    recording → a `DANGER`-tinted row: a `DANGER` dot, **Recording · Fist** over the mono clock
    (`0:03.1 / 0:05.0` timed, `0:07.4 elapsed` start/stop) and **Stop early** / **Stop** at the
    right; timed adds a thin `DANGER` progress line;
    saved → a `SUCCESS`-tinted row with a check and the saved text, for ~2 s.
  - The old IDLE/state pill row under the button goes: the action area now carries the state in words.
- [ ] **Step 4: `myocontrol`:** construct with `take_lengths=(3.0, 5.0, 10.0)` and
  `warmups=(0.0, 1.0, 2.0, 3.0)`, defaults 5 s and 2 s. After `viewer.ui(ctx)` in the signal cell,
  draw from the widget's `take` read with the window draw list: during warm-up, a translucent
  surface-tone veil over the plot with **Get ready · Fist** in `WARNING`, the countdown digit large
  in `display_font()` and `recording starts in 1.4 s` in muted mono; while recording, a chip at
  the plot's top-right `REC Fist · 0:03.1` (`DANGER` dot) and, timed only, a 3 px `DANGER`
  progress bar along the cell's top edge. Nothing is drawn when idle.
- [ ] **Step 5:** ruff, full suite; commit `feat: timed takes — warm-up countdown, fixed length, auto stop; elapsed time while recording`.
