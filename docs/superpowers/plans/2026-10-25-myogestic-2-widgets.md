# MyoGestic 2.0 widgets — Implementation Plan

> **For agentic workers:** nine independent tasks (A–I), one worker each, all branched from
> `feat/myocontrol-ux`. Touch only your task's files. Steps use checkbox (`- [ ]`) syntax.

**Goal:** every widget in `myogestic/widgets` speaks the 2.0 design language already used by
StepBar, ParticipantPanel, DevicePicker, SessionManager, FeatureSelector, PredictionLabel,
RecordingControls, SignalViewer and PostProcessor(compact).

**Architecture:** rendering changes inside each widget; public constructors keep working (new
keyword arguments only, defaults chosen so existing call sites still run). Shared look comes from
`myogestic/widgets/common.py` helpers (`panel_header`, `primary_button`, `destructive_button`,
`segmented`, `push_selected`/`pop_selected`, `tinted_row`, `mono_text`, `muted`, `ui_px`, `PALETTE`
and the state tokens `SUCCESS`/`IDLE`/`WARNING`/`DANGER`).

**Tech Stack:** Python, imgui_bundle (ImGui, ImPlot, ImPlot3D, HelloImGui), pytest.

**Spec:** the approved canvas *MyoGestic 2.0 Widgets*
(https://claude.ai/artifact/Acesk6Cmo8cMVvpAbJ2pcr). Its first board is the kit; each other board
is one task below. This file restates every decision.

## Global Constraints

- `CLAUDE.md` in full. No colour literal outside `_theme.py` / `widgets/common.py` (a colour fixed in
  both themes gets a named token in `common.py`); `ensure_implot_style()` in every module that plots;
  NumPy docstrings; docs are tested (a changed widget updates its docstring and any `docs/` page that
  describes it — **except `docs/concepts/visual-language.md`, which only Task I edits**).
- **The kit** (canvas board 1): one card, one `panel_header` (no nested sub-headers,
  `separator_text` or `collapsing_header` sections inside a widget), its state as the header dot;
  state in words as a `tinted_row`; one full-width `primary_button` for the forward action;
  `destructive_button` (red on hover only) for removal — never a permanently coloured button;
  sticky on/off as chips with `push_selected`, never checkboxes; lists as one-line ~26 px rows,
  values and times in mono, right-aligned; rarely-touched settings behind an icon-only settings
  button and popover; captions above controls in a two-column grid instead of `label_column`;
  `PALETTE` only for categorical identity; header actions icon-only; every pixel size via `ui_px`.
- State colours: `SUCCESS` working, `IDLE` not running and nothing wrong (an unattached stream is
  IDLE, not DANGER), `WARNING` worth knowing, `DANGER` failed.
- Constructors stay backward compatible; deprecate rather than remove. Examples are updated in a
  later phase: only touch an `examples/panels/` file if your change would otherwise break it.
- Shared helpers you add go in `widgets/common.py`, appended at the end of the file.
- Verification: targeted tests while working; the full suite **once** at the end with
  `uv run --extra grpc --extra dev pytest -q --deselect tests/test_recording_race.py::test_clear_after_detach_does_not_crash_acquire_loop`
  (that stress test takes minutes under load; the coordinator runs it after merging). `uv run ruff check .` clean.
- One commit per task with the message given, no AI attribution.

## Review Focus

1. **UI scale 2.0 and the light theme** for every redrawn widget: nothing overflows, every state stays legible.
2. **Narrow cells** (~320 px): two-column grids fall back to one column; rows ellipsize instead of wrapping.
3. **Empty and error states** say what to do in words (no bare "(no data)" without a next step where one exists).
4. **Existing call sites** in `examples/` still construct and render (no new required arguments).
5. **Widget identity:** state keyed by `widget_id`, never by the data shown (two instances never share state).

---

### Task A — Streams (`StreamPanel`, `StreamManager`)
Files: `myogestic/widgets/signals/stream_panel.py`, `myogestic/widgets/panels/stream_manager.py`, their tests.
- [ ] StreamPanel: header `Streams` with an icon-only rescan action and a header dot for the worst state
  (all connected SUCCESS, any problem WARNING, none connected IDLE). One line per stream: dot, mono
  name, mono muted `fs Hz · n ch · age` (ellipsized) and a reconnect icon; not connected → IDLE dot,
  `not connected`, a **Connect** button; connecting → surface-tone row `connecting… N s` + **Abort**;
  failed → DANGER-tinted row with the error + **Retry**. With `selectable`, Connect opens a popover
  listing discovered outlets as one-line picks (name + `n ch · fs Hz`) with a rescan icon.
- [ ] StreamManager: draws the stream chips row (mono name, state dot, selected `push_selected`, `×`
  on the selected chip via `destructive_button`, trailing `+` opening an inline name field + **Add** +
  cancel), reusing DevicePicker's chip code through a shared helper rather than copying it. While
  recording: chips dimmed, a caption *Stop the recording to add or remove streams.*
- [ ] Commit: `feat(2.0): StreamPanel one-line rows; StreamManager as stream chips`.

### Task B — Recording and Pong (`RecordButton`, `PongTask`, `status_pill`)
Files: `myogestic/widgets/panels/recording.py` (RecordButton only), `myogestic/widgets/pong.py`,
`status_pill` in `myogestic/widgets/common.py`, their tests.
- [ ] RecordButton: idle → the red full-width record button (same as RecordingControls'); recording →
  DANGER-tinted row **Recording** over mono `0:42.7 elapsed` + **Stop**; naming → surface row
  `naming · 0:42.7 captured` and the modal restyled: caption *Name (optional)*, full-width input,
  a caption showing the resulting file stem, `primary_button` **Save**, an outlined **Discard 0:42.7**
  (red on hover); no participant → disabled record button + caption *Set a participant first —
  recordings are saved under their ID.* All sizes via `ui_px`.
- [ ] PongTask: **Serve** as `primary_button`; rally state as a SUCCESS-tinted row with the mono detail
  and **Stop**; the score in the mono font.
- [ ] `status_pill`: every pixel value through `ui_px`.
- [ ] Commit: `feat(2.0): RecordButton states and dialog; Pong serve and score; scaled status pill`.

### Task C — Processes and smoothing (`ProcessLauncher`, `PostProcessor`/`FilterProcessor`)
Files: `myogestic/widgets/panels/process_launcher.py`, `myogestic/widgets/panels/filter_processor.py`, their tests.
- [ ] ProcessLauncher: header `Process` with the pop-out log as an icon-only header action and the
  header dot (tooltip keeps PID / exit code); process combo full width; stopped → `primary_button`
  **Launch**; running → SUCCESS-tinted row `running · PID 4212 · 0:42` + **Stop**; failed → DANGER
  row `exited with code 1 · 0:03` + **Show output**, then **Launch again**. No permanently coloured buttons.
- [ ] PostProcessor: `compact` defaults to **True**. The compact popover shows the filter's
  `description` as a muted sentence and each parameter as caption-above-slider with its mono value.
  The full panel (`compact=False`) keeps working but uses `panel_header_button` for reset, mono delay
  and caption-above sliders. FilterProcessor follows the same rendering.
- [ ] Commit: `feat(2.0): ProcessLauncher launch/run/fail states; compact smoothing by default`.

### Task D — Plots (`Heatmap`, `LinePlot`, `Scatter2D`, `Scatter3D`, `RawSignalViewer`)
Files: `myogestic/widgets/plots/heatmap.py`, `plots/line_plot.py`, `plots/scatter.py`,
`myogestic/widgets/signals/raw.py`, their tests.
- [ ] Each plot: a `panel_header` title (opt-out `show_title=False`), no ImPlot title, sizes via `ui_px`,
  empty state in words. Heatmap: mono range read-out and a colour-scale strip under the grid.
  LinePlot and Scatter2D/3D: legend as PALETTE-dot chips under the plot; a `y_range` keyword for a
  shared range (LinePlot) with an Auto / Shared `segmented` in the header when one is given.
- [ ] Scatter3D: styled like the rest (an ImPlot3D equivalent of `ensure_implot_style`).
- [ ] RawSignalViewer: state keyed by `widget_id` (not the stream name); header `Raw · <stream>` with a
  Window `segmented` and a Channels popup of chips (PALETTE dot + `push_selected`) instead of
  PALETTE-filled toggles; mono footer `fs Hz · k/n ch · N pts/ch raw · fps`; disconnected / missing /
  no-channel states as centred words like SignalViewer's.
- [ ] Commit: `feat(2.0): plots with headers, legend chips and shared ranges; RawSignalViewer toolbar`.

### Task E — Training tools (`TemplateInspector`, `TrialPreview`)
Files: `myogestic/widgets/training/template_inspector.py`, `training/trial_preview.py`, `common.py`
(a band token), their tests.
- [ ] TemplateInspector: header `Templates` + mono `12 of 16 kept` + **All** / **None** small buttons;
  gesture filter chips (PALETTE dot, count); one-line rows: a **kept/out** chip (`push_selected`)
  instead of a checkbox, the label as a PALETTE-tinted tag, mono source (ellipsized), a thin energy
  bar, mono `#trial`; the selected row tinted. `label_colors` keeps working but defaults to PALETTE by
  label index; caller colours no longer bypass the theme by default.
- [ ] TrialPreview: the band colour comes from a named token in `common.py`; header, mono window
  read-out, sizes via `ui_px`.
- [ ] Commit: `feat(2.0): TemplateInspector one-line rows with kept chips; TrialPreview band token`.

### Task F — Hand and control map (`VhiMovementPanel`, `ControlMapEditor`)
Files: `myogestic/widgets/vhi/panel.py`, `myogestic/widgets/vhi/palette.py`,
`myogestic/widgets/control_map_editor.py`, their tests.
- [ ] VhiMovementPanel: header `Hand movements` with an icon-only refresh and the header dot (SUCCESS
  reachable, IDLE not running); movements as wrapping chips (current one `push_selected`); a mono
  count line; not running → centred *The hand is not running* / *Launch it, then refresh to load its
  movements.* + **Refresh**.
- [ ] ControlMapEditor: header `Control map · <file>` with icon-only Reload, Save as and a TOML toggle,
  and the header dot; dirty → WARNING-tinted row *Unsaved changes · N controls edited* with
  `primary_button` **Save** (the one forward action); disk conflict → DANGER row with **Reload from
  disk** / **Keep my edits**; each control a surface-tone card: mono name input, a *Treat as
  probability* chip, trash at the right; target rows on one line (target picker, weight slider, mono
  value, ×); `+ target`; activation as two captioned sliders side by side (*On at or above*,
  *Steady for*) with mono values; `+ control`; with the TOML toggle on, the TOML editor sits beside
  the fields (two columns) instead of in a collapsing section. Problems listed as a DANGER row.
- [ ] Commit: `feat(2.0): VHI movement chips; ControlMapEditor cards, one Save, side-by-side TOML`.

### Task G — Force tracking (`TrackingTask`)
Files: `myogestic/widgets/tracking.py`, its tests.
- [ ] One card: header `Force tracking` + dot; Stream and Channel side by side (captions above);
  one calibration row (surface tone, dot, mono `zero 0.12 · MVC 3.40`, **Zero** and **MVC** buttons;
  uncalibrated → WARNING row *Capture zero, then MVC*; MVC countdown shown in that row); one target
  row (a small trapezoid sketch, mono `2·3·5·3·2 s · 40 % · 5 reps`, a settings button whose popover
  holds the five durations, Level, Reps and Look ahead in a two-column grid); `primary_button`
  **Start**; running → SUCCESS row *Rep 2 of 5 · hold* over mono `61 % MVC · error +3 %` + **Stop**,
  the setup dimmed; the plot with Target/Force legend chips; a mono summary line. No
  `separator_text`, no `label_column`.
- [ ] Commit: `feat(2.0): TrackingTask as one card with a calibration row and target popover`.

### Task H — Start without a display
Files: `myogestic/core.py` (window setup in `App.run`), a test.
- [ ] Today any app segfaults at startup when macOS reports no active display (screen locked, display
  asleep): HelloImGui's `WinPositionCentered` reads an empty monitor list. Before running, detect the
  no-monitor case and avoid centring (e.g. an explicit window position mode/coordinates), so the app
  starts. Test with the monitor query monkeypatched to return none.
- [ ] Commit: `fix: start apps when no display is active instead of crashing`.

### Task I — The 2.0 language in the docs
Files: `docs/concepts/visual-language.md` only.
- [ ] Add a section **The 2.0 kit** describing each pattern of canvas board 1 with the helper that
  draws it (`panel_header`, `tinted_row`, `primary_button`, `destructive_button`, chips with
  `push_selected`, one-line rows, settings popover, captions above controls, empty/locked states,
  state colours including "unattached is IDLE"), with a short runnable snippet only where the docs
  test can run it. Keep existing sections consistent with it (fix any that contradict).
- [ ] Commit: `docs: the 2.0 kit in the visual language`.
