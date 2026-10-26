# Compact Train, Drive and Takes — Implementation Plan

> **For agentic workers:** two independent tasks, one worker each, both branched from
> `feat/myocontrol-ux`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make Train, Drive and the takes list stay short as a session grows: one line per take
grouped by day, one card per step, rarely-touched knobs behind a popover.

**Architecture:** Task A redraws `SessionManager` (one-line rows, day groups, summary, gesture
chips, icon actions), adds a public selection summary, and rebuilds `myocontrol`'s Train step
on it. Task B restyles `FeatureSelector` (toggle chips), `PredictionLabel` (a hero card),
gives `PostProcessor` an opt-in compact row with a settings popover, and rebuilds `myocontrol`'s
Drive step. Rendering only: selection semantics, training, prediction and filtering logic stay.

**Tech Stack:** Python, imgui_bundle (ImGui / HelloImGui), pytest.

**Spec:** the approved canvas *Myocontrol Train, Drive and Sessions*
(https://claude.ai/artifact/Wf8YBfLNeouA7Ph78XYHN1): the interactive workspace, "Takes · now vs
proposed" and "Train and Drive · now vs proposed". This file restates every decision.

## Global Constraints

- `CLAUDE.md` applies in full: no colour literal outside `_theme.py` / `widgets/common.py`
  (`tests/test_visual_language.py`); panel titles via `panel_header`; every sticky on/off control
  via `push_selected` / `pop_selected`; pixel sizes via `ui_px`; `PALETTE` only for categorical
  identity (gesture colours); NumPy docstrings; icons follow the visual-language table
  (`ARROWS_ROTATE` rescan, `BROOM` clear accumulated content, two spaces between icon and label).
- `uv run ruff check .` clean; `uv run --extra grpc --extra dev pytest -q` green; docs are tested,
  so changed widgets get their docstrings and `docs/` pages (e.g. `docs/widget-gallery.md`) updated.
- At the default 1280 × 828 window: the Train and Drive steps fit the step cell (about 400 px)
  without a scrollbar; the takes cell is about 260 px and scrolls only its list, never its header,
  summary or gesture chips.
- Commits: no AI attribution of any kind.

## Review Focus

1. **Many takes** (30+ across several days): one line each, older days collapsed, the list scrolls
   inside its cell while the header, summary and chips stay put.
2. **A take recorded with no labels, or with a gesture name not in `class_names`:** its row still
   draws (no chips, or the raw name), never raises.
3. **A deselected gesture chip:** excluded from the Train card's totals and from training data,
   and its chips in the rows read as excluded.
4. **Loading files from elsewhere** (outside the participant folder): they get their own group
   (e.g. "Loaded"), not mixed into a day of the participant's takes.
5. **UI scale 2.0 and the light theme:** rows, chips and the popover keep their proportions and
   stay legible.

---

### Task A: Takes list and the Train step

**Files:**
- Modify: `myogestic/widgets/training/session_manager.py`, `myogestic/widgets/training/_session_state.py`
- Modify: `examples/start_here/myocontrol.py` — `model_ui` only (and imports it needs)
- Tests: the existing session-manager tests, `tests/test_myocontrol_wiring.py`
- Docs: `docs/widget-gallery.md` and any page describing `SessionManager`

**Interfaces:**
- Produces: a public read of the current selection on `SessionManager`, e.g.
  `selection() -> SelectionSummary` with `n_selected: int`, `n_total: int`,
  `class_seconds: dict[str, float]` (selected takes only, active gestures only). Name it to fit
  the module; the Train step reads it instead of recomputing.

- [ ] **Step 1: Tests first:** rows group by day (Today / Yesterday / `Oct 24`) from each take's
  `created`, newest first; only the newest group starts open; the summary counts and the
  `class_seconds` follow selection and active gestures; All / None select and clear every row;
  a row without labels draws without raising; loaded-from-elsewhere files form their own group.
- [ ] **Step 2: Header row:** `panel_header` title (`Takes · <participant>` when one is set,
  else the existing title) with icon-only actions at the right: `ARROWS_ROTATE` (rescan, today's
  *Scan folder*), a load action (today's *Load Files…*), and `BROOM` (today's *Clear*); each with
  a tooltip naming exactly what it does (*Clear* says the files stay on disk).
- [ ] **Step 3: Summary row:** `N of M selected · m:ss total` in muted text, and `All` / `None`
  as `small_button`s at the right.
- [ ] **Step 4: Gesture chips** replace the per-class button row: one chip per gesture with its
  `PALETTE` dot, name and total time across all takes; an included gesture uses
  `push_selected`; clicking toggles it (today's deactivated-classes behaviour).
- [ ] **Step 5: Rows:** one line per take: checkbox, the take's gesture chips (tinted from
  `PALETTE`, names only; excluded gestures drawn muted), then right-aligned muted mono time
  `HH:MM` and its duration. Tooltip: the file name and streams line (today's tooltip). Groups are
  collapsible headers with a chevron, the group label and `selected/total · m:ss`. Only the list
  scrolls (a child region), so the header, summary and chips never leave the cell.
- [ ] **Step 6: Train step (`model_ui`):** no MODE / INPUT sub-headers. The mode `segmented` spans
  the row; then `features.ui()`; then a card on the surface tone: **Training on N takes** with the
  total at the right and one thin bar per active gesture (`PALETTE` colour, `m:ss`), from the new
  selection read; then the existing input summary on one muted mono line
  (`200 ms windows · notch 50 Hz · 64 ch · CatBoost`); then `primary_button` **Train classifier** /
  **Train regressor** across the row; after a fit, a `SUCCESS`-tinted row (the `tinted_row`
  helper) with a check and the saved model's file name; when disabled, the existing reason line,
  now naming what is missing (e.g. a gesture with no selected takes). Keep the "features changed —
  retrain" warning.
- [ ] **Step 7:** ruff, full suite; commit `feat: one-line takes by day, and a Train card that shows what it trains on`.

### Task B: Drive step, feature chips, prediction card, compact smoothing

**Files:**
- Modify: `myogestic/widgets/training/feature_selector.py`, `myogestic/widgets/training/prediction_label.py`,
  `myogestic/widgets/panels/filter_processor.py` (`PostProcessor`)
- Modify: `examples/start_here/myocontrol.py` — `drive_ui`, `_pushed`, and the `PostProcessor`
  construction only
- Tests: the existing tests of those three widgets, `tests/test_myocontrol_wiring.py`
- Docs: `docs/widget-gallery.md` and any page describing the three widgets

**Interfaces:**
- Produces: `PostProcessor(..., compact: bool = False)`. `False` keeps today's full panel for
  the other examples; `True` draws one row and moves the parameters into a popover.

- [ ] **Step 1: Tests first** for: feature chips toggle and keep at least today's rules about
  active features; the compact `PostProcessor` row draws the filter combo, the latency and a
  settings button, and its popover holds every parameter slider plus reset; `PredictionLabel`
  draws the idle text before a prediction and the label with one bar per class during one;
  `_pushed` rows read `alias → target  value`.
- [ ] **Step 2: `FeatureSelector`:** a caption *Features* then one toggle chip per feature (mono
  label, `push_selected` when active), wrapping; no checkboxes; the count leaves the title.
- [ ] **Step 3: `PredictionLabel`:** a card on the surface tone: the predicted label large in
  `display_font()` with a muted mono detail at the right (`every 50 ms` while predicting, else the
  idle reason); with `show_probability`, one thin bar per class in its `PALETTE` colour with a mono
  value. Idle shows `—`. Public API unchanged.
- [ ] **Step 4: `PostProcessor(compact=True)`:** one row: label *Smoothing*, the filter combo
  filling the row, the latency in muted mono (`159 ms`), and an icon-only settings button that is
  `push_selected` while its popover is open. The popover: the filter's name as a `panel_header`
  with the existing reset (`ROTATE_LEFT`) at the right, every parameter slider, and one muted
  sentence on what the parameters do.
- [ ] **Step 5: Drive step (`drive_ui`):** `prediction.ui()` (the card), then
  **Start predicting** / **Stop predicting** across the row (`primary_button`; while predicting it
  wears `push_selected` as today), the disabled reason when needed, then
  `output_filter.ui()` with `compact=True` set at construction, then a surface-tone card captioned
  *Sent to the hand* listing each pushed control as `alias → target` with its value right-aligned
  in mono (`_pushed` reshaped to rows; `nothing sent yet` before the first frame). No
  PREDICTION / POST-PROCESSING / PUSHED sub-headers.
- [ ] **Step 6:** ruff, full suite; commit `feat: Drive card — prediction hero, compact smoothing, sent controls; feature chips`.
