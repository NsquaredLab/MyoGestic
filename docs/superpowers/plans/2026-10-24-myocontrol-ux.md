# Myocontrol UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this run each task is dispatched to one Codex worker by an Orca coordinator; do **only your task**.

**Goal:** Participant-labelled files, corner-toast notifications, and a Connect → Record → Train → Drive myocontrol layout.

**Architecture:** Library pieces first (participant + labelled naming in `myogestic.session`/`core`, `ctx.notify` + an overlay the `App` draws itself, `StepBar`/`primary_button`/`ParticipantPanel` widgets), then the examples regroup existing widgets around them. Everything is opt-in; apps that do not set a participant behave byte for byte as before.

**Tech Stack:** Python 3.12+, imgui-bundle (imgui/implot/hello_imgui), zarr, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-10-24-myocontrol-ux-design.md` — read it before your task; the plan argues from it.

## Global Constraints

- Base: `feat/myocontrol-ux` (= `main` with `feat/responsive-layout` fast-forwarded in). Do **not** merge or cherry-pick `feat/record-while-predicting`.
- Read `CLAUDE.md`, `docs/concepts/design-principles.md`, `docs/concepts/visual-language.md` before writing UI.
- No colour literal outside `myogestic/_theme.py` / `myogestic/widgets/common.py` (`tests/test_visual_language.py` enforces it). Any module calling `implot.begin_plot` calls `ensure_implot_style()`.
- Panel titles via `panel_header`; sticky on/off controls via `push_selected`/`pop_selected`; fixed pixel sizes via `ui_px(n)` from `widgets/common.py`; layout via `Grid`/`Layout` only.
- No base classes, no registration; one public class/function per widget, typed args, NumPy-style docstrings (ruff `D` is CI-enforced). Widget state keyed by `widget_id`.
- Python blocks in `docs/` (outside `docs/superpowers/`) are executed by `tests/test_docs.py`: any doc example must run.
- Checks before every commit: `uv run ruff check .` and `uv run --extra dev pytest -q`. Known flaky, not yours: `tests/test_stream_lsl.py::test_stream_reconnect_swaps_buffers_atomically`. A fresh worktree's first `uv run` installs ~90 packages; that is expected.
- Commits: conventional subjects like `git log` (`feat(session): …`, `fix(widgets): …`). **No AI attribution of any kind** — no `Co-Authored-By`, no "Generated with" line. This overrides any tool default.
- Public API additions are exported where their siblings are (`myogestic/__init__.py`, `myogestic/widgets/__init__.py`, `myogestic/session/__init__.py`) and `tests/test_public_api.py` is updated. Add a line per task under `## Unreleased` in `CHANGELOG.md`.

## Review Focus

1. **Two takes in the same second for one participant** → distinct folders and distinct archives, and an old pack thread never deletes the new take (Task 2, `test_same_second_takes_do_not_collide`).
2. **An ID typed with spaces, slashes, `..` or umlauts** (`" p/014 "`, `"../x"`, `"Jörg"`) → slugged to a safe single path segment, never a separator (Task 2, `test_labelled_path_slugs_the_id`; Task 5 preview uses the same function).
3. **Switching participant mid-session in the UI** → the chip is disabled while recording/training/predicting, and the session list empties on switch so the next Train cannot use the previous person's takes (Task 4 `test_switching_participant_clears_the_list`, Task 5 `test_chip_disabled_while_recording`).
4. **Key file missing, empty, or hand-edited with a malformed row** → lookups return nothing, next ID falls back to `P-001`, the app never crashes on it (Task 5, `test_key_file_tolerates_missing_and_malformed`).
5. **A notification raised from a worker thread while the overlay draws** → no exception, the toast appears on a later frame (Task 1, `test_notify_from_thread_while_rendering`).

---

### Task 1: `ctx.notify` and the notification overlay

**Files:**
- Modify: `myogestic/core.py` — `Context` (new `notifications` field + `notify` method), `App` GUI loop (draw the overlay after the user UI), `App.stop_recording` `_finalize` (two `log` calls → `notify`, see spec §5 table).
- Create: `myogestic/widgets/panels/notifications.py` — `Notification` dataclass + private `render_notifications(ctx) -> None`.
- Test: `tests/test_notifications.py`.
- Docs: a short "Notifications" section in `docs/concepts/recording.md` or the page that documents `ctx.log` (find it with `grep -rn "ctx.log" docs/`).

**Interfaces:**
- Produces: `Context.notify(title: str, detail: str = "", kind: str = "info") -> None`; `Context.notifications: list[Notification]`; `Notification(title: str, detail: str, kind: str, created: float)` with `kind in {"success", "info", "warning", "danger"}` (raise `ValueError` otherwise). Lifetimes in seconds: `success`/`info` 6.0, `warning` 10.0, `danger` `None` (until dismissed).
- Do **not** touch `myogestic/ml/pipeline.py` or `App.start_recording` (Tasks 2 and 4 own them).

- [ ] **Step 1: Write the failing tests** in `tests/test_notifications.py`:
  - `test_notify_appends_and_mirrors_to_log`: `ctx.notify("Recording saved", "a.session.zip", "success")` → one `Notification` with those fields; `ctx.logs[-1]` ends with `"Recording saved — a.session.zip"`. Without detail the log line ends with just the title.
  - `test_notify_rejects_unknown_kind`: `kind="oops"` raises `ValueError`.
  - `test_expiry_by_kind`: with `time.monotonic` patched, a `success` toast is gone from the overlay's visible set after 6.0 s, a `warning` after 10.0 s, a `danger` never.
  - `test_at_most_three_visible`: five notifications → the renderer draws the newest three; all five lines are in `ctx.logs`.
  - `test_overlay_renders_headless(imgui_frame)`: `render_notifications(ctx)` with one of each kind draws without error.
  - `test_notify_from_thread_while_rendering(imgui_frame)`: a thread calls `notify` 200 times while frames render; no exception.
  - `test_stop_recording_notifies_saved(tmp_path)`: record + stop (reuse `_recorded_app` pattern from `tests/test_record_button.py`), wait for the pack thread; a `success` notification titled `"Recording saved"` exists.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_notifications.py -q` — expect FAIL (no `notify`).
- [ ] **Step 3: Implement.** `notify` validates kind, appends, then calls `self.log(...)`. The renderer prunes expired items on the UI thread (hover pauses: when a toast's window is hovered, shift its `created` forward by the frame delta), anchors one auto-resize window to the bottom-right of `imgui.get_main_viewport()` work area with margin `ui_px(18)` and width `ui_px(372)`, flags: no decoration, no focus on appearing, no nav, no saved settings, no docking. Per toast: a filled circle in `SUCCESS`/`INFO`/`WARNING`/`DANGER`, bold-ish title, `detail` in `muted()`, `ICON_FA_XMARK` dismiss (`imgui.small_button`). The `App` calls it lazily (`from myogestic.widgets.panels.notifications import render_notifications`) right after the user `@app.ui` callbacks each frame.
- [ ] **Step 4: Run** the test file, then `uv run ruff check .` and the full suite — expect PASS.
- [ ] **Step 5: Commit** `feat(core): ctx.notify and a corner toast overlay the App draws itself`.

---

### Task 2: participant on the context, labelled session names, the Record gate

**Files:**
- Modify: `myogestic/session/_core.py` — `labelled_path`, `_unique_stem`, `Session.__init__(base_path="sessions", participant="")`, `save_meta` writes `"participant"`.
- Modify: `myogestic/session/_io.py` — `open_session_store` sets `session.participant` (`""` when absent).
- Modify: `myogestic/session/__init__.py` — export `labelled_path`.
- Modify: `myogestic/core.py` — `Context.participant: str = ""` and `Context.require_participant: bool = False` (+ docstring attributes), `App.__init__(..., require_participant: bool = False)` copies it to `self.ctx.require_participant`, `App.start_recording` passes `participant=self.ctx.participant` and enforces the gate.
- Modify: `myogestic/widgets/panels/recording.py` — `RecordingControls` and `RecordButton` draw Record disabled with a hover reason when gated.
- Test: `tests/test_participant_labels.py`.

**Interfaces:**
- Produces: `labelled_path(base_path: str | Path, participant: str = "", suffix: str = "") -> Path` (no filesystem side effects; returns `base/<ID>/<ID>_<YYYY-MM-DD_HH-MM-SS>[_<suffix>]`, or `base/<YYYY-MM-DD_HH-MM-SS>` + nothing when the slugged ID is empty — the legacy uuid8 tail stays Session's job). `Session.participant: str`. `Context.participant: str`. `Context.require_participant: bool` (set from `App(require_participant=)`; widgets read it off `ctx`).
- Gate message (exact): status `"Set a participant ID before recording."`. Until Task 1 lands on your base, use `ctx.log`; if `ctx.notify` exists on your base, call `ctx.notify("Recording refused", "Set a participant ID first.", "warning")` too.
- Do **not** touch the overlay, `_finalize`, or `myogestic/ml/`.

- [ ] **Step 1: Write the failing tests** in `tests/test_participant_labels.py`:
  - `test_labelled_path_with_and_without_id`: with `time.strftime` frozen to `2026-10-24_15-12-03`: `labelled_path("sessions", "P-014")` == `Path("sessions/P-014/P-014_2026-10-24_15-12-03")`; with `suffix="model.joblib"` ends `_model.joblib`; `labelled_path("sessions")` == `Path("sessions/2026-10-24_15-12-03")`.
  - `test_labelled_path_slugs_the_id`: `" p/014 "`, `"../x"`, `"Jörg"` each give a path whose parent under `sessions` is exactly one segment with no `/`, `\` or `..`.
  - `test_session_without_participant_keeps_legacy_layout`: `Session(str(tmp_path)).path.name` matches `^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_[0-9a-f]{8}$`.
  - `test_session_with_participant_nests_and_labels`: `Session(str(tmp_path), participant="P-014").path` == `tmp_path/"P-014"/"P-014_<ts>"`.
  - `test_same_second_takes_do_not_collide`: frozen clock, two Sessions for `P-014` → paths `…_15-12-03` and `…_15-12-03-2`; after packing the first, a third Session does not reuse `…_15-12-03` (the zip still exists).
  - `test_meta_records_participant_not_names`: record + stop as `P-014`; archive `meta.json["participant"] == "P-014"`; open with `open_session_store` → `.participant == "P-014"`; an old-style session without the key opens with `.participant == ""`.
  - `test_require_participant_refuses_without_id`: `App("t", require_participant=True)`, connected stream, `start_recording()` → state stays `"idle"`, no folder created under `tmp_path`, `ctx.status_message == "Set a participant ID before recording."`; after `ctx.participant = "P-014"` it records into `tmp_path/"P-014"`.
  - `test_record_button_disabled_when_gated(imgui_frame)`: render `RecordingControls` with the gate on and no participant; clicking (simulate as the existing recording widget tests do) does not start recording.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** `_unique_stem(parent: Path, stem: str) -> str`: return `stem`, else `stem-2`, `stem-3`, … for the first candidate where neither `parent/candidate` nor any `parent.glob(f"{candidate}*.session.zip")` exists. `Session.__init__` with a participant: `parent = base/<slug>`; `parent.mkdir(parents=True, exist_ok=True)`; then `(parent/_unique_stem(...)).mkdir(exist_ok=False)`, retrying `_unique_stem` on `FileExistsError`. Without a participant: today's code unchanged. Reuse `_slug` for the ID.
- [ ] **Step 4: Run** the file, ruff, full suite — expect PASS (existing `test_session_pack.py`, `test_record_button.py`, `test_recording_race.py` must stay green untouched).
- [ ] **Step 5: Commit** `feat(session): participant-labelled sessions and an opt-in Record gate`.

---

### Task 3: `StepBar`, `primary_button`, light-theme contrast

**Files:**
- Create: `myogestic/widgets/panels/step_bar.py` — `StepBar`.
- Modify: `myogestic/widgets/common.py` — `PRIMARY_FILL`, `ON_PRIMARY_TEXT`, `primary_button`.
- Modify: `myogestic/_theme.py` — light `text_dim` alpha `153` → `199`.
- Modify: `myogestic/widgets/__init__.py`, `myogestic/widgets/panels/__init__.py` exports; `docs/concepts/visual-language.md` (one row for `primary_button` under State cues or Panels; note the token).
- Create: `examples/panels/step_bar.py` (the `panels/` convention: one widget, standalone).
- Test: `tests/test_step_bar.py`.

**Interfaces:**
- Produces: `StepBar(steps: list[str], *, widget_id: str = "steps")`, `StepBar.ui(done: list[bool]) -> int` (active index; `len(done)` must equal `len(steps)`, else `ValueError`). `primary_button(label: str, size: tuple[float, float] = (0, 0)) -> bool`. `PRIMARY_FILL = imgui.ImVec4(0 / 255, 98 / 255, 204 / 255, 1.0)`, `ON_PRIMARY_TEXT = imgui.ImVec4(1.0, 1.0, 1.0, 1.0)`; hover/active fills derived in `primary_button` by lightening `PRIMARY_FILL`, defined in `common.py`.
- Do **not** touch `core.py`, `session/`, `ml/`.

- [ ] **Step 1: Write the failing tests** in `tests/test_step_bar.py`:
  - `test_step_bar_defaults_to_first_step(imgui_frame)`: `StepBar(["A","B"]).ui([False, False]) == 0`.
  - `test_step_bar_click_selects(imgui_frame)`: simulate a click on the second button (mouse pos + down/up over two frames, as `tests/test_control_map_editor.py` does) → next `ui` returns `1`; push/pop stay balanced on the click frame (no ImGui assertion).
  - `test_step_bar_state_is_per_widget_id(imgui_frame)`: two bars with different ids keep different selections.
  - `test_step_bar_rejects_mismatched_done`: `ValueError`.
  - `test_primary_button_renders(imgui_frame)`: returns `False` without a click, no style stack leak (`imgui.get_style()` colours unchanged after).
  - `test_light_text_dim_alpha`: after applying the light theme, `Col_.text_disabled` alpha ≈ `199/255`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** Step button content: `f"{n}  {label}"` or `f"{ICON_FA_CHECK}  {label}"` (the check drawn in `SUCCESS` via `text_colored` before the label, same line); buttons `same_line()` with `ui_px(4)` spacing; active one wrapped in `push_selected`/`pop_selected` guarded on the value read **before** the button (visual-language "push/pop guarded at push time").
- [ ] **Step 4: Run** file, `tests/test_visual_language.py`, ruff, full suite — expect PASS.
- [ ] **Step 5: Commit** `feat(widgets): StepBar, primary_button, and readable muted text on light`.

---

### Task 4: model auto-save, training notifications, sessions that follow the participant

Depends on Tasks 1 and 2 being on your base.

**Files:**
- Modify: `myogestic/ml/pipeline.py` — `Pipeline.autosave_dir: str | None = None`; `start_training` worker: auto-save + `notify` per spec §4/§5.
- Modify: `myogestic/widgets/training/session_manager.py`, `myogestic/widgets/training/_session_state.py` — `SessionManager.ui(participant: str | None = None)`.
- Test: `tests/test_ml_autosave.py`, `tests/test_session_manager_participant.py`.

**Interfaces:**
- Consumes: `ctx.notify` (Task 1), `labelled_path`, `ctx.participant` (Task 2), existing `save_pickle`.
- Produces: `Pipeline.autosave_dir`; `Pipeline.last_saved_model: str | None` (path of the last auto-save, for the status bar). `SessionManager.ui(participant: str | None = None) -> TrainingData`.

- [ ] **Step 1: Write the failing tests:**
  - `test_autosave_writes_labelled_model(tmp_path)`: `pipeline.save_model = save_pickle`, `autosave_dir = str(tmp_path)`, `ctx.participant = "P-014"`, a trivial `@pipeline.train`; after training (join the thread or poll state back to `"idle"`) one file matches `tmp_path/"P-014"/"P-014_*_model.joblib"`, `last_saved_model` points at it, and a `success` notification `"Training finished"` has its file name as detail.
  - `test_no_autosave_without_dir`: `autosave_dir=None` → no file written, still a `"Training finished"` notification (detail: elapsed seconds, e.g. `"in 0.0 s"`).
  - `test_autosave_failure_keeps_model`: `save_model` raises → `pipeline.model` is set, a `danger` notification exists, state returns to `"idle"`.
  - `test_training_failure_notifies_danger`: train raises → `danger` `"Training failed"` with the error text.
  - `test_switching_participant_clears_the_list(tmp_path)`: two takes under `P-014`, one under `P-015`; `ui(participant="P-014")` + Scan lists 2; `ui(participant="P-015")` lists 0 until Scan, then 1.
  - `test_recorded_take_registers_under_participant(tmp_path)`: `add_recorded_session(<P-014 zip>)` makes it selected in the manager rendered with `participant="P-014"`.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** The manager remembers the last participant in its `SessionWidgetState` (new field `participant: str | None = None`); on change it clears `sessions` and `deactivated_classes`. `render_summary_and_buttons` scans `Path(base_path) / participant` when one is set.
- [ ] **Step 4: Run** files, ruff, full suite — expect PASS.
- [ ] **Step 5: Commit** `feat(ml): auto-save the trained model under the participant label`.

---

### Task 5: `ParticipantPanel` and the pseudonymisation key file

Depends on Tasks 2 and 3 being on your base.

**Files:**
- Create: `myogestic/widgets/panels/participant.py` — `ParticipantPanel` + private key-file helpers.
- Modify: widget exports; `docs/api/widgets.md` entry; `examples/panels/participant_panel.py`.
- Test: `tests/test_participant_panel.py`.

**Interfaces:**
- Consumes: `labelled_path`, `_slug`, `ctx.participant` (Task 2); `primary_button` (Task 3).
- Produces: `ParticipantPanel(*, key_file: str | Path = "~/myogestic/participant-key.csv", widget_id: str = "participant")`, `ParticipantPanel.ui(ctx) -> None` (draws the header chip; opens the modal). Private, tested directly: `_lookup(key_file: Path, first: str, family: str) -> str | None`, `_next_id(key_file: Path) -> str`, `_append(key_file: Path, pid: str, first: str, family: str) -> None`.
- Key file: stdlib `csv`, header `id,first_name,family_name,created` (`created` = ISO date). `_next_id`: max `N` over ids matching `^P-(\d+)$`, plus one, formatted `P-{N:03d}`; `P-001` when none. Matching folds case and accents (`unicodedata.normalize("NFKD")`, drop combining marks).

- [ ] **Step 1: Write the failing tests:**
  - `test_next_id_and_append(tmp_path)`: empty → `P-001`; after `_append(k, "P-014", "Jane", "Doe")` → `P-015`.
  - `test_lookup_folds_case_and_accents(tmp_path)`: row `P-007, Jörg, Müller` found by `("jorg", "MULLER")`.
  - `test_key_file_tolerates_missing_and_malformed(tmp_path)`: missing file → `_lookup` `None`, `_next_id` `P-001`; a file with a short row and a non-`P-` id → no exception, malformed rows ignored.
  - `test_start_sets_participant_and_writes_key_only(tmp_path, imgui_frame)`: drive the modal's start path (call the panel's internal start method the implementation exposes as `_start(ctx, pid, first, family)`); `ctx.participant == "P-014"`; key file has the row; nothing under the sessions folder contains `"Jane"` or `"Doe"`.
  - `test_chip_disabled_while_recording(imgui_frame)`: with `ctx.state = "recording"`, clicking the chip does not open the modal.
  - `test_panel_renders(imgui_frame)`: chip with and without a participant renders.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement.** Modal via `imgui.open_popup`/`begin_popup_modal` with id from `widget_id`. Inputs: ID (prefilled `_next_id`), first, family. Typing a first+family that `_lookup` finds fills the ID and shows "Returning participant" in `muted()`. Preview lines via `labelled_path(<sessions>, slug(id))` (the panel takes no sessions path: show it relative, `sessions/<ID>/<ID>_<now>…`). Start = `primary_button("Start session")`, disabled while `_slug(id) == ""`. Chip: `ID` in `mono_font()`, local name in `muted()`, or `"Set participant"` in `WARNING` when empty; disabled with a hover reason while `ctx.state != "idle"`. Names live only in widget memory and the key file.
- [ ] **Step 4: Run** file, ruff, full suite — expect PASS.
- [ ] **Step 5: Commit** `feat(widgets): ParticipantPanel with a local pseudonymisation key file`.

---

### Task 6: myocontrol redesigned around the steps

Depends on Tasks 1–5.

**Files:**
- Modify: `examples/start_here/myocontrol.py`.
- Modify: `tests/test_myocontrol_wiring.py` (extend), `examples/start_here/README.md` (one line: participant + steps).

**Interfaces:**
- Consumes everything above: `App(require_participant=True)`, `pipeline.save_model = save_pickle`, `pipeline.autosave_dir = "sessions"`, `StepBar`, `ParticipantPanel`, `primary_button`, `SessionManager.ui(participant=ctx.participant)`, `ctx.notify`, `Layout`/`Grid.areas` (see `examples/synthetic/emg_32ch_multi_model.py` for the pattern).

- [ ] **Step 1: Extend `tests/test_myocontrol_wiring.py`** (keep its existing assertions):
  - `test_myocontrol_requires_participant`: the module's `app.ctx.require_participant is True`.
  - `test_myocontrol_autosaves_models`: `pipeline.autosave_dir == "sessions"` and `pipeline.save_model is save_pickle`.
  - `test_myocontrol_steps`: the module exposes `steps` with labels `["Connect", "Record", "Train", "Drive"]`.
  - `test_myocontrol_renders_each_step(imgui_frame)`: for each step index, set the bar's active step and render the app UI one frame without error.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Rebuild the layout** per spec §7: header row (title in `display_font()`, `StepBar`, `ParticipantPanel` chip, state pill), body (signal over log | step panel over sessions), status bar. Wide and narrow `Grid.areas` in a `Layout`. Step panels exactly as the spec §7 table; move the mains notch to Connect, mode + `FeatureSelector` into Train beside a `primary_button(f"Train {mode.lower()}")`; Drive gets `primary_button` Start/Stop predicting (replicate `PredictButton`'s disabled-with-reason). Track a fingerprint of (mode, selected features, notch) at the moment Train is pressed; when it differs from the current one and a model exists, show the `WARNING` "Features changed — retrain to apply them." line. On a successful `_bind`, `notify("Virtual Hand connected", "Start predicting drives it.", "info")`. Remove the Model/Source/Streams/Hand tab bars; nothing positions itself outside the Grid.
- [ ] **Step 4: Run** the wiring tests, `tests/test_examples.py`, ruff, full suite — expect PASS. Then launch it once: `uv run --extra examples --extra grpc python examples/start_here/myocontrol.py` with the Synthetic device; set a participant, record one take, train, confirm the toast and the `sessions/<ID>/` files; quit.
- [ ] **Step 5: Commit** `feat(examples): myocontrol as Connect, Record, Train, Drive with participant labels`.

---

### Task 7: force_ramps and pong adopt the participant

Depends on Tasks 2 and 5. Parallel with Task 6.

**Files:**
- Modify: `examples/start_here/force_ramps.py`, `examples/start_here/pong.py`, `tests/test_force_ramps_wiring.py`, `tests/test_pong_wiring.py`, `examples/start_here/WINDOWS.md` (the walkthrough mentions what to click before Record — add "set the participant").

- [ ] **Step 1: Extend the two wiring tests:** each module's `app.ctx.require_participant is True` and it constructs a `ParticipantPanel`; one headless frame of each app's UI renders.
- [ ] **Step 2: Run** — expect FAIL.
- [ ] **Step 3: Implement:** `App(..., require_participant=True)`; a `ParticipantPanel` chip placed in each app's existing top/control area (a `Grid` cell it already has — do not restructure the layout).
- [ ] **Step 4: Run** the wiring tests, `tests/test_examples.py`, ruff, full suite — expect PASS.
- [ ] **Step 5: Commit** `feat(examples): force_ramps and pong label their recordings by participant`.

---

## Waves (for the coordinator)

| Wave | Tasks | Why |
| --- | --- | --- |
| 1 | 1, 2, 3 | Independent. 1 and 2 both add a `Context` field in `core.py` (adjacent lines); the coordinator resolves that textual conflict when merging. |
| 2 | 4, 5 | 4 needs 1+2; 5 needs 2+3. Disjoint files. |
| 3 | 6, 7 | Need everything; disjoint example files. |

Each worker branches from `feat/myocontrol-ux` as it stands at its wave's start; the coordinator reviews and merges each branch into `feat/myocontrol-ux` before the next wave.
