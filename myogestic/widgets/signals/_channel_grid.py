"""Pure grid-layout helpers for the spatial channel-selection widget.

Deliberately imgui-free: everything here operates on plain
`ChannelGrid` values and lists of ints, so it can be
unit tested without a rendering context and reused by any future
non-imgui frontend.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import ceil, sqrt

from myogestic.stream import ChannelGrid


def auto_shape(columns: list[int]) -> list[list[int | None]]:
    """Lay `columns` out row-major into a near-square grid.

    Uses ``cols = ceil(sqrt(len(columns)))`` for the row width, fills rows
    left-to-right / top-to-bottom, and pads the final row with ``None`` so
    every row has equal length.
    """
    n = len(columns)
    if n == 0:
        return []
    n_cols = ceil(sqrt(n))
    cells: list[list[int | None]] = []
    for start in range(0, n, n_cols):
        row: list[int | None] = list(columns[start : start + n_cols])
        row.extend([None] * (n_cols - len(row)))
        cells.append(row)
    return cells


def grid_arrangement(n_grids: int) -> int:
    """Number of columns to tile ``n_grids`` grid blocks into, near-square.

    ``ceil(sqrt(n))`` columns, so multiple grids are shown side by side in a
    compact block instead of one tall vertical stack — e.g. 6 grids lay out as
    3 columns × 2 rows, 4 as 2 × 2. Always at least 1.
    """
    if n_grids <= 1:
        return 1
    return ceil(sqrt(n_grids))


def _dedupe_in_range(columns: list[int], n_channels: int) -> list[int]:
    """First-seen columns within ``[0, n_channels)``, deduplicated, order preserved."""
    seen: set[int] = set()
    kept: list[int] = []
    for c in columns:
        if 0 <= c < n_channels and c not in seen:
            seen.add(c)
            kept.append(c)
    return kept


def _is_rectangular(cells: list[list[int | None]]) -> bool:
    """True when `cells` is a non-empty list of equal-length, non-empty rows."""
    if not cells:
        return False
    width = len(cells[0])
    if width == 0:
        return False
    return all(len(row) == width for row in cells)


def _null_invalid_cells(cells: list[list[int | None]], n_channels: int) -> list[list[int | None]]:
    """Copy `cells`, replacing out-of-range / duplicate entries with ``None``.

    Traverses row-major (same order as `ChannelGrid.columns`) so the
    "first-seen" column wins ties the same way [`_dedupe_in_range`][] does.
    """
    seen: set[int] = set()
    result: list[list[int | None]] = []
    for row in cells:
        new_row: list[int | None] = []
        for c in row:
            if c is not None and 0 <= c < n_channels and c not in seen:
                seen.add(c)
                new_row.append(c)
            else:
                new_row.append(None)
        result.append(new_row)
    return result


def resolve_scope(channel_scope: Iterable[int] | None, n_channels: int) -> list[int]:
    """Resolve the columns a viewer may **ever** show, in caller order.

    ``None`` means unrestricted — every channel. An explicit iterable is
    clamped to ``[0, n_channels)`` and de-duplicated (first-seen wins), and
    **may resolve to empty**: an explicit constraint that matches nothing is
    honoured rather than quietly widened back to the whole stream, which would
    defeat the point of scoping a panel. Order is preserved because the default
    selection policy takes a prefix of it (see [`resolve_initial`][]).
    """
    if channel_scope is None:
        return list(range(n_channels))
    return _dedupe_in_range(list(channel_scope), n_channels)


def normalize_layout(
    channel_grids: list[ChannelGrid] | None,
    n_channels: int,
    scope: list[int] | None = None,
) -> list[ChannelGrid]:
    """Validate `channel_grids` against `n_channels`, never raising.

    Out-of-range and duplicate column indices are dropped (first-seen wins).
    A grid whose ``cells`` aren't rectangular is re-laid-out with
    [`auto_shape`][] over its surviving columns; a rectangular grid keeps
    its shape with invalid entries nulled out instead. Grids left with no
    valid columns are dropped entirely. If nothing survives — `channel_grids`
    is ``None``/empty, or every grid was fully invalid — falls back to a
    single auto-shaped grid labeled ``"all"`` spanning every channel.

    `scope` (from [`resolve_scope`][]) restricts the layout to a viewer's own
    columns: out-of-scope cells are **nulled, not dropped**, so a rectangular
    grid keeps its physical shape and — because [`rect_to_channels`][] skips
    ``None`` — a rubber-band drag cannot reach outside the scope. Grids left
    empty are removed, and any scoped column no grid covers is collected into a
    trailing auto-shaped ``"other"`` grid, so everything **All** can select is
    also individually toggleable. ``None`` leaves the layout unrestricted.
    """
    fallback_columns = list(range(n_channels)) if scope is None else list(scope)
    fallback = [ChannelGrid("all", auto_shape(fallback_columns))] if fallback_columns else []
    if not channel_grids:
        return fallback

    scope_set = None if scope is None else set(scope)
    result: list[ChannelGrid] = []
    for grid in channel_grids:
        valid_columns = _dedupe_in_range(grid.columns, n_channels)
        if scope_set is not None:
            valid_columns = [c for c in valid_columns if c in scope_set]
        if not valid_columns:
            continue
        if _is_rectangular(grid.cells):
            new_cells = _null_invalid_cells(grid.cells, n_channels)
            if scope_set is not None:
                new_cells = [
                    [c if c is not None and c in scope_set else None for c in row]
                    for row in new_cells
                ]
        else:
            new_cells = auto_shape(valid_columns)
        result.append(ChannelGrid(grid.label, new_cells))

    if scope_set is not None and result:
        # Anything in scope that no surviving grid covers would be selectable via
        # All yet impossible to toggle in the grid window — give it a home.
        covered = {c for g in result for c in g.columns}
        missing = [c for c in scope if c not in covered]
        if missing:
            result.append(ChannelGrid("other", auto_shape(missing)))

    return result if result else fallback


def rect_to_channels(grid: ChannelGrid, r0: int, c0: int, r1: int, c1: int) -> set[int]:
    """Return the non-``None`` channels covered by the cell rectangle `(r0, c0)`-`(r1, c1)`.

    The corners are order-independent (dragging in any direction yields the
    same result); out-of-range corners — including small negatives that
    Python's slicing would otherwise wrap to the far edge — are clamped to
    the grid bounds instead.
    """
    n_rows = len(grid.cells)
    n_cols = len(grid.cells[0]) if n_rows else 0
    top, bottom = sorted((r0, r1))
    left, right = sorted((c0, c1))
    top = max(0, min(top, n_rows - 1))
    bottom = max(0, min(bottom, n_rows - 1))
    left = max(0, min(left, n_cols - 1))
    right = max(0, min(right, n_cols - 1))
    channels: set[int] = set()
    for row in grid.cells[top : bottom + 1]:
        for cell in row[left : right + 1]:
            if cell is not None:
                channels.add(cell)
    return channels


def reduce_selection(enabled: set[int], op: str, targets: Iterable[int]) -> set[int]:
    """Apply a selection `op` to `enabled`, returning the new selection set.

    `op` is one of ``"add"``, ``"remove"``, ``"toggle"``, ``"set"``,
    ``"invert"``, ``"all"``, ``"none"``. Callers drive ``invert``/``all``/
    ``none`` by passing the full channel range as `targets`.
    """
    target_set = set(targets)
    if op == "add" or op == "all":
        return enabled | target_set
    if op == "remove" or op == "none":
        return enabled - target_set
    if op == "toggle" or op == "invert":
        return enabled ^ target_set
    if op == "set":
        return target_set
    msg = f"unknown selection op: {op!r}"
    raise ValueError(msg)


def resolve_initial(
    initial_channels: Iterable[int] | None,
    n_channels: int,
    layout: list[ChannelGrid],
    *,
    scope: list[int] | None = None,
) -> set[int]:
    """Resolve the widget's initial selection.

    ``None`` selects every channel when `n_channels` is small (``<= 32``),
    otherwise the first ``min(n_channels, 16)``. An explicit iterable is
    clamped to the valid ``[0, n_channels)`` range. `layout` is accepted for
    interface symmetry with future policies but isn't consulted yet.

    `scope` (from [`resolve_scope`][]) makes the whole policy relative to a
    viewer's own columns: the size test and the 16-channel prefix both run over
    the scope, and an explicit selection is clamped to it. This has to be built
    in rather than filtered afterwards — for a scope of columns 256‥319 the
    unscoped policy would pick "the first 16 of 320", i.e. columns 0‥15, whose
    intersection with the scope is **empty**, leaving a dead panel.
    """
    del layout
    columns = list(range(n_channels)) if scope is None else scope
    if initial_channels is None:
        if len(columns) <= 32:
            return set(columns)
        return set(columns[:16])
    allowed = set(columns)
    return {c for c in initial_channels if c in allowed}
