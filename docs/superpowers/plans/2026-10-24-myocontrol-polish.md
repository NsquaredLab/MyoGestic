# Myocontrol Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this run each task is dispatched to one Codex worker by an Orca coordinator; do **only your task**.

**Goal:** Panels that are not half empty, a signal toolbar that is not two dense rows, a slim header and status bar.

**Architecture:** Three library changes in disjoint files (signal toolbar; recorded-time data + session list; bare grid areas, step connectors, participant dialog), then one example task that composes them in `myocontrol.py`.

**Tech Stack:** Python 3.12+, imgui-bundle, pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-10-24-myocontrol-ux-design.md` (the base design) and the polish canvas "Myocontrol Polish Pass" (https://claude.ai/artifact/M6CN4hbDQ69tDEfGx7UW1T, private; each task below describes what it shows). The earlier plan `docs/superpowers/plans/2026-10-24-myocontrol-ux.md` has the Global Constraints this plan inherits verbatim.

## Global Constraints

All of `docs/superpowers/plans/2026-10-24-myocontrol-ux.md` → Global Constraints, plus:

- Base: `feat/myocontrol-ux`. Nothing that is reachable today may become unreachable; it may move one click deeper.
- Full suite: `uv run --extra grpc --extra dev pytest -q`. If `tests/test_recording_race.py::test_clear_after_detach_does_not_crash_acquire_loop` holds the run past ~5 minutes under machine load, deselect it, run that file alone, report both lines.
- No AI attribution in commits.

## Review Focus

1. **Every toolbar control still works after it moves into a popup** — Window, Detail, 1:1, Gain, Artifact, Per channel, Rescale, Notch, View, All/None/Invert/Edit, stats (Task 1, `test_every_control_reachable`).
2. **A take with no labels, or labels outside the sample range** → `class_seconds` is `{}` or clipped, never negative (Task 2, `test_class_seconds_edge_cases`).
3. **Old sessions without `duration_s` / `class_seconds`** still list and train (Task 2, `test_old_session_without_seconds`).
4. **Switching participant while the auto-scanned list is showing** → the list shows only the new participant's takes, unticked (Task 2, `test_autoscan_follows_participant`).
5. **A bare grid area still clips its content** to its cell (Task 3, `test_bare_area_clips`).

---

### Task 1: one-row signal toolbar with Display and Channels popups

**Files:** `myogestic/widgets/signals/_controls.py`, `myogestic/widgets/signals/viewer.py`, existing signal-viewer tests that assert on the old rows, new `tests/test_signal_toolbar.py`, `docs/concepts/visual-language.md` (one line), `CHANGELOG.md`.

**Canvas:** header row = title on the left; on the right Pause, View, Scale (Auto | Manual), `8/8 ch ▾`, `Display`. Below it only the plot, and one muted right-aligned line `2048 Hz · 120 fps`.

- **Header controls** (same row as the panel title, right-aligned, dropping to a second line only if the panel is too narrow): Pause/Play (existing transport), View (existing combo: Raw, Rectified, DC removed, RMS envelope — keep the combo, label it in the button: `Raw ▾`), Scale `segmented` Auto | Manual, a `{enabled}/{total} ch` button that opens the **Channels** popup, and a `Display` button (`ICON_FA_SLIDERS`, wrapped in `push_selected`/`pop_selected` while its popup is open).
- **Channels popup:** the existing All / None / Invert / Edit… (grid window) and the channel bar chips. The stream combo and the reconnect button appear in the header only when `selectable` and the app has more than one stream.
- **Display popup**, grouped with `panel_header`-style group titles: **Time** — Window, Detail, 1:1. **Amplitude** — Gain, Artifact, Lanes (`segmented` Shared | Per channel, replacing the checkbox), Rescale now. **Display filter** — Notch (`segmented` Off | 50 Hz | 60 Hz) with the muted line "Changes the plot only. The recorded signal's notch is set where the device is connected." **Footer** — the old stats line (`buf …`, `MinMax …`) in mono, plus the Show stats toggle.
- The plot footer shrinks to one muted line: `{fs:g} Hz · {fps:.0f} fps`.
- `show_controls=False` keeps its meaning (header controls and popups hidden, title + collapse toggle stay). Popups via `imgui.open_popup`/`begin_popup`, ids scoped by `widget_id`. Manual scale's range inputs, when Manual is selected, appear in the Display popup's Amplitude group.

- [ ] Write failing tests in `tests/test_signal_toolbar.py`: `test_header_is_one_row(imgui_frame)` (render a connected viewer at 900 px wide; the plot's top y is within one frame height + spacing of the title row — assert via the cursor y you can read after the header, or expose a private `_last_header_height` the test reads), `test_display_popup_opens(imgui_frame)` (simulate a click on Display; next frame the popup is open; the button is drawn selected), `test_every_control_reachable(imgui_frame)` (open each popup and assert each control's id is submitted: use `imgui.get_id`/item tracking or a module-level registry the implementation fills only in tests — pick the simplest that works with the existing `imgui_frame` fixture), `test_stream_picker_only_with_two_streams`.
- [ ] Run, see them fail; implement; update the old tests that pinned the two rows (change the assertion, never delete coverage); run the file, `tests/test_visual_language.py`, ruff, full suite.
- [ ] Commit: `feat(viewer): one-row signal toolbar with Display and Channels popups`.

---

### Task 2: recorded time per gesture, and a session list that fills itself

**Files:** `myogestic/session/_core.py`, `myogestic/session/__init__.py`, `myogestic/widgets/training/_session_state.py`, `myogestic/widgets/training/session_manager.py`, `myogestic/widgets/panels/recording.py`, `tests/test_recorded_time.py`, `tests/test_session_manager_participant.py`, `tests/test_public_api.py`, `CHANGELOG.md`.

**Interfaces (produced, Task 4 consumes):**
- `meta.json` gains `"duration_s": float` (last minus first sample timestamp of the first stream with samples) and `"class_seconds": {class_name: float}` when there are class names and at least one label. Label `i` lasts from its timestamp to the next label's timestamp, the last one to the last sample timestamp; intervals are clipped to `[first, last]` sample time; `class_index == -1` is not counted. Labels and samples share the `mne_lsl` `local_clock` (see `Session.add_label`). No schema bump: new optional keys.
- `myogestic.session.recorded_time(folder: str | Path) -> RecordedTime`, `@dataclass(frozen=True) class RecordedTime: takes: int; total_s: float; per_class: dict[str, float]` — sums every session folder / archive directly in `folder` (non-recursive, same discovery as `scan_sessions`); sessions without the new keys count as takes with 0 s. Missing folder → `RecordedTime(0, 0.0, {})`.
- `SessionManager.ui(participant=...)`: when a participant is set, the list **fills itself** with that participant's takes (scan `base/participant` on participant change and after each recorded take), rows **unticked** except takes registered by `add_recorded_session` (still ticked). With `participant=None` behaviour is exactly today's (empty until Scan). Empty list with a participant: centred muted text "No takes for {ID} yet." + "Takes you record appear here, already ticked for training." and a small "Load files from elsewhere…" link-button (the existing file dialog). Each row: name in mono, duration `m:ss` right-aligned, and one small chip per class with its seconds (`Rest 0:14`), chip colour = `PALETTE[class_index]` at low alpha with readable text — chips are categorical identity, so PALETTE is the right token.
- `RecordingControls`: gesture buttons in a 2-column grid filling the width, height `ui_px(44)`; Record/Stop full width, height `ui_px(44)`; status pill stays. Pure layout; behaviour unchanged.

- [ ] Failing tests: `test_meta_has_duration_and_class_seconds(tmp_path)` (record with two labels at known timestamps, stop, read meta), `test_class_seconds_edge_cases` (no labels → no key; label before first sample → clipped; `-1` ignored), `test_recorded_time_sums_folder(tmp_path)`, `test_old_session_without_seconds(tmp_path)` (hand-written meta without the keys lists and sums as 0 s), `test_autoscan_follows_participant(tmp_path)`, `test_no_participant_stays_empty_until_scan`, `test_recording_controls_layout(imgui_frame)` (renders; gesture buttons share a row).
- [ ] Implement, run file + ruff + full suite.
- [ ] Commit: `feat(session): recorded time per gesture and a participant list that fills itself`.

---

### Task 3: bare grid areas, step connectors, participant dialog

**Files:** `myogestic/grid.py`, `myogestic/widgets/panels/step_bar.py`, `myogestic/widgets/panels/participant.py`, `tests/test_grid.py` (or `tests/test_responsive_layout.py`), `tests/test_step_bar.py`, `tests/test_participant_panel.py`, `docs/concepts/grid-layout.md` (a short "bare areas" paragraph with a runnable example — docs blocks are executed), `CHANGELOG.md`.

**Interfaces (produced, Task 4 consumes):**
- `Grid.areas(template, *, row_height=..., col_width=..., bare: Iterable[str] = ())`: areas named in `bare` draw with no border and a transparent background (still a child window, still clipped, same padding rules). Unknown names in `bare` raise `ValueError` naming them. `Layout` passes through unchanged.
- `StepBar`: a short hairline connector (`ui_px(24)` wide, 1 px, `hairline()`) between consecutive steps, drawn in `SUCCESS` at reduced alpha when the step on its left is done. Steps keep their behaviour.
- `ParticipantPanel`:
  - Dialog layout: a label column on the left (`ui_px(120)`, `muted()`), inputs on the right with hidden labels (`##`), a thin separator between the ID and the names, under the names one muted line with `ICON_FA_LOCK`: "Stays on this computer, in the key file. Never in a recording.", the preview block in the mono font on `CONSOLE_BG`, Cancel and Start session right-aligned.
  - `open() -> None`: request the modal on the next `ui()` (used by a "Set participant" button elsewhere); ignored while `ctx.state != "idle"`.
  - On a successful start, `ctx.log(f"Participant {pid} · saving to sessions/{pid}/")` — the ID only.

- [ ] Failing tests: `test_bare_area_has_no_border(imgui_frame)`, `test_bare_area_clips(imgui_frame)`, `test_bare_rejects_unknown_area`, `test_step_connectors_render(imgui_frame)`, `test_open_requests_modal(imgui_frame)`, `test_start_logs_id_only(tmp_path)` (no name in `ctx.logs`), `test_dialog_labels_left(imgui_frame)` (render; no exception — layout is visual).
- [ ] Implement, run files + ruff + full suite.
- [ ] Commit: `feat(widgets): bare grid areas, step connectors, a calmer participant dialog`.

---

### Task 4: myocontrol composes the polish

Depends on Tasks 1–3.

**Files:** `examples/start_here/myocontrol.py`, `tests/test_myocontrol_wiring.py`, `CHANGELOG.md` (one line for the myocontrol redesign as a whole — it has none yet).

- **Header:** one area `header` spanning the full width, `Px(52)`, in `bare`. Inside, vertically centred on one line: `MyoGestic` in `display_font()` at `ui_px(22)` + `Myocontrol` muted; `StepBar` centred in the remaining width; participant chip + state `status_pill` right-aligned (measure after `same_line`, see visual-language "Four ways a row lies to you").
- **Status bar:** area `status`, `Px(26)`, in `bare`; one line, ellipsized: `● emg · 8 ch / 2048 Hz · P-001 · sessions/P-001 · Model: …`, the dot in `SUCCESS`/`IDLE`.
- **Record step:**
  - No participant → a centred lock card: `ICON_FA_LOCK` in `WARNING`, "Set a participant to record", one muted line, `primary_button("Set participant")` calling `participant.open()`.
  - With a participant → `RecordingControls`, then a "Recorded for {ID}" block on `Col_.popup_bg` (`panel_header` + `{takes} takes · m:ss` right-aligned, one bar per class from `recorded_time(Path("sessions", ID))`, bar fill `PALETTE[i]`, value `m:ss`), refreshed when the state goes recording → idle (not every frame); an empty participant shows the block with "Nothing yet. Each gesture's recorded time shows here as you go." Then one muted line: "Pick the gesture the hand shows, press Record, switch gestures as the participant moves, then Stop."
- **Train / Drive:** keep the tooltips, and also draw the reason under a disabled `primary_button` as one muted line with a `WARNING` `ICON_FA_CIRCLE_INFO`.
- **Sessions:** unchanged call (`sessions.ui(participant=ctx.participant)`) — Task 2 makes it fill itself.

- [ ] Failing tests: `test_header_is_one_bare_area`, `test_status_is_one_bare_area`, `test_record_locked_without_participant(imgui_frame)` (render Record step with no participant; clicking the button calls `participant.open`), `test_recorded_block_reads_disk(tmp_path, imgui_frame)`, plus keep every existing wiring test green.
- [ ] Implement, run wiring/examples tests + ruff + full suite. Do not launch the GUI (the coordinator drives it).
- [ ] Commit: `feat(examples): myocontrol polish — slim header, filled steps, one-line status`.

## Waves

| Wave | Tasks | Files |
| --- | --- | --- |
| A | 1, 2, 3 | disjoint (signals/ · session/ + training/ + recording.py · grid.py + step_bar.py + participant.py); each adds one CHANGELOG line, the coordinator merges them |
| B | 4 | myocontrol.py and its test |
