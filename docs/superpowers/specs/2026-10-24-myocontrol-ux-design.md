# Design: myocontrol UX — participant labels, step notifications, a workflow you can see

**Status:** draft, plan written (`docs/superpowers/plans/2026-10-24-myocontrol-ux.md`).
Visual reference: the Design canvas "MyoGestic Myocontrol Redesign"
(https://claude.ai/artifact/U66Wyc9ZNsLHZHrdg6NFqv — private to the owner). Not implemented.

## Context / problem

A collaborator ran `examples/start_here/myocontrol.py` and reported five things:

1. There is nowhere to enter who the participant is.
2. Saved files carry no participant label (MyoGen-style: who + date + time).
3. Nothing tells you a step finished ("training is finished").
4. The feature choice (RMS, …) was missed: it sits in a **Model** tab beside the plot, not
   next to the Train button it configures.
5. Every recorded and every trained file should be labelled.

Today a recording lands in `sessions/<YYYY-MM-DD_HH-MM-SS>_<uuid8>/` and packs to
`<that>_<typed-name>.session.zip` (`Session.__init__`, `Session.pack_to_zip`). `meta.json`
holds no participant. `myocontrol.py` never saves a model. Completion is a line in the
`LogPanel` and nothing else. No participant, toast or notification code exists anywhere in
`myogestic/`.

Decided with the owner (2026-10-24):

- **Pseudonymised participant ID** labels every file. First and family name may be typed
  but are written only to a local key file, never into a recording, archive or model.
- **Corner toasts**, not blocking dialogs: a modal mid-trial steals focus from the subject's
  task.
- **Record is locked until a participant ID is set** — in apps that opt in.

## Goals / non-goals

**Goals**

1. An app can declare the participant; every session folder, archive and auto-saved model it
   writes is named `<ID>_<YYYY-MM-DD_HH-MM-SS>…` inside `sessions/<ID>/`, and `meta.json`
   records `"participant": "<ID>"`.
2. Names, when typed, go to `~/myogestic/participant-key.csv` only. A returning participant's
   name finds their existing ID; a new one is offered the next free `P-NNN`.
3. `ctx.notify(...)` raises a toast that the `App` draws itself — every app gets it, including
   `force_ramps.py` and `pong.py`, with no wiring. Each toast is also a `ctx.log` line.
4. `myocontrol.py` is laid out as Connect → Record → Train → Drive, with the Train step
   showing model mode and features beside the Train button.
5. Existing apps, tests and old sessions behave exactly as before unless they opt in.

**Non-goals**

- Merging `feat/record-while-predicting`. This work builds on `main` +
  `feat/responsive-layout`; record-while-predicting rebases onto it afterwards. Its REC pill
  is not reimplemented here.
- A session note field (it is on the canvas; dropped — nobody asked for it).
- Cross-validated accuracy in the training toast (the canvas shows a sample figure;
  `myocontrol`'s `train` computes none, and computing one doubles training time).
- A gesture suffix derived automatically. A take is named only if the operator names it,
  exactly as today; a myocontrol take holds several classes, so no single gesture names it.
- Encrypting the key file. It is a local CSV; protecting the machine is the lab's job.
- Redesigning `force_ramps.py` / `pong.py` beyond adopting the participant panel and gate.

## Prerequisite

`feat/responsive-layout` (automatic UI scale, `Grid.areas`, `Layout` reflow, `ui_px`) is
fast-forwarded into `main` first. Its tests pass on its own branch. The myocontrol layout
below uses `Layout`/`Grid.areas`; widgets size fixed pixels through `ui_px`.

## Design

### 1. Participant on the context

```python
@dataclass
class Context:
    ...
    participant: str = ""   # pseudonymised ID, e.g. "P-014"; "" = none set
```

`App(..., require_participant: bool = False)`. When `True`, `App.start_recording` refuses
while `ctx.participant == ""`: it sets `ctx.status_message`, notifies
`("Recording refused", "Set a participant ID first.", "warning")`, and returns without
creating a folder. Default `False` keeps every existing test and example working.

The flag is stored on the context, `ctx.require_participant: bool = False`, because the
recording widgets receive `ctx` and nothing else. `RecordingControls` and `RecordButton`
mirror the gate: with `ctx.require_participant` and no participant, Record is drawn disabled
and its hover tooltip says why, using the `imgui.HoveredFlags_.allow_when_disabled` idiom
already in `_render_predict_button`.

### 2. Labelled names

One helper in `myogestic.session`, used by both sessions and models:

```python
def labelled_path(base_path: str | Path, participant: str = "", suffix: str = "") -> Path:
    """base/<ID>/<ID>_<YYYY-MM-DD_HH-MM-SS>[_suffix]  — or the legacy layout without an ID."""
```

- The ID goes through the existing `_slug` whitelist (`P-014` survives it unchanged), so a
  typed ID can never become a path separator or `..`.
- With an ID: `sessions/P-014/P-014_2026-10-24_15-12-03`. Without one: the current
  `sessions/2026-10-24_15-12-03_<uuid8>` exactly, so `require_participant=False` apps keep
  today's layout byte for byte.

**The same-second guard stays.** The uuid8 suffix exists because a session's pack thread
`rmtree`s its own folder and a shared name lets an old pack wipe a new recording
(comment in `Session.__init__`). The labelled name drops the uuid, so it must replace the
guarantee: a new stem is unique when neither `parent/<stem>` nor any
`parent/<stem>*.session.zip` exists; otherwise try `<stem>-2`, `<stem>-3`, …; then create
the folder with `mkdir(exist_ok=False)` and retry on `FileExistsError`. A test creates two
sessions for one participant within the same second and asserts distinct folders and zips.

`Session(base_path="sessions", participant="")` builds its path with this. `pack_to_zip`
is unchanged: it still appends the typed name, so a named take is
`P-014_2026-10-24_15-12-03_<name>.session.zip`.

`meta.json` gains a top-level `"participant": "<ID>"` when one is set, beside `"name"`.
It does not change a per-stream entry, so `_META_SCHEMA_VERSION` is not bumped.
`open_session_store` exposes it as `session.participant` and reads old sessions without it
as `""`.

**Invariant:** a first or family name is never written into a session folder, archive,
`meta.json`, or model file. A test records a session with a key-file entry present and
asserts neither name appears in any file of the archive.

### 3. Sessions follow the participant

`scan_sessions` is non-recursive (`base.iterdir()`), and `SessionManager` keys its state by
`f"{title}_{base_path}"`, which `add_recorded_session` reproduces with the default
`"sessions"`. Nesting by participant must not break any of the three.

`SessionManager.ui(self, participant: str | None = None)`. When `participant` is given, Scan
looks in `base_path/participant`, and a change of participant clears the listed sessions
(the next participant's training set starts empty — training on another person's takes by
accident is the failure this prevents). The widget id does not change, so
`add_recorded_session` keeps registering into the same state. It is called with the session
path, which it already scans by parent. Acceptance: record as `P-014`, the take appears
selected; switch to `P-015`, the list empties; Scan finds only `P-015`'s takes.

### 4. Model auto-save

`Pipeline` gets an attribute hook beside `save_model`:

```python
pipeline.save_model = save_pickle        # existing
pipeline.autosave_dir = "sessions"       # new; None (default) = no auto-save
```

After a successful `train`, when both are set, the pipeline saves to
`labelled_path(autosave_dir, ctx.participant, "model.joblib")` →
`sessions/P-014/P-014_2026-10-24_15-20-41_model.joblib`. A failing save is logged and
notified as `danger`; the trained model stays in memory and usable.

### 5. Notifications

```python
ctx.notify(title: str, detail: str = "", kind: str = "info") -> None
# kind: "success" | "info" | "warning" | "danger"
```

- Appends a `Notification(title, detail, kind, created)` to `ctx.notifications` and calls
  `ctx.log(f"{title} — {detail}" if detail else title)`. Safe from any thread: the same
  GIL-atomic `list.append` `ctx.log` relies on. Expiry is computed on the UI thread from
  `time.monotonic()`.
- Lifetimes: `success` and `info` 6 s, `warning` 10 s, `danger` until dismissed. Hovering a
  toast pauses its clock. At most three show; older ones leave the overlay (they stay in the
  log).
- `App` draws the overlay itself after the user's `@app.ui`, in a private renderer
  (`myogestic/widgets/panels/notifications.py`, imported lazily like `session_manager`).
  Anchored to the bottom-right of `imgui.get_main_viewport()`'s work area (with
  `docking=True` multi-viewport, "the window" is ambiguous), sized with `ui_px`. Window flags:
  no decoration, no focus on appearing, no nav, no saved settings, no docking, auto-resize.
  Each toast: a status dot in `SUCCESS`/`INFO`/`WARNING`/`DANGER`, the title, the detail in
  `muted()`, and an `XMARK` dismiss button. Surfaces read the theme (`Col_.popup_bg`,
  `Col_.border`); no literals.
- **Which events notify** — this list is the whole set, so toasts do not sprawl:

| Where | Today | Becomes |
| --- | --- | --- |
| `App.stop_recording` finalize | `log("Session saved → …")` | `notify("Recording saved", <archive name>, "success")` |
| `App.stop_recording` finalize | `log("Pack failed: …")` | `notify("Recording not packed", "<error> — folder kept", "danger")` |
| `App.start_recording` gate | — | `notify("Recording refused", "Set a participant ID first.", "warning")` |
| `Pipeline.start_training` worker | `log("Training complete")` | `notify("Training finished", <saved model name or elapsed s>, "success")` |
| `Pipeline.start_training` worker | `log("Training failed: …")` | `notify("Training failed", <error>, "danger")` |
| `myocontrol` `_bind` success | — | `notify("Virtual Hand connected", "Start predicting drives it.", "info")` |

### 6. Widgets

**`StepBar(steps: list[str], *, widget_id: str = "steps")`**, `ui(done: list[bool]) -> int`.
One button per step: a number, or `ICON_FA_CHECK` in `SUCCESS` when done, then the label.
Clicking selects; the active step uses `push_selected`/`pop_selected` (it is a sticky
on/off control per the visual language). Returns the active index. State keyed by
`widget_id`. It navigates, it does not gate: any step can be opened.

**`ParticipantPanel(*, key_file: str | Path = "~/myogestic/participant-key.csv",
widget_id: str = "participant")`**, `ui(ctx) -> None`.
- Header chip: the ID in the mono font (or "Set participant" in `WARNING` when none), the
  local name in `muted()`. Clicking opens a modal.
- Modal: ID input (prefilled with the next free `P-NNN`), first and family name inputs, a
  read-only preview of the folder and file names `labelled_path` will produce, **Start
  session** (enabled once the ID is non-empty after `_slug`) and **Cancel**.
- Typing a first + family name that matches a key-file row (case- and accent-insensitive)
  fills its ID and says "Returning participant".
- Start writes `ctx.participant` and, if a name was typed and is not yet in the key file,
  appends a row. Stdlib `csv`, columns `id,first_name,family_name,created`, parent folder
  created on first write. The key file lives in the home folder on purpose: a copied
  `sessions/` must not carry it.
- While `ctx.state != "idle"` the chip is disabled with a reason: a participant cannot
  change mid-recording.

**`primary_button(label: str, size=(0, 0)) -> bool`** in `widgets/common.py`, filled with a
new `PRIMARY_FILL` token, text in a new `ON_PRIMARY_TEXT`, both fixed in both themes and
defined in `common.py` (white on `#0062CC` is 5.6:1; on the theme accent it is 3.6:1). Used
for the one forward action per step (Train, Start predicting, Start session).

**Light theme:** `text_dim` alpha 153 → 199 in `_theme.py`. At 153, small muted labels on
white measure about 3.4:1, under the 4.5:1 the canvas was drawn to.

### 7. myocontrol layout

`App(..., require_participant=True)`, `pipeline.save_model = save_pickle`,
`pipeline.autosave_dir = "sessions"`. A `Layout` with a wide and a narrow `Grid.areas`:

- **Header** (one `Px` row): title, `StepBar(["Connect", "Record", "Train", "Drive"])`,
  `ParticipantPanel` chip, the state pill.
- **Body:** signal viewer over the activity log (left, `Fr`); the active step's panel over
  the session list (right, `Fr`).
- **Status bar** (one `Px` row): device, participant ID, save folder, model state.

Step panels (existing widgets, regrouped):

| Step | Contents | Done when |
| --- | --- | --- |
| Connect | `DevicePicker`, mains notch `segmented`, `ProcessLauncher` + control-map bind | `emg` stream connected |
| Record | `RecordingControls` (gated) | the participant has at least one take |
| Train | mode `segmented`, `FeatureSelector`, input read-out (window, notch, channels), `primary_button("Train …")`, a "Features changed — retrain" `WARNING` line when inputs changed since the model was fitted | `pipeline.model is not None` |
| Drive | `PredictionLabel`, `primary_button` Start/Stop predicting, `PostProcessor`, the PUSHED read-out | predicting |

The session list is `SessionManager.ui(participant=ctx.participant)`.

`force_ramps.py` and `pong.py` add `require_participant=True`, a `ParticipantPanel` chip in
their existing header area, and nothing else.

## Testing

- Unit: `labelled_path` (with/without ID, slugging, collision suffix incl. the zip-exists
  case), `Session` naming + `meta.json` participant key, `open_session_store` on an old
  session, the name-never-written invariant, key-file lookup/next-ID/append, `notify`
  lifetimes and log mirroring, the `start_recording` gate, `SessionManager` participant
  switch, `Pipeline` auto-save success and failure.
- Render (headless, like the existing widget tests): `StepBar`, `ParticipantPanel` modal,
  the notification overlay, `primary_button`; a simulated click on the step bar (the visual
  language warns that a layout pass cannot catch push/pop-on-toggle bugs).
- `tests/test_visual_language.py` passes: no colour literal outside `_theme.py` /
  `widgets/common.py`.
- `uv run ruff check .` and `uv run --extra dev pytest -q` green, the two known LSL-flaky
  tests excepted (see `CLAUDE.md`).
