# Recorded Participants Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pick up a participant recorded earlier — their takes, and their saved model — from the participant dialog every app already opens.

**Architecture:** Task 1 adds a "Recorded" tab to `ParticipantPanel` (`myogestic/widgets/panels/participant.py`) that lists participants found under the sessions folder; every app using the panel gains it. Task 2 wires myocontrol's "Drive with saved model" and its Train card.

**Tech Stack:** imgui-bundle, `myogestic.widgets` 2.0 kit, `myogestic.session`.

**Spec:** approved canvas https://claude.ai/artifact/AXTfFmaesJEcE7et3sWmUK — sources copied at `/private/tmp/claude-501/-Users-raul-code-myogestics-MyoGestic-main/c0763295-1de4-45ba-8e9d-ab0c5ea6bb02/scratchpad/design/participant/project/*.dc.html` (Main = dialog with both tabs, Loaded = after choosing, Empty = first run).

## Global Constraints

- Privacy: names live only in the key file (`participant-key.csv`); a name is never written to a recording, a model, a log line or a status message. In the Recorded list names are masked (`•••••  •••••••`) until **Show names** is pressed, and the toggle resets when the dialog closes. Participants without a key-file row show only their ID.
- `docs/concepts/visual-language.md` § "The 2.0 kit" and CLAUDE.md: tokens only, `ui_px`, `mono_text` for IDs and numbers, chips with `push_selected`/`pop_selected`, `segmented` for the two tabs, captions above fields, PALETTE dots for gestures (`PALETTE[index % len(PALETTE)]`, the index being the class's index in that participant's `class_names`).
- Scanning must stay cheap: read `meta.json` of each `*.session.zip`/session folder once per dialog open (reuse `scan_sessions` / `recorded_time` / `_read_session_metadata` from `myogestic.session` / `_session_state`), never per frame; skip takes still being saved (the pending-save tracking added in d771754).
- Keyword-only, backwards-compatible API: every current `ParticipantPanel()` caller keeps working and gains the tab.
- No AI attribution, no `Co-Authored-By`. Full suite once at the end, including `tests/test_recording_race.py`.

## Review Focus

- A sessions folder with a participant whose takes are all cursor takes (no class names): row shows "cursor", no dots.
- A participant folder with no readable takes (only a half-saved folder, or garbage files): not listed.
- The key file missing or hand-edited: list still works with IDs only.
- Choosing a participant while a recording is running: not possible (dialog already closes when not idle — keep that).
- Two participants with the same name in the key file: IDs stay the identity; nothing merges.

---

### Task 1: `ParticipantPanel` — Recorded tab

**Files:** Modify `myogestic/widgets/panels/participant.py`, `docs/api/widgets.md`, `examples/panels/participant_panel.py` (show the tab with a demo sessions folder only if the demo needs it). Tests: `tests/test_participant*.py`.

**Interfaces — Produces:**
- `ParticipantPanel(..., sessions_dir: str | Path = "sessions", on_drive: Callable[[str, Path], None] | None = None)`.
- `on_drive(participant_id, model_path)` is called by **Drive with saved model**, after the panel has set `ctx.participant`; the button exists only when `on_drive` is given and the participant has a model.
- Model discovery: the newest `*_model.joblib` (by modification time) in `sessions_dir/<id>/`.

- [ ] Dialog opens on **Recorded** when at least one participant exists, else on **New participant**; `segmented` tabs "Recorded N" / "New participant".
- [ ] Recorded: search (ID, and name only while names are shown), rows newest first — ID (mono), name (masked/shown), gesture dots or "cursor", takes "n · m:ss", last recorded ("Today 08:47", "Yesterday 15:47", else date), model ✓/—; click selects (selected tint + accent border); a summary line for the selection; Cancel, **Drive with saved model** (conditional), **Continue with <ID>** (primary) which sets `ctx.participant` exactly as Start session does today for a returning ID.
- [ ] New participant: today's form restyled per the canvas (captions above, next free ID prefilled, path preview, "Recorded before? Pick them in Recorded").
- [ ] Empty state per the canvas.
- [ ] Tests first: listing from a temp sessions folder (classes, cursor-only, unreadable, still-saving takes); masking and the reset on close; search; Continue sets the participant without touching the key file; Drive calls `on_drive` with the newest model; names never appear in `ctx.log`/status; 320 px and scale 2 light-theme fit.
- [ ] Commit `feat(widgets): pick a recorded participant from the participant dialog`.

### Task 2: myocontrol — Drive with a saved model

**Files:** Modify `examples/start_here/myocontrol.py`, `tests/test_myocontrol_wiring.py`.

- [ ] Pass `on_drive` that loads the model with the pipeline's own loader (`load_pickle`, as Save/Load do), records it as the pipeline's model with its path, and opens the Drive step.
- [ ] Continue lands on the first incomplete step; the participant's takes are ticked in Takes.
- [ ] Train card: when the model came from a saved file and no retrain happened, a green state row "Saved model loaded · <when>", **Go to Drive** (primary) and **Retrain on N takes**; otherwise unchanged.
- [ ] Tests first: on_drive loads the newest model and selects Drive; Continue ticks the takes; Train card states.
- [ ] Commit `examples: myocontrol drives a recorded participant's saved model`.
