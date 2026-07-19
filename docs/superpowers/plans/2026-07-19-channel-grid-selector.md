# Spatial channel-selection grid — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the signal viewer's 256-button channel wall with a compact grid-aware spatial toggle grid, carry channel topology in `StreamInfo` (serialized for replay), and decimate only the enabled channels so limiting the view restores responsiveness.

**Architecture:** A pure-function core (imgui-free: layout normalization, auto-shaping, rectangle→channel mapping, selection reducer, initial-selection resolution) with property tests; a thin imgui shell in `render_channel_controls`; a `StreamInfo.channel_grids` topology field round-tripped through session save/load; and a viewer reorder so the enabled set is resolved before the frame is built and decimated.

**Tech Stack:** Python 3.12, imgui-bundle, numpy, tsdownsample (M4), zarr sessions, pytest. Design spec: `docs/superpowers/specs/2026-07-19-channel-grid-selector-design.md`.

## Global Constraints

- **No AI attribution** in commits/PRs (no "Generated with…" footer, no "Co-Authored-By: Claude" trailer).
- **MyoGestic conventions:** 4-space indent, double quotes, ruff line-length 100. Examples get `E402` leeway.
- **Never block acquisition on a layout hint:** `StreamInfo.__post_init__` keeps only the existing dtype check — no `channel_grids` validation there. The viewer validates and falls back.
- **Back-compat:** old sessions (no `channel_grids`) load as `None`; tolerant `info.get(...)` decode.
- **Same widget contract:** `render_channel_controls(...)` keeps its `(enabled: set[int], ch_names, hovered_ch)` return so the plot is untouched.
- **Auto-shape never claims physical geometry** for a known grid; it's a derived rectangle only.

---

### Task 1: `ChannelGrid` + `StreamInfo.channel_grids`

**Files:**
- Modify: `myogestic/stream.py` (near `StreamInfo`)
- Test: `tests/test_channel_grid.py`

**Interfaces — Produces:**
- `ChannelGrid(label: str, cells: list[list[int | None]])` — frozen dataclass; `cells` is a 2-D map of output-column indices, `None` = empty cell. Property `columns -> list[int]` (non-None cells, row-major order).
- `StreamInfo.channel_grids: list[ChannelGrid] | None = None` (new trailing field).

- [ ] **Step 1: Failing test**
```python
# tests/test_channel_grid.py
from myogestic.stream import ChannelGrid, StreamInfo

def test_channel_grid_columns_and_streaminfo_field():
    g = ChannelGrid("IN1", [[0, 1], [2, None]])
    assert g.columns == [0, 1, 2]                     # row-major, skips None
    info = StreamInfo(n_channels=3, fs=2048.0, channel_grids=[g])
    assert info.channel_grids[0].label == "IN1"
    assert StreamInfo(n_channels=3, fs=2048.0).channel_grids is None   # default
    # a malformed layout must NOT raise at construction (viewer validates)
    StreamInfo(n_channels=2, fs=2048.0, channel_grids=[ChannelGrid("x", [[9, 9]])])
```
- [ ] **Step 2:** `pytest tests/test_channel_grid.py::test_channel_grid_columns_and_streaminfo_field -v` → FAIL (no `ChannelGrid`).
- [ ] **Step 3: Implement** in `stream.py`:
```python
@dataclass(frozen=True)
class ChannelGrid:
    """A named electrode grid as a 2-D map of output-column indices (None = empty cell)."""
    label: str
    cells: list[list[int | None]]

    @property
    def columns(self) -> list[int]:
        return [c for row in self.cells for c in row if c is not None]
```
Add `channel_grids: list[ChannelGrid] | None = None` as the last field of `StreamInfo`. Do **not** touch `__post_init__` beyond leaving the dtype check.
- [ ] **Step 4:** rerun → PASS.
- [ ] **Step 5: Commit** `feat(stream): ChannelGrid topology + StreamInfo.channel_grids field`.

---

### Task 2: Pure core — `auto_shape` + `normalize_layout`

**Files:**
- Create: `myogestic/widgets/signals/_channel_grid.py`
- Test: `tests/test_channel_grid.py`

**Interfaces — Consumes:** `ChannelGrid` (Task 1). **Produces:**
- `auto_shape(columns: list[int]) -> list[list[int | None]]` — near-square, row-major, last row padded with `None`.
- `normalize_layout(channel_grids: list[ChannelGrid] | None, n_channels: int) -> list[ChannelGrid]` — validate against `n_channels`; drop out-of-range/duplicate columns; fall back to a single auto-shaped grid ("all") when `None` or empty or fully invalid.

- [ ] **Step 1: Failing tests**
```python
from myogestic.stream import ChannelGrid
from myogestic.widgets.signals._channel_grid import auto_shape, normalize_layout

def test_auto_shape_covers_all_columns_near_square():
    cells = auto_shape(list(range(10)))
    flat = [c for row in cells for c in row if c is not None]
    assert flat == list(range(10))                    # every column, in order
    assert all(len(row) == len(cells[0]) for row in cells)  # rectangular
    assert len(cells[0]) <= 4 and len(cells) <= 4     # near-square (ceil(sqrt(10))=4)

def test_normalize_none_makes_one_auto_grid():
    layout = normalize_layout(None, 8)
    assert len(layout) == 1 and sorted(layout[0].columns) == list(range(8))

def test_normalize_drops_out_of_range_and_dupes_then_falls_back_if_empty():
    good = normalize_layout([ChannelGrid("IN1", [[0, 1, 99], [1, 2]])], 4)
    assert sorted(good[0].columns) == [0, 1, 2]       # 99 dropped, dup 1 dropped
    empty = normalize_layout([ChannelGrid("bad", [[50]])], 4)
    assert sorted(empty[0].columns) == [0, 1, 2, 3]   # invalid -> auto "all"
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `_channel_grid.py`: `auto_shape` uses `cols = ceil(sqrt(len))`, fills row-major, pads the final row with `None`. `normalize_layout` iterates grids, keeps first-seen in-range columns (set to dedupe, preserve order), re-shapes each kept grid via `auto_shape` only when its own `cells` are invalid — otherwise keeps the given `cells` with invalid entries nulled; if the union of kept columns is empty, return `[ChannelGrid("all", auto_shape(range(n_channels)))]`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat(viewer): channel-grid layout normalization + auto-shape`.

---

### Task 3: Pure core — `rect_to_channels`, `reduce_selection`, `resolve_initial`

**Files:** Modify `myogestic/widgets/signals/_channel_grid.py`; Test `tests/test_channel_grid.py`

**Interfaces — Produces:**
- `rect_to_channels(grid: ChannelGrid, r0, c0, r1, c1) -> set[int]` — columns in the (order-independent) cell rectangle, skipping `None`.
- `reduce_selection(enabled: set[int], op: str, targets: Iterable[int]) -> set[int]` — `op` in `{"add","remove","toggle","set","invert","all","none"}` (`invert`/`all`/`none` use `targets` = full channel range).
- `resolve_initial(initial_channels: Iterable[int] | None, n_channels: int, layout: list[ChannelGrid]) -> set[int]` — `None` → all if `n_channels <= 32` else first `min(n_channels, 16)`; an iterable → those clamped to `[0, n_channels)`.

- [ ] **Step 1: Failing tests (property + table)**
```python
import random
from myogestic.stream import ChannelGrid
from myogestic.widgets.signals._channel_grid import rect_to_channels, reduce_selection, resolve_initial

GRID = ChannelGrid("g", [[0, 1, 2], [3, None, 5]])   # note the hole at (1,1)

def test_rect_skips_holes_and_is_direction_invariant():
    a = rect_to_channels(GRID, 0, 0, 1, 2)
    b = rect_to_channels(GRID, 1, 2, 0, 0)            # dragged the other way
    assert a == b == {0, 1, 2, 3, 5}                  # (1,1) hole excluded

def test_invert_twice_is_identity_and_in_bounds():
    for _ in range(50):
        n = random.randint(1, 64)
        sel = set(random.sample(range(n), k=random.randint(0, n)))
        once = reduce_selection(sel, "invert", range(n))
        twice = reduce_selection(once, "invert", range(n))
        assert twice == sel
        assert once <= set(range(n))

def test_resolve_initial_policy():
    assert resolve_initial(None, 16, []) == set(range(16))        # small -> all
    assert resolve_initial(None, 256, []) == set(range(16))       # large -> first 16
    assert resolve_initial(range(4), 256, []) == {0, 1, 2, 3}
    assert resolve_initial([1, 2, 999], 8, []) == {1, 2}          # clamp out-of-range
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** the three functions (pure set logic; `rect_to_channels` normalizes `min/max` of the corners then collects non-None cells).
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat(viewer): rectangle/selection/initial pure ops for the channel grid`.

---

### Task 4: Serialize `channel_grids` through sessions

**Files:** Modify `myogestic/session/_core.py` (`save_meta`), `myogestic/session/_io.py` (`open_session_store`); Test `tests/test_channel_grid_serialization.py`

**Interfaces — Consumes:** `StreamInfo.channel_grids` (Task 1).

- [ ] **Step 1: Failing test**
```python
# round-trip a StreamInfo with channel_grids through a packed session
from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.session import Session, open_session_store
import numpy as np

def test_channel_grids_round_trip(tmp_path):
    info = StreamInfo(n_channels=4, fs=8.0,
                      channel_grids=[ChannelGrid("IN1", [[0, 1], [2, 3]])])
    s = Session(base_path=str(tmp_path))
    s.init_stream("emg", info)
    s.append("emg", np.zeros((2, 4), np.float32), np.arange(2, dtype=np.float64))
    s.save_meta(app_name="t")
    zip_path = s.pack_to_zip(); s.close()
    back = open_session_store(zip_path).stream_info("emg")
    assert back.channel_grids == info.channel_grids   # frozen dataclass equality
    assert back.channel_names is None                  # existing field still round-trips

def test_old_session_without_grids_loads_as_none(tmp_path):
    # a session whose meta lacks channel_grids
    ...  # write meta without the key, assert stream_info().channel_grids is None
```
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** In `save_meta`, write each stream's `n_channels, fs, dtype, channel_names, channel_grids` (grids as `[{"label":…, "cells":…}]`), and bump the meta `schema_version`. In `open_session_store`, decode `channel_grids` via `info.get("channel_grids")` into `ChannelGrid` objects (tolerant: missing → `None`), and also read `channel_names` (fix the existing save/load asymmetry noted in the spec).
- [ ] **Step 4:** run → PASS; also run the full `tests/test_session*`/`tests/test_replay*` to confirm no regression.
- [ ] **Step 5: Commit** `feat(session): persist StreamInfo.channel_grids (+ channel_names) with a schema bump`.

---

### Task 5: Decimate only the enabled channels (viewer reorder)

**Files:** Modify `myogestic/widgets/signals/viewer.py`, `myogestic/widgets/signals/_state.py`; Test `tests/test_signal_viewer_decimation.py`

**Interfaces:** `build_signal_frame(stream, v, enabled: set[int])` and `_m4_decimate_visible_window(t, d, n_out, v)` operate on the enabled-column subset. `resolve_enabled(v, stream, n_channels, initial_channels) -> set[int]` reads persistent `v.channels` (initialising via `resolve_initial` once).

- [ ] **Step 1: Failing test** — drive the acquire loop with a synthetic 64-ch source (reuse the `_SynthSource`/`_FixedSource` pattern), set `v.channels = {0, 5, 10}`, call `build_signal_frame(stream, v, {0,5,10})`, and assert the decimated `data` has exactly 3 columns and the M4 index union was computed over 3 channels (e.g. `frame.data.shape[1] == 3`). Also assert an empty `enabled` → no decimation work / empty frame.
- [ ] **Step 2:** run → FAIL (build_signal_frame decimates all channels).
- [ ] **Step 3: Implement.** Reorder `viewer.py`: resolve `enabled` from `v` **before** `build_signal_frame`; pass `enabled` in; slice the visible window to the enabled columns before `_m4_decimate_visible_window`; keep an index map so `render_plot` still colors/labels by true channel index. Render the plot with last frame's `hovered_ch` (store `v.last_hovered`), then render controls (which update `v.channels` and `v.last_hovered` for next frame). No behavior change for small streams (all enabled).
- [ ] **Step 4:** run the new test + `tests/test_signal_viewer*` → PASS.
- [ ] **Step 5: Commit** `perf(viewer): decimate only enabled channels (resolve selection before frame build)`.

---

### Task 6: The spatial toggle-grid widget

**Files:** Modify `myogestic/widgets/signals/_controls.py` (`render_channel_controls`); Test `tests/test_channel_grid.py` (smoke)

**Interfaces — Consumes:** the pure core (Tasks 2-3) + `normalize_layout(stream.info.channel_grids, n_channels)`. **Produces:** unchanged `(enabled, ch_names, hovered_ch)`.

- [ ] **Step 1: Smoke test** — with a fake `stream`/`ViewerState`, call `render_channel_controls` inside a headless imgui frame (reuse whatever harness the existing viewer tests use, or assert the pure helpers it delegates to); assert it returns a 3-tuple `(set, names_or_none, int)` and never raises for `n_channels` in `{4, 64, 256}` with and without `channel_grids`. (imgui pixel behaviour is validated manually via Task 8.)
- [ ] **Step 2:** run → FAIL / establish the harness.
- [ ] **Step 3: Implement** the grid renderer (imgui shell over the pure core):
  - `layout = normalize_layout(stream.info.channel_grids, n_channels)`; per grid draw a header (`{label}  {sel}/{total}  [all][none]`) then the `cells` row-major as DPI-scaled square cells. Enabled = palette color + filled dot; disabled = dim + hollow border (colorblind-safe). Empty cell = blank spacer. Footer `enabled N/total  [all][none][invert]`.
  - Interaction: capture `mouse-down` cell + its state + the op (add/remove) and the initial `enabled` snapshot; while dragging past `imgui.get_io().mouse_drag_threshold`, compute the rectangle by hit-testing the cursor against stored cell geometry and apply `reduce_selection(snapshot, op, rect_to_channels(...))`; a below-threshold release = single toggle; `shift` = linear range from last click via `reduce_selection`; hover → tooltip (`{label} · col {ch} · {name}`) + `hovered_ch`. Stable ids `f"##{stream_name}_cell_{ch}"`.
  - Keyboard: cells focusable, `Space` toggles the focused cell.
- [ ] **Step 4:** run smoke + `ruff` → PASS.
- [ ] **Step 5: Commit** `feat(viewer): spatial toggle-grid channel selector (replaces the button wall)`.

---

### Task 7: `initial_channels` arg + per-stream selection state

**Files:** Modify `myogestic/widgets/signals/viewer.py` (`signal_viewer` signature), `myogestic/widgets/signals/_state.py` (`ViewerState` init keyed by stream); Test `tests/test_signal_viewer_decimation.py`

- [ ] **Step 1: Failing tests** — (a) `signal_viewer(ctx, "emg", initial_channels=range(16))` results in `v.channels == set(range(16))` on first open and is **not** re-applied after the user changes it; (b) switching a `selectable` viewer between two streams keeps each stream's own selection (no shared reset).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** Add `initial_channels: Iterable[int] | None = None` to `signal_viewer`; resolve it once via `resolve_initial` when a stream's `ViewerState` selection is first created; key the stored selection by `(widget_id, stream_name, n_channels)` so a stream switch restores rather than resets.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat(viewer): initial_channels arg + per-stream selection state`.

---

### Task 8: Synthetic high-channel demo with grids (manual validation)

**Files:** Create `examples/synthetic/channel_grid_demo.py`

- [ ] **Step 1:** Write a minimal viewer-only app: a synthetic in-process 256-channel `Source` whose `connect()` returns `StreamInfo(..., channel_grids=[ChannelGrid(f"IN{i+1}", auto_shape(range(i*64, (i+1)*64))) for i in range(4)])`; register it as a `Stream`; render `signal_viewer(ctx, "emg", selectable=True, initial_channels=range(16))`.
- [ ] **Step 2:** `python -m py_compile` + `ruff check/format` → clean. (GUI runs on the user's machine.)
- [ ] **Step 3: Commit** `docs(examples): channel-grid demo (synthetic 256-ch, 4 grids)`.

---

## Follow-on (rides with the OTB source work, NOT this branch)

`QuattrocentoSource.channel_grids` population — build one `ChannelGrid` per active IN from `select`/`nch_mode` (auto-shape each grid's output columns; the true 2-D electrode geometry is a later refinement). This lands on the OTB hardening branch since it depends on that unmerged source. The framework feature here is fully testable via the Task 8 synthetic source without it.

## Verification (end-to-end)

- `uv run pytest tests/test_channel_grid.py tests/test_channel_grid_serialization.py tests/test_signal_viewer_decimation.py -q` → green (pure core, serialization round-trip, decimate-enabled).
- Full suite `uv run pytest -q` green (session/replay/viewer regressions; known LSL multicast flake aside).
- `uv run python -m py_compile examples/synthetic/channel_grid_demo.py`; ruff clean.
- **Manual:** run `channel_grid_demo.py`, start the generator, confirm the grid renders per-IN, click/drag/shift select works, only enabled channels plot, and a 256-ch stream stays responsive with `initial_channels=range(16)`.

## Self-review notes
- Types consistent: `ChannelGrid.cells: list[list[int | None]]` and `columns` used the same way in Tasks 1-3, 6, 8.
- No placeholders except the deliberately manual imgui pixel behaviour (Task 6 → validated in Task 8), and the Task 4 "old session" test body (write meta without the key).
- Spec coverage: topology model (T1), auto-shape/normalize (T2), rect/reduce/initial (T3), serialization+schema (T4), decimate-enabled (T5), the widget+interaction+a11y (T6), initial_channels+per-stream state (T7), demo (T8). Quattrocento population is the noted follow-on.
