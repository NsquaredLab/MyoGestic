# Grid layout - Px and Fr

`@app.ui` panels are placed with a `Grid` that borrows the units of CSS
Grid. There are two track types - and **only** two - that mean the same
thing on both axes:

| Unit       | Meaning                                                                 |
|------------|-------------------------------------------------------------------------|
| `Px(n)`    | Exactly `n` pixels (fixed-size track).                                  |
| `Fr(n)`    | `n` shares of the space remaining after Px tracks are subtracted.       |

Bare numbers are **deliberately rejected** so a reader can never confuse
`300` ("pixels") with `300` ("shares of leftover space"). When the track
list is omitted entirely, every row/column is `Fr(1)` - i.e. shared equally.

## The shape of a Grid

```python
from myogestic.grid import Grid, Px, Fr

grid = Grid(3, 4)                   # 3 rows × 4 cols, every track Fr(1)

grid = Grid(
    8, 3,
    row_height=[Px(200), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1)],
    col_width =[Px(300), Fr(1), Fr(1)],
)
```

`row_height` and `col_width` must each be exactly the same length as
`rows`/`cols` - short lists raise a `ValueError` at construction time, not
at first render.

## Placing panels

Index the grid in `[row, col]` form. Slices span across tracks:

```python
@app.ui
def my_ui(ctx):
    with grid[0, 0:4]:        # row 0, full width (4-column span)
        signal_viewer(ctx, "emg")
    with grid[1, 0:2]:        # row 1, left half
        scatter2d("UMAP", pts)
    with grid[2, 0]:          # single cell
        imgui.button("Record")
```

Each `with grid[...]` block opens an ImGui child window sized to the cell.
The cell background uses the active theme's `Col_.child_bg`, so light/dark
mode just works without per-panel styling.

## How sizes resolve

Each frame, the grid measures the parent window, subtracts `Px` totals
and the gutters between tracks (`GUTTER = 6` px), then divides what's
left among the `Fr` tracks proportionally to their values:

* `[Fr(1), Fr(2)]` over 600 px of remaining space → `200, 400`.
* `[Px(300), Fr(1), Fr(1)]` over 900 px total → `300, 300, 300`.
* `[Px(600), Fr(1)]` over 500 px total → `600, 0` (Px overflow is
  preserved; the Fr track collapses to zero rather than clipping the Px).

Resize the window: only `Fr` tracks change. `Px` tracks stay fixed,
which is what you want for fixed-width side panels (control palettes,
status panels, logos).

## Patterns that come up a lot

**A logo strip across the top:**

```python
grid = Grid(7, 3, row_height=[Px(80), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1)])
with grid[0, 0:3]:
    app_logo()
```

**A fixed control palette on the left:**

```python
grid = Grid(4, 3, col_width=[Px(280), Fr(1), Fr(1)])
with grid[0:4, 0]:
    movement_palette(...)
with grid[0, 1:3]:
    signal_viewer(...)
```

**Equal split - no track list:**

```python
grid = Grid(2, 2)        # four equal cells
with grid[0, 0]: imgui.text("top left")
with grid[0, 1]: imgui.text("top right")
with grid[1, 0]: imgui.text("bottom left")
with grid[1, 1]: imgui.text("bottom right")
```

## Validation

The grid eagerly rejects shapes that would silently misbehave:

| Input                           | Error                                    |
|---------------------------------|------------------------------------------|
| `row_height=[300, 1, 1]`        | `TypeError` - wrap in `Px` or `Fr`.      |
| `row_height=[Px(-50), Fr(1)]`   | `ValueError` - must be non-negative.     |
| `row_height=[Px(float("inf"))]` | `ValueError` - must be finite.           |
| `Px(True)` / `Fr(False)`        | `TypeError` - `bool` is not numeric here.|
| 8-entry list for a 7-row grid   | `ValueError` - length mismatch.          |

These all fail at `Grid(...)` construction, not on first frame.

## Why no `auto` / content-sized tracks?

CSS Grid has an `auto` keyword that sizes a track to its content. We
don't - every cell is an ImGui child window, and ImGui needs the size up
front. If you want a content-sized panel, give the row a `Px(...)`
matching the panel's natural height (typically the height of one or two
text rows plus padding) and skip the surrounding child window's scrollbar
via `imgui.begin_child(..., child_flags=imgui.ChildFlags_.auto_resize_y)`
*inside* the cell.

## See also

* [`myogestic.grid`](../api/core.md) - full API reference for `Grid`, `Px`, `Fr`.
* [Anatomy of an app](../anatomy.md) - where the grid fits in the
  `@app.ui` lifecycle.
