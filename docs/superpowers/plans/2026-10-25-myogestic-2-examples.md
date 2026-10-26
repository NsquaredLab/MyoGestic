# MyoGestic 2.0 Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every example composes the 2.0 widgets the way `examples/start_here/myocontrol.py` does, so no example still shows the pre-2.0 layout.

**Architecture:** The widgets are already 2.0 (plan `2026-10-25-myogestic-2-widgets.md`). This plan only changes how examples arrange them and the few example-local panels they draw by hand. No widget API changes; if an example needs one, ask the coordinator.

**Tech Stack:** Python 3, imgui-bundle, `myogestic.widgets`, `Grid`/`Px`/`Fr`.

**Spec:** `docs/concepts/visual-language.md` § "The 2.0 kit" (the contract) and the approved canvas https://claude.ai/artifact/Acesk6Cmo8cMVvpAbJ2pcr. Reference composition: `examples/start_here/myocontrol.py`.

## Global Constraints

- The kit table in `visual-language.md` § "The 2.0 kit" is the rule set: one card, one `panel_header`; state in a `tinted_row`; one full-width `primary_button` forward action; chips with `push_selected`/`pop_selected` instead of checkboxes; rare settings behind a `SLIDERS` popover; captions above controls (`imgui.text_colored(muted(), …)` + `imgui.begin_table`) instead of a header per field; `mono_text` for values.
- No raw `imgui.text` title, no `imgui.checkbox` toggle, no `separator_text`/`collapsing_header` section in an example-local panel.
- Several `panel_header`s stacked in one grid cell are sub-headers: fold them into one card with captions.
- A second amplifier is added through `DevicePicker(on_add=…, on_remove=…)` (as in `myocontrol.py`). Drop `StreamManager` and its "Streams" tab wherever that covers it. `examples/panels/stream_manager.py` stays — it is the StreamManager demo.
- A tab bar stays only where two full-cell views compete for one cell (e.g. Signal vs. Force). A tab bar that hides a panel which fits beside the others becomes cards.
- Behaviour and wiring do not change: what records, trains, predicts and pushes stays identical. Comments that explain wiring stay; comments about layout that no longer exists go.
- Layout only through `Grid` with `Px`/`Fr`. No colour literals. `ui_px` for fixed pixel sizes. NumPy docstrings; `uv run ruff check .` clean.
- Each example must still pass `tests/test_examples.py` (wires up, draws a frame, survives an unlaunchable target). Check light theme, UI scale 2.0 and the narrowest cell the grid gives.
- Update the folder `README.md` where it describes a layout you changed. Update a test only where it asserts the old layout (a tab label, a `StreamManager`); never weaken a wiring assertion.
- Commit message `examples: <group> on the 2.0 kit`. No AI attribution, no `Co-Authored-By`, no "Generated with".
- Full suite once at the end: `uv run --extra grpc --extra dev pytest -q --deselect tests/test_recording_race.py::test_clear_after_detach_does_not_crash_acquire_loop` (the coordinator runs that stress test).

## Review Focus

- A narrow right-hand cell (320 px at scale 2): folded cards must stack captions to one column, not clip.
- An example started with nothing connected: every card reads in words (`IDLE` "Not connected — …"), never a bare "(no data)".
- Recording in progress: controls that cannot change mid-take are disabled with a visible caption.
- Pong/force tabs: the first tab is the one a layout pass renders — keep the subject's view first.
- An unlaunchable VHI/target: example-local hand cards show an empty state with the next step.

---

### Task P1: start_here

**Files:** Modify `examples/start_here/force_ramps.py`, `examples/start_here/pong.py`, `examples/start_here/myocontrol.py` (only leftover raw `imgui.button`/`imgui.text`), `examples/start_here/README.md`. Tests: `tests/test_pong_wiring.py`, `tests/test_myocontrol_wiring.py`, `tests/test_examples.py`.

- [ ] force_ramps: `DevicePicker` takes `on_add`/`on_remove`; drop `StreamManager` and the Source/Streams tab bar (Source becomes one card). Keep the Signal/Force tab bar.
- [ ] pong: same `DevicePicker` change; the right column's Source/Streams/Hand tabs become cards or a two-tab bar per Global Constraints. Fold `model_ui`'s BLOCK/MODE/CONTROL/OPPONENT/PUSHED/CONTROL MAP headers into one card: captions above `segmented()` choices, state in `tinted_row`, block start as the one `primary_button`.
- [ ] myocontrol: replace any remaining raw `imgui.button`/`imgui.text` with kit helpers; no layout change.
- [ ] Run `uv run --extra grpc --extra dev pytest -q tests/test_examples.py tests/test_pong_wiring.py tests/test_myocontrol_wiring.py tests/test_layout_responsive.py` → pass; full suite once; commit.

### Task P2: synthetic EMG apps and OTB

**Files:** Modify `examples/synthetic/{emg_32ch_multi_model,emg_popout_layout,emg_classification,emg_classification_grpc,emg_regression,emg_regression_raulnet,high_channel_viewer,channel_grid_demo,electrode_overview,multi_panel_grids,my_device}.py`, `examples/otb/*.py`. Test: `tests/test_examples.py`.

- [ ] Each app's example-local panels (e.g. the `MODEL` panels in `emg_32ch_multi_model.py` / `emg_popout_layout.py`) become one card each per the kit; raw `imgui.button` forward actions become the card's `primary_button`.
- [ ] Shared range wherever several plots are compared (`electrode_overview`, `multi_panel_grids`, `channel_grid_demo`).
- [ ] Run `uv run --extra grpc --extra dev pytest -q tests/test_examples.py tests/test_docs.py` → pass; full suite once; commit.

### Task P3: control and hand examples

**Files:** Modify `examples/synthetic/{control_map_studio,vhi_control_hand,servo_hand,reference_target}.py`. Tests: `tests/test_control_map_studio.py`, `tests/test_examples.py`.

- [ ] control_map_studio: `DRIVE THE MAP` and `KEYBOARD` panels per the kit (chips instead of the checkbox, no `separator` sections); the maps tab bar stays (one map per tab is a competing full-cell view).
- [ ] vhi_control_hand: the `CONTROL HAND` panel is one card with a `tinted_row` state and one `primary_button`.
- [ ] Run `uv run --extra grpc --extra dev pytest -q tests/test_control_map_studio.py tests/test_examples.py` and, because these touch the control bus path, `uv run --extra grpc --extra dev pytest -m lsl_contention -q` → pass; full suite once; commit.

### Task P4: panel demos

**Files:** Modify `examples/panels/*.py` and `examples/panels/README.md`. Tests: `tests/test_examples.py`, `tests/test_app_logo.py`.

- [ ] Each demo shows its widget in its 2.0 default, with only demo controls the widget does not already have; `participant_panel.py`, `step_bar.py` and `pong.py` lose their raw `imgui.checkbox`/`imgui.text`/`imgui.button` demo controls in favour of chips and captions.
- [ ] Demos whose widget gained a parameter in the 2.0 plan use it where it is the point of the demo (`LinePlot(y_range=…)`, `RecordingControls(timed=…)`).
- [ ] Run `uv run --extra grpc --extra dev pytest -q tests/test_examples.py tests/test_app_logo.py tests/test_docs.py` → pass; full suite once; commit.

### Task P5 (coordinator): gallery screenshots

Needs an active display. After P1–P4 merge: `uv run python tools/widget_screenshot.py --all`, review every PNG in `docs/images/widgets/`, commit `docs: 2.0 widget gallery`.

## Phase 2b: one header everywhere (decided after reviewing the first shots)

The myocontrol header (logo line, title, step bar, participant chip, state pill) becomes the
`AppHeader` widget, and every example opens with it in a bare `Px(52)` row. Session apps pass a
`StepBar` and take the myocontrol shell (signal | step card, sessions, log); viewers, tools and
panel demos pass only a title. Standalone `AppLogo` image cells go. Examples are then converted
one at a time and reviewed with before/after screenshots: pong, force_ramps, the synthetic
session apps, sessantaquattro_app, then viewers, tools and panel demos.

### Task H1: `AppHeader`

**Files:** Create `myogestic/widgets/panels/app_header.py`, `examples/panels/app_header.py`, `tests/test_app_header.py`. Modify `myogestic/widgets/__init__.py`, `myogestic/widgets/common.py` (`edge_rule`), `examples/start_here/myocontrol.py`, `docs/api/widgets.md`.

**Interfaces — Produces:**
- `AppHeader(title: str, *, steps: StepBar | None = None, participant: ParticipantPanel | None = None, show_state: bool = True, widget_id: str = "app_header")`
- `AppHeader.ui(ctx: Context, done: list[bool] | None = None) -> int | None` — the active step, or `None` without steps.
- `edge_rule(*, bottom: bool) -> None` in `common.py` (moved from myocontrol's `_edge_rule`).

- [ ] Tests first: logo line drawn; with steps, `ui` returns `steps.active` and the title is dropped before the steps compress; without steps the title is shown and ellipsized, `ui` returns `None`; participant chip and state pill right-aligned and never overlapping the steps at 640/1100/1800 px and scale 1/2; renders correctly in a bare `Px(52)` cell with no style pushed by the caller.
- [ ] Move myocontrol's `header_ui` logic into the widget unchanged in look; myocontrol uses `AppHeader("Myocontrol", steps=steps, participant=participant)` and keeps its footer.
- [ ] `tests/test_myocontrol_wiring.py`, `tests/test_examples.py`, the new tests and ruff pass; full suite once; commit `feat(widgets): AppHeader — the myocontrol header for every app`.
