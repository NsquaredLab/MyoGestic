---
title: "Grid layout - Px and Fr"
---
Place `@app.ui` panels with a `Grid`. Its two CSS Grid track types mean the
same thing on both axes. `Px` and `Fr` are the only supported track types.

| Unit       | Meaning                                                                 |
|------------|-------------------------------------------------------------------------|
| `Px(n)`    | Exactly `n` pixels at UI scale 1.0 (fixed-size track).                                  |
| `Fr(n)`    | `n` shares of the space remaining after Px tracks are subtracted.       |

Use `Px(300)` for 300 pixels or `Fr(300)` for 300 shares of leftover space.
Bare numbers are rejected so pixels cannot be confused with shares of leftover space. With no track list, every row/column is `Fr(1)`
and shares space equally.

## The shape of a Grid

```python
from myogestic.grid import Grid, Px, Fr

grid = Grid(3, 4)  # 3 rows × 4 cols, every track Fr(1)

grid = Grid(
    8,
    3,
    row_height=[Px(200), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1)],
    col_width=[Px(300), Fr(1), Fr(1)],
)
```

`row_height` and `col_width` must each be exactly the same length as
`rows`/`cols`. Short lists raise a `ValueError` at construction.

## Placing panels

Index the grid in `[row, col]` form. Slices span across tracks:

```python
emg_viewer = SignalViewer("emg")
umap = Scatter2D("UMAP")


@app.ui
def my_ui(ctx):
    with grid[0, 0:4]:  # row 0, full width (4-column span)
        emg_viewer.ui(ctx)
    with grid[1, 0:2]:  # row 1, left half
        umap.ui(pts)
    with grid[2, 0]:  # single cell
        imgui.button("Record")
```

Each `with grid[...]` block opens an ImGui child window sized to the cell.
The cell background uses the active theme's `Col_.child_bg`, so light and dark
mode both render correctly without per-panel styling.

## How sizes resolve

Each frame, the grid measures the parent window, subtracts `Px` totals
and the gutters between tracks, `GUTTER = 12` px, then divides what's
left among the `Fr` tracks proportionally to their values. `Px` values and
the gutter are pixels at UI scale 1.0 and are multiplied by the live scale.
See [UI scale](#ui-scale). These examples use scale 1.0.

* `[Fr(1), Fr(2)]` over 600 px of remaining space → `200, 400`.
* `[Px(300), Fr(1), Fr(1)]` over 900 px total → `300, 288, 288` after the two 12 px gutters.
* `[Px(600), Fr(1)]` over 500 px total → `600, 0`. Px overflow is preserved;
  the Fr track collapses to zero.

When you resize the window, `Fr` tracks absorb the change. `Px` tracks stay fixed relative to the text. They grow or shrink only with UI scale. Use them for fixed-width control palettes, status panels or
logos. A `Px(300)` sidebar keeps its proportion to its labels on a laptop
and a 4K monitor.

## UI scale

One number scales the fonts, imgui's padding and spacing, and every `Px`
track. The default is the OS display scale multiplied by the window size
relative to 1280 × 800. Windows at 150 % uses a display scale of 1.5. The window
factor is limited to ×0.85–×1.3; the result is rounded in 0.05 steps and clamped
to 0.5–2.0. It is recomputed every frame on resize or monitor change. Set
`App(ui_scale=1.1)` or `MYOGESTIC_UI_SCALE=1.1` for a fixed scale. The shell
setting takes precedence.

The scale floor is deliberately limited. A window too small for its arrangement needs
a different arrangement rather than smaller text. Use `Layout` to change it.

## Named areas and reflow

`Grid.areas` draws the arrangement as text and names every panel. A name
repeated across a rectangle spans it, `.` leaves a cell empty, and `a | b`
puts panels that are never needed at the same time in one cell, as tabs.
`Layout` holds two such arrangements and picks one per frame from the window
width:

<!--docs:run-->
```python
from myogestic import Fr, Grid, Layout, Px

layout = Layout(
    wide=Grid.areas(
        """
        logo      signal   signal
        record    signal   signal
        sessions  fuzzy    fuzzy
        train     fuzzy    fuzzy
        """,
        col_width=[Px(260), Fr(1), Fr(1)],
    ),
    narrow=Grid.areas(
        """
        signal
        record
        sessions | train
        logo | fuzzy
        """,
    ),
    breakpoint=Px(1100),
)
assert layout.panel_names == {"logo", "signal", "record", "sessions", "train", "fuzzy"}
```

`@app.ui` places panels by name and does not change between the two:

```python
@app.ui
def ui(ctx):
    with layout["signal"]:
        viewer.ui(ctx)
    with layout["sessions"]:
        pipeline.training_data = sessions.ui()
```

Reflow behaviour

* Below the breakpoint, panels move to the narrow arrangement.
* Widget state survives the switch. Your widgets are the same Python
  objects in both arrangements. A panel's child window is keyed by its name,
  not its position, so a panel with a cell of its own in both arrangements
  also keeps its scroll position; one that moves into or out of a tab group
  starts scrolled to the top.
* A hidden tab still runs. Its body executes every frame inside a clipped
  window. The widgets draw nothing, but return values keep flowing, so
  `pipeline.training_data = sessions.ui()` stays current while the Train tab is
  showing.
* The breakpoint is in scale-1.0 pixels, so it switches at the same window
  size relative to the text on every screen.
* Group tabs by session phase, such as setup, recording, training or
  predicting. Keep the live signal, Record/Stop and prediction in their own cells.

Both arrangements must place the same panels; `Layout(...)` raises at
construction, naming the ones that differ. A plain `Grid` indexed by
`[row, col]` keeps working and never reflows.

### Bare areas

Pass area names in `bare` for a header or status strip without a border or
background. Each area remains a clipped child window; short standalone bare rows reduce vertical padding to fit a control,
and `Layout` preserves each arrangement's bare areas. Unknown names raise a
`ValueError` when the grid is constructed.

<!--docs:run-->
```python
from myogestic import Fr, Grid, Px

grid = Grid.areas(
    """
    header
    signal
    status
    """,
    row_height=[Px(52), Fr(1), Px(26)],
    bare=("header", "status"),
)
assert grid.panel_names == {"header", "signal", "status"}
```

## Patterns that come up a lot

A logo strip across the top

```python
grid = Grid(7, 3, row_height=[Px(80), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1)])
logo = AppLogo()
with grid[0, 0:3]:
    logo.ui()
```

A fixed control palette on the left

```python
grid = Grid(4, 3, col_width=[Px(280), Fr(1), Fr(1)])
emg_viewer = SignalViewer("emg")
with grid[0:4, 0]:
    movement_palette(...)
with grid[0, 1:3]:
    emg_viewer.ui(ctx)
```

Equal split without a track list

```python
grid = Grid(2, 2)  # four equal cells
with grid[0, 0]:
    imgui.text("top left")
with grid[0, 1]:
    imgui.text("top right")
with grid[1, 0]:
    imgui.text("bottom left")
with grid[1, 1]:
    imgui.text("bottom right")
```

## Validation

The grid validates track values and list lengths at construction.

| Input                           | Error                                    |
|---------------------------------|------------------------------------------|
| `row_height=[300, 1, 1]`        | `TypeError` - wrap in `Px` or `Fr`.      |
| `row_height=[Px(-50), Fr(1)]`   | `ValueError` - must be non-negative.     |
| `row_height=[Px(float("inf"))]` | `ValueError` - must be finite.           |
| `Px(True)` / `Fr(False)`        | `TypeError` - `bool` is not numeric here.|
| 8-entry list for a 7-row grid   | `ValueError` - length mismatch.          |

These inputs fail at `Grid(...)` construction.

<a id="why-no-auto--content-sized-tracks"></a>

## Content-sized tracks

CSS Grid supports content-sized `auto` tracks. MyoGestic does not support `auto` because
every cell is an ImGui child window, which needs its size before rendering. For a content-sized
panel, set the row's `Px(...)` to its natural height, typically one or two
text rows plus padding. Inside the cell, skip the surrounding child window's
scrollbar with `imgui.begin_child(..., child_flags=imgui.ChildFlags_.auto_resize_y)`.

## See also

* [`myogestic.grid`](../api/core.md) - full API reference for `Grid`, `Layout`, `Px`, `Fr`.
* [Anatomy of an app](../anatomy.md) - where the grid fits in the
  `@app.ui` lifecycle.
