# Design: Spatial channel-selection grid for the signal viewer

**Status:** design, pending review · **Codex-reviewed:** thread 019f7949

## Context / problem

The signal viewer's channel enable/disable UI (`myogestic/widgets/signals/_controls.py::render_channel_controls`) renders **one button per channel** — a wall of 256 colored buttons at high channel counts (HD-EMG / Quattrocento). It's unusable: you can't find a channel, and toggling a region means many clicks. A student fork prototyped grid-aware dropdowns; this is the refined, spatial version.

There is also a real performance issue the button wall hides: the viewer decimates **all** channels every frame regardless of which are enabled (`build_signal_frame` runs before the controls, and `_m4_decimate_visible_window` loops over every column and unions all channels' extrema — which barely decimates when channels are independent). So "just enable fewer channels" does **not** make a 256-channel stream responsive today. This design fixes both: a compact spatial toggle grid, and decimation that operates on **only the enabled channels**.

## Goals / non-goals

**Goals**
- Replace the button wall with a compact, grid-aware **spatial toggle grid**: cells laid out by electrode grid; click to toggle, drag to rubber-band a region, per-grid + global all/none/invert.
- Carry channel **topology in `StreamInfo`** (expressive, serialized) so it survives recording → replay.
- **Decimate only enabled channels**, so limiting the view actually restores responsiveness.
- **Configurable initial selection** so a 256-channel stream doesn't open as a 256-line plot.
- A **pure-function core** (imgui-free) with property tests; accessible cells.

**Non-goals**
- Activity/heatmap coloring of cells (a separate feature; cells here show on/off, not signal level).
- True electrode geometry for every device — we auto-shape a grid into a rectangle when the physical layout is unknown, and never claim false topology.
- The acquire-thread M4 (already handled separately). This design only touches the **viewer-side** visible-window decimation.

## Data model — topology in `StreamInfo`

Add an optional field (default `None`, so every existing source and old session is unaffected):

```python
@dataclass(frozen=True)
class ChannelGrid:
    label: str                      # "IN1", "grid 0", ...
    cells: list[list[int | None]]   # 2D map: output-column index, or None for an empty cell

@dataclass
class StreamInfo:
    ...
    channel_grids: list[ChannelGrid] | None = None
```

- `cells` is an explicit **cell → output-column map**. This is deliberately expressive (Codex): the Quattrocento `select` can be sparse/reordered (`[10, 100, 115]`), grids can have holes, electrodes can be serpentine/rotated. A count-based spec ("label + N contiguous channels") cannot represent that; the 2D `int | None` map can.
- **Known topology** (e.g. `QuattrocentoSource`) populates the true grouping — one grid per IN — from its `select`/`nch_mode`. If the physical 2D geometry is unknown, it **auto-shapes** that grid's column list into a near-rectangle (row-major) — a valid special case of `cells`, explicitly *derived*, not claimed as physical.
- **No topology** (LSL, Muovi, replay of old sessions): `channel_grids is None` → the viewer auto-shapes **all** channels into a single grid.
- **Validation lives in the viewer, not `StreamInfo.__post_init__`** — a malformed layout hint must never block acquisition (Codex). `__post_init__` keeps only the existing dtype check; the viewer normalizes/validates and falls back to auto-shape on anything malformed.

## Serialization (session round-trip)

`StreamInfo` is serialized per stream into session meta (`session/_core.py::save_meta`) and reconstructed on load (`session/_io.py::open_session_store`). `channel_grids` must round-trip so **`ReplaySource` preserves topology** (at replay the original source is gone — this is the core reason topology belongs in `StreamInfo`, not a `source.channel_layout()` hook).

- Explicit JSON encode/decode of `channel_grids` (list of `{label, cells}`); `cells` is JSON-native (nested arrays with `null`).
- **Bump the session schema version**; tolerant decode: a missing key → `None` (old sessions load unchanged).
- Fix-forward the existing inconsistency noted in review: `save_meta` currently omits `channel_names` while `open_session_store` reads it — write both `channel_names` and `channel_grids` in `save_meta` so the round-trip is real. Add a round-trip test.

## Viewer restructure — decimate only enabled channels

Today (`widgets/signals/viewer.py`): `build_signal_frame` (decimate **all**) → `render_channel_controls` (resolve `enabled`) → `render_plot(enabled)`.

New order: **resolve `enabled` from viewer state first** → `build_signal_frame(enabled)` decimating **only** the enabled columns → `render_plot` → `render_channel_controls` (mutates `enabled` for the next frame). Immediate-mode means a selection change lands one frame later — imperceptible.

- `_m4_decimate_visible_window` (and the window slice feeding it) take the enabled column subset; the union-of-extrema now spans only enabled channels, so at 16-of-256 the decimation cost drops ~16×. This is what makes `initial_channels` deliver real responsiveness and pairs with the merged acquire-thread M4 fix.
- `hovered_ch` from the controls still drives the plot highlight (unchanged contract).

## The spatial toggle-grid widget

Replaces the button-wall body of `render_channel_controls`; **same signature and return** `(enabled: set[int], ch_names, hovered_ch)` — a drop-in, so `render_plot` is untouched.

- **Layout**: per grid, draw cells row-major from `cells` (empty cells render as blank gaps). DPI-scaled minimum cell size. **Enabled** = channel's palette color + a filled dot; **disabled** = dim with a hollow border — an on/off distinction beyond brightness alone (colorblind-safe). Per-grid header `IN1  8/64  [all][none]`; footer `enabled 24/256  [all][none][invert]`.
- **Interaction** (the risky part — snapshot state at mouse-down, don't re-toggle per frame):
  - Click (below ImGui's drag threshold) → toggle that cell.
  - Drag (past threshold) → rubber-band **2-D rectangle**. Capture the mouse-down cell, its state, and the operation (add if it was off, remove if on) at mouse-down; apply that op to the rectangle each frame **from the captured snapshot**, not by repeatedly toggling. **Hit-test cursor coordinates against the grid geometry** rather than trusting per-cell hover (ImGui's active item suppresses others' hover during a drag). Handle release outside the grid and focus loss.
  - **Shift-click** → linear channel-index range from the last click (1-D); **Ctrl/Cmd** → additive toggle. (Shift = linear range, drag = 2-D rectangle — disambiguated explicitly.)
  - Hover → tooltip (grid label · output-column index · channel name) and set `hovered_ch`.
  - Keyboard: cells are focusable, Space toggles the focused cell.
- **Stable IDs** keyed by `(stream, output-column)`, never by label or row position.

## Initial selection + selection state

- `signal_viewer(ctx, name, initial_channels: Iterable[int] | None = None)` — consumed **once** when the `ViewerState` is first created (like other viewer args), never re-applied per frame (that would overwrite user choices). No `int` overload: `range(16)` means "first 16" unambiguously.
- `None` policy: `n ≤ 32` → all enabled (today's behavior preserved); otherwise a **bounded useful subset** — the first `min(n, 16)` channels — and the footer reads `16 of 256 enabled`. Never an unexplained empty plot; never "first grid" blindly (a grid can be 64).
- **Selection state keyed by active stream identity** (+ channel count), not just the widget id — fixes the existing bug where switching a `selectable` viewer's stream resets one shared channel set.

## Pure-function core (imgui-free, tested)

Extract so the imgui layer is a thin shell:

- `normalize_layout(channel_grids, n_channels) -> list[ChannelGrid]` — validate, drop out-of-range/duplicate columns, fall back to auto-shape.
- `auto_shape(columns) -> list[list[int | None]]` — near-rectangle, row-major.
- `rect_to_channels(grid, r0, c0, r1, c1) -> set[int]` — order-independent; skips empty cells.
- `resolve_initial(initial_channels, n_channels, layout) -> set[int]` — the None policy above.
- `reduce_selection(enabled, op, targets) -> set[int]` — add / remove / toggle / invert / all / none.

**Property / table tests**: `invert∘invert == identity`; every result ⊆ `[0, n)`; sparse layouts never select an empty cell (holes preserved); dragging a rectangle in either direction yields the same set; `auto_shape` covers exactly the input columns.

## Testing

- Pure-function unit + property tests (above).
- **Serialization round-trip**: `StreamInfo(channel_grids=…)` → `save_meta` → `open_session_store` → equal; old-session (no field) → `None`.
- **Decimate-enabled**: headless test that `build_signal_frame` with a subset decimates only those columns (extend the existing `tests/test_stream_m4_*`).
- imgui rendering: manual via `examples/synthetic/high_channel_viewer.py` (extended to set `channel_grids`); plus a small smoke test that `render_channel_controls` returns a valid `(enabled, names, hovered)` without raising.

## Risks

- **Serialization / schema version** — old sessions must load unchanged (tolerant decode; test).
- **Viewer reorder** could shift frame timing / hover subtly — covered by the decimate-enabled test + manual demo.
- **imgui drag semantics** — the classic click/drag/hover/release-outside pitfalls; mitigated by snapshot-at-mouse-down + geometry hit-testing.
- **Auto-shape must never claim false physical geometry** for a known grid — it's labelled derived, and known sources supply the real grouping.
- **Scope split**: the framework parts (StreamInfo field, viewer, widget, decimate-enabled) land as one upstream PR off `main`; the `QuattrocentoSource.channel_grids` population is a small addition that rides with the OTB source work (it depends on that unmerged source). The framework feature is testable without it via a synthetic source.
