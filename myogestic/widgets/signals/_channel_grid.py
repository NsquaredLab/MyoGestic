"""Pure grid-layout helpers for the spatial channel-selection widget.

Deliberately imgui-free: everything here operates on plain
:class:`~myogestic.stream.ChannelGrid` values and lists of ints, so it can be
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

    Traverses row-major (same order as :attr:`ChannelGrid.columns`) so the
    "first-seen" column wins ties the same way :func:`_dedupe_in_range` does.
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


def normalize_layout(channel_grids: list[ChannelGrid] | None, n_channels: int) -> list[ChannelGrid]:
    """Validate `channel_grids` against `n_channels`, never raising.

    Out-of-range and duplicate column indices are dropped (first-seen wins).
    A grid whose ``cells`` aren't rectangular is re-laid-out with
    :func:`auto_shape` over its surviving columns; a rectangular grid keeps
    its shape with invalid entries nulled out instead. Grids left with no
    valid columns are dropped entirely. If nothing survives — `channel_grids`
    is ``None``/empty, or every grid was fully invalid — falls back to a
    single auto-shaped grid labeled ``"all"`` spanning every channel.
    """
    fallback = [ChannelGrid("all", auto_shape(list(range(n_channels))))]
    if not channel_grids:
        return fallback

    result: list[ChannelGrid] = []
    for grid in channel_grids:
        valid_columns = _dedupe_in_range(grid.columns, n_channels)
        if not valid_columns:
            continue
        if _is_rectangular(grid.cells):
            new_cells = _null_invalid_cells(grid.cells, n_channels)
        else:
            new_cells = auto_shape(valid_columns)
        result.append(ChannelGrid(grid.label, new_cells))

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
) -> set[int]:
    """Resolve the widget's initial selection.

    ``None`` selects every channel when `n_channels` is small (``<= 32``),
    otherwise the first ``min(n_channels, 16)``. An explicit iterable is
    clamped to the valid ``[0, n_channels)`` range. `layout` is accepted for
    interface symmetry with future policies but isn't consulted yet.
    """
    del layout
    if initial_channels is None:
        if n_channels <= 32:
            return set(range(n_channels))
        return set(range(min(n_channels, 16)))
    return {c for c in initial_channels if 0 <= c < n_channels}
