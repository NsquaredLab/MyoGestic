# Brand header and compact Connect — Implementation Plan

> **For agentic workers:** two independent tasks, one worker each, both branched from
> `feat/myocontrol-ux`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** put the MyoGestic brand into the app (icon, logo, header) and rebuild the Connect step
as one compact card that fits the step cell without scrolling.

**Architecture:** Task A swaps brand assets and redraws `myocontrol`'s header around a one-line
logo image. Task B changes how `DevicePicker` *renders* (stream chips, a two-column option grid,
a state-dependent action area) without touching its connect/abort/threading logic, then rebuilds
`myocontrol`'s Connect step on it.

**Tech Stack:** Python, imgui_bundle (ImGui / HelloImGui), pytest.

**Spec:** the approved design canvas, *Myocontrol Header and Connect*
(https://claude.ai/artifact/8Kcst1b278KE7vvZ1MPyAW). Its three boards are the source of truth;
this file restates every decision a worker needs.

## Global Constraints

- `CLAUDE.md` applies in full. In particular: no colour literal outside `_theme.py` /
  `widgets/common.py` (enforced by `tests/test_visual_language.py`); panel titles through
  `panel_header`; any sticky on/off control through `push_selected` / `pop_selected`; sizes fixed
  in pixels go through `ui_px`; layout between panels is `Grid`; NumPy docstrings.
- `uv run ruff check .` clean; `uv run --extra grpc --extra dev pytest -q` green.
- Docs are tested: a changed public signature gets its docstring and any docs page updated.
- Commits: no AI attribution of any kind.
- Brand sources (read-only, copy from here):
  `/Users/raul/Library/CloudStorage/SynologyDrive-papers/in_progress/tutorial_emg/figures/ai/myogestic-brand/app/`
  holds `icon.png` (512², crowned M·G on the gradient tile), `myogestic_logo.png` (800×540,
  stacked logo) and `myogestic_logo_line.png` (519×128, one-line logo, transparent).

## Review Focus

1. **UI scale 2.0** (large screens): the logo, chips and option grid scale with `ui_px` /
   frame height and never overflow their row.
2. **Narrow window** (below the 1100 px breakpoint, and a 900 px window): the header drops
   "Myocontrol" first; the option grid falls back to one column when a cell is too narrow for
   its control.
3. **Removing the selected stream, or the last one:** the picker points at a remaining stream;
   the last stream is never removable.
4. **Light theme:** the logo, the divider and the connected status bar stay legible (tints are
   derived from tokens, not literals).
5. **During a recording:** add, remove, connect, reconnect and disconnect are disabled, each
   with its reason in the tooltip (existing rule: a device change mid-recording corrupts the take).

---

### Task A: Brand assets and the header

**Files:**
- Replace: `myogestic/assets/app_settings/icon.png` ← brand `app/icon.png` (window icon on
  Linux/Windows; `_platform._try_set_macos_dock_icon` makes it the macOS Dock icon)
- Replace: `myogestic/assets/myogestic_logo.png` ← brand `app/myogestic_logo.png`
- Add: `myogestic/assets/myogestic_logo_line.png` ← brand `app/myogestic_logo_line.png`
- Modify: `myogestic/widgets/panels/app_logo.py` (and `image.py` only if the change belongs there)
- Modify: `examples/start_here/myocontrol.py` — `header_ui` only
- Test: the existing app-logo / image tests, or a new `tests/test_app_logo.py`

**Interfaces:**
- Produces: a way to draw the one-line logo at a fixed height. Prefer extending the existing
  public class over a new widget, e.g. `AppLogo(variant="line", height=ui_px(26))`, with width
  from the asset's aspect ratio. A missing asset falls back to the current Instrument Serif text
  wordmark, never an exception.

- [ ] **Step 1:** Copy the three assets into place.
- [ ] **Step 2:** Write the failing test(s): the line variant's drawn size is `height × aspect`
  of `myogestic_logo_line.png` (519/128); a missing asset takes the text fallback.
- [ ] **Step 3:** Implement the logo variant.
- [ ] **Step 4:** Rework `header_ui`, left to right on one 52 px row, everything vertically
  centred: the line logo at `ui_px(26)` tall → a 1 px `hairline()` divider `ui_px(20)` tall →
  "Myocontrol" in `muted()` → the `StepBar` directly after, `ui_px(14)` from the group, **left-
  aligned, no longer centred** → participant chip and state pill right-aligned as today. When the
  row is too narrow, drop the divider and "Myocontrol" first, then fall back to the existing
  compact step padding.
- [ ] **Step 5:** Run the new tests, `ruff`, and the full suite.
- [ ] **Step 6:** Commit: `feat: brand icon and logo; the one-line logo leads the header`.

### Task B: Compact Connect

**Files:**
- Modify: `myogestic/widgets/signals/device_picker.py` and its tests
- Modify: `myogestic/widgets/panels/process_launcher.py` and its tests
- Modify: `myogestic/widgets/common.py` — only for a token-derived tinted-row helper, if needed
- Modify: `examples/start_here/myocontrol.py` — `connect_ui`, `hand_ui`, the step `panel_header`
  call for Connect, and the module-level widget construction
- Modify: `docs/concepts/visual-language.md` (the chip pattern) and any docs page describing
  `DevicePicker`

**Interfaces:**
- Produces: `DevicePicker(..., on_add: Callable[[str], object] | None = None,
  on_remove: Callable[[str], object] | None = None)` with `StreamManager`'s contract for both.
- Produces: `ProcessLauncher.launch(name: str) -> None` and `ProcessLauncher.stop(name: str) -> None`,
  public wrappers over the existing per-process start/stop.

`DevicePicker` rendering — **all existing state, threading, generation and abort logic stays as
it is; this is a rendering change:**

- [ ] **Step 1: Stream chips** (when `selectable=True`) replace the "Stream" combo row: one chip
  per stream in `ctx.streams` minus `exclude`, sorted. A chip is a rounded button: a `CIRCLE`
  glyph in the stream's state colour (`SUCCESS` connected, `DANGER` last error, `IDLE` otherwise)
  and the name in the mono font. The chip of the stream being shown uses
  `push_selected`/`pop_selected`. With `on_add`, a trailing `PLUS` chip opens an inline row: a
  name input (hint `e.g. force`, cleaned exactly as `StreamManager` cleans names — import its
  helper, do not copy it), **Add**, and a bare `XMARK` cancel. With `on_remove`, the selected chip
  carries a bare `XMARK` through `destructive_button` (red on hover only); never offered for the
  last remaining stream.
- [ ] **Step 2: Device row:** the device combo spans the row with no "Device" label; the existing
  ⓘ setup popup button sits at its right.
- [ ] **Step 3: Options:** a two-column grid; each cell is a small `muted()` caption above its
  control; `segmented` when `_fits_segmented(labels, cell_width)`, else a combo; one column when
  a cell would be narrower than its control can use. A scan device shows the caption **Outlet**
  above its target combo, with the rescan button at its right.
- [ ] **Step 4: Action area, by state:**
  not connected → `primary_button(f"{ICON_FA_PLUG}  Connect")` full width, plus a `DANGER` mono
  line with `stream.last_error` only when there is one;
  connecting → one row: `IDLE` dot, mono `connecting… N s`, a small **Abort** at the right;
  connected → one row on a `SUCCESS`-tinted rounded background (token-derived): `SUCCESS` dot,
  mono `{fs} Hz · {ch} ch · {age}`, and icon-only `ARROWS_ROTATE` (Reconnect) and
  `PLUG_CIRCLE_XMARK` (Disconnect) buttons at the right, each with its existing tooltip.
  Live sliders stay below, for the attached device only.
- [ ] **Step 5: Tests first** for: chip click points the panel at that stream; `on_add` receives
  the cleaned name; remove is absent for the last stream and disabled while recording; connected
  state draws Reconnect/Disconnect and no Connect; `ProcessLauncher.launch`/`stop` start and stop
  the process. Update the existing picker tests to the new layout. See them fail, then implement.

`myocontrol` Connect step:

- [ ] **Step 6:** The Connect step's `panel_header` carries the emg stream's status dot
  (`SUCCESS` / `DANGER` / `IDLE`). The picker becomes
  `DevicePicker("emg", selectable=True, show_header=False, on_add=…, on_remove=app.remove_stream)`,
  `on_add` moved from the `StreamManager` construction; the `StreamManager` instance and its
  STREAMS section go.
- [ ] **Step 7:** Mains notch is one row: the label "Mains notch" (tooltip: *Filters the recording
  and the model input.*) and the `segmented` control filling the rest; disabled when not idle.
- [ ] **Step 8:** Virtual Hand is one row on a surface-tone background: a status dot (`IDLE` not
  running, `WARNING` launched and binding, `SUCCESS` bound), **Virtual Hand**, a muted mono detail
  (`not running` / the binder's status or `launched · binding as soon as it answers…` /
  `bound · prediction and control → hand`) and one button: **Launch** (calls
  `processes.launch(vhi.name)`), **Stop** once launched from here, **Bind now** when a VHI runs
  that this app did not start. The control map moves into the detail line's tooltip
  (`alias → target · role`, from `CONTROL_MAP` and `ALIAS_ROLES`). Keep `_announce_binding` and
  `binder.poll()` exactly as they behave now.
- [ ] **Step 9:** At the default 1280 × 828 window the Connect step (Muovi, not connected) fits the
  step cell — about 400 px — without a scrollbar.
- [ ] **Step 10:** `ruff`, the full suite; commit: `feat: compact Connect — stream chips, one
  device card, one-row notch and hand`.
