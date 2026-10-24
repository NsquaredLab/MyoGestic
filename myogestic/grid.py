"""Matplotlib-style grid layout for @app.ui functions.

Track sizes use CSS-Grid-style units that mean the same thing on both axes:

* [`Px(n)`][Px] — ``n`` pixels at UI scale 1.0 (fixed-size track; follows the
  scale, so a ``Px(300)`` sidebar keeps its proportion to the text).
* [`Fr(n)`][Fr] — ``n`` shares of the *remaining* space after the
  Px tracks are subtracted (proportional track).

Track entries must be ``Px(...)`` or ``Fr(...)``: bare numbers are
deliberately rejected so a reader can never confuse "300 pixels" with
"300 shares of leftover space". Default (no track list) is all-``Fr(1)``,
i.e. equal distribution.

Examples
--------
::

    from myogestic.grid import Grid, Px, Fr

    grid = Grid(3, 4) # 3 equal rows x 4 equal cols
    grid = Grid(
        8, 3,
        row_height=[Px(200), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1), Fr(1)],
        col_width =[Px(300), Fr(1), Fr(1)],
    )

    @app.ui
    def my_ui(ctx):
        with grid[0, 0:4]:          # row 0, full width
            signal_viewer(ctx, "emg")
        with grid[1, 0:2]:          # row 1, left half
            scatter2d("UMAP", pts)
        with grid[2, 0]:            # single cell
            imgui.button("Record")
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from imgui_bundle import imgui

from myogestic._scale import current_scale

#: Gap between adjacent cells, in pixels at UI scale 1.0. The panels themselves
#: carry a border and `window_padding`, so this only has to separate two cards —
#: but at 6 px they read as one slab with lines drawn on it rather than as
#: separate panels. Scaled with everything else, see `_gutter`.
GUTTER: float = 12


def _gutter() -> float:
    return GUTTER * current_scale()


def _content_rect() -> tuple[imgui.ImVec2, imgui.ImVec2]:
    """Read the parent's content bounds independently of child-padding styles."""
    origin = imgui.get_cursor_start_pos()
    cursor, available = imgui.get_cursor_pos(), imgui.get_content_region_avail()
    # Begin captures padding and decorations for the parent. The live style may
    # already specify different padding for our children, so use its real bounds.
    # Cursor + remaining space is stable even after another cell was submitted.
    return origin, imgui.ImVec2(
        cursor.x + available.x - origin.x, cursor.y + available.y - origin.y,
    )


def _validate_value(value: object, kind: str) -> float:
    """Coerce a Px/Fr constructor arg to a non-negative finite float.

    Rejects ``bool`` (which is a subclass of ``int`` so would otherwise
    sneak through) and gives a clean error for non-numeric inputs like
    ``Px("300")`` instead of letting ``math.isfinite`` raise.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"{kind}({value!r}): value must be an int or float, got {type(value).__name__}"
        )
    v = float(value)
    if not math.isfinite(v) or v < 0:
        raise ValueError(f"{kind}({value!r}): value must be finite and non-negative")
    return v


@dataclass(frozen=True, slots=True)
class Px:
    """Fixed size. ``Px(300)`` means "300 px at UI scale 1.0".

    The track follows the live UI scale (see ``App(ui_scale=...)``), so a fixed
    sidebar grows and shrinks with the text it holds instead of drifting out of
    proportion between a laptop and a 4K monitor.

    Examples
    --------
    >>> from myogestic import Px
    >>> Px(300)
    Px(300)
    """

    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validate_value(self.value, "Px"))

    def __repr__(self) -> str:
        return f"Px({self.value:g})"


@dataclass(frozen=True, slots=True)
class Fr:
    """Fractional unit (CSS-grid ``fr``).

    ``Fr(1)`` means "1 share of the space remaining after [`Px`][]
    tracks are subtracted". Multiple ``Fr`` entries split the remainder
    proportionally to their values, so ``[Fr(1), Fr(2)]`` splits leftover
    space 1:2.

    Examples
    --------
    >>> from myogestic import Fr
    >>> Fr(2)
    Fr(2)
    """

    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validate_value(self.value, "Fr"))

    def __repr__(self) -> str:
        return f"Fr({self.value:g})"


Track = Px | Fr
"""A single grid track size: either a fixed [`Px`][] or a fractional [`Fr`][].

Examples
--------
>>> from myogestic.grid import Px, Track
>>> track: Track = Px(300)
"""


def _coerce(spec: object, axis: str, index: int) -> Track:
    """Coerce a track spec to a [`Px`][] or [`Fr`][] instance.

    Track entries must be ``Px(...)`` or ``Fr(...)`` — bare numbers are
    rejected so ``[300, 1, 1]`` can't be silently misread as pixels.
    """
    if isinstance(spec, (Px, Fr)):
        return spec
    raise TypeError(
        f"{axis}[{index}] = {spec!r}: must be Px(...) or Fr(...). "
        f"Bare numbers are not accepted — wrap in Px (pixels) or Fr (fractional)."
    )


def _resolve_tracks(tracks: list[Track], avail: float, scale: float = 1.0) -> list[float]:
    """Resolve a list of Px/Fr tracks to pixel sizes for ``avail`` total space.

    Px tracks keep their declared value times ``scale``. Fr tracks share whatever
    remains (clamped at zero — Px overflow is preserved, never auto-shrunk).
    """
    fixed_total = sum(t.value * scale for t in tracks if isinstance(t, Px))
    fr_total = sum(t.value for t in tracks if isinstance(t, Fr))
    fr_avail = max(0.0, avail - fixed_total)
    fr_scale = (fr_avail / fr_total) if fr_total > 0 else 0.0
    return [t.value * scale if isinstance(t, Px) else t.value * fr_scale for t in tracks]


#: One rectangle of the template: (row_start, row_end, col_start, col_end).
_Rect = tuple[int, int, int, int]


def _parse_areas(template: str) -> tuple[int, int, dict[str, _Rect]]:
    """Parse a `Grid.areas` template into its size and one rectangle per token.

    A token is a panel name, ``a|b|c`` (panels sharing a cell as tabs), or ``.``
    (empty). Each token must cover a rectangle.
    """
    lines = [ln for ln in template.splitlines() if ln.strip()]
    if not lines:
        raise ValueError("Grid.areas(): the template is empty — write one line per row")
    rows = [re.sub(r"\s*\|\s*", "|", ln).split() for ln in lines]
    cols = len(rows[0])
    for r, row in enumerate(rows):
        if len(row) != cols:
            raise ValueError(
                f"Grid.areas(): row {r} has {len(row)} cells but row 0 has {cols} — "
                f"every row needs the same number of cells (use '.' for an empty one)"
            )
    cells: dict[str, list[tuple[int, int]]] = {}
    for r, row in enumerate(rows):
        for c, token in enumerate(row):
            if token != ".":
                cells.setdefault(token, []).append((r, c))
    rects: dict[str, _Rect] = {}
    for token, where in cells.items():
        r0, r1 = min(r for r, _ in where), max(r for r, _ in where) + 1
        c0, c1 = min(c for _, c in where), max(c for _, c in where) + 1
        if len(where) != (r1 - r0) * (c1 - c0):
            raise ValueError(
                f"Grid.areas(): {token!r} is not a rectangle — it spans rows {r0}-{r1 - 1} "
                f"and columns {c0}-{c1 - 1}, so every cell in that block must say {token!r}"
            )
        rects[token] = (r0, r1, c0, c1)
    return len(rows), cols, rects


class Grid:
    """Grid layout manager. Index with ``[row, col]`` or ``[row, col_start:col_end]``.

    Both axes accept the same Px/Fr track specs. See module docstring for
    examples.

    Parameters
    ----------
    rows
        Number of rows.
    cols
        Number of columns.
    row_height
        Per-row track specs (length must equal ``rows``).
        Default ``None`` → all rows share equally (``[Fr(1)] * rows``).
    col_width
        Per-column track specs (length must equal ``cols``).
        Default ``None`` → all columns share equally (``[Fr(1)] * cols``).

    Raises
    ------
    ValueError
        if a list length doesn't match ``rows`` / ``cols``, or
        if any track value is non-finite or negative.
    TypeError
        if a track entry isn't Px, Fr, or a number.

    Examples
    --------
    >>> from myogestic import Fr, Grid, Px
    >>> grid = Grid(2, 3, row_height=[Px(120), Fr(1)])
    >>> (grid.rows, grid.cols)
    (2, 3)
    """

    def __init__(
        self,
        rows: int,
        cols: int,
        row_height: list[Track] | None = None,
        col_width: list[Track] | None = None,
    ):
        if not isinstance(rows, int) or isinstance(rows, bool) or rows <= 0:
            raise ValueError(f"rows must be a positive int, got {rows!r}")
        if not isinstance(cols, int) or isinstance(cols, bool) or cols <= 0:
            raise ValueError(f"cols must be a positive int, got {cols!r}")
        self.rows = rows
        self.cols = cols
        self._row_tracks: list[Track] = self._normalize(row_height, rows, "row_height")
        self._col_tracks: list[Track] = self._normalize(col_width, cols, "col_width")
        self._scaled_heights: list[float] = [0.0] * rows
        self._last_frame: int = -1
        # Named areas (see `Grid.areas`): panel name -> rectangle, and for panels
        # sharing a cell as tabs, panel name -> its group's members.
        self._areas: dict[str, _Rect] = {}
        self._bare: frozenset[str] = frozenset()
        self._groups: dict[str, tuple[str, ...]] = {}
        self._selected: dict[tuple[str, ...], str] = {}  # group -> selected tab
        self._tab_frame: dict[tuple[str, ...], int] = {}  # group -> frame its tabs drew

    @classmethod
    def areas(
        cls,
        template: str,
        *,
        row_height: list[Track] | None = None,
        col_width: list[Track] | None = None,
        bare: Iterable[str] = (),
    ) -> Grid:
        """A grid whose cells are named, drawn as text. Place panels with `area`.

        One line per row, one word per cell. A name repeated across a rectangle
        spans it; ``.`` leaves a cell empty; ``a | b | c`` puts panels that are
        never needed at the same time in one cell, as tabs. Naming panels instead
        of indexing ``[row, col]`` is what lets a `Layout` move them between
        arrangements without losing their state.

        Parameters
        ----------
        template
            The arrangement, one line per row.
        row_height
            Per-row track specs; default all ``Fr(1)``.
        col_width
            Per-column track specs; default all ``Fr(1)``.
        bare
            Area names to draw without a border or background. Their child
            windows retain the same padding and content clipping.

        Raises
        ------
        ValueError
            if rows differ in length, a name does not cover a rectangle, a panel
            is placed twice, a track list has the wrong length, or ``bare``
            contains an unknown area name.

        Examples
        --------
        >>> from myogestic import Fr, Grid, Px
        >>> grid = Grid.areas('''
        ...     logo               signal
        ...     record             signal
        ...     sessions | train   signal
        ... ''', col_width=[Px(260), Fr(1)])
        >>> (grid.rows, grid.cols)
        (3, 2)
        >>> sorted(grid.panel_names)
        ['logo', 'record', 'sessions', 'signal', 'train']
        """
        rows, cols, rects = _parse_areas(template)
        grid = cls(rows, cols, row_height=row_height, col_width=col_width)
        for token, rect in rects.items():
            members = tuple(token.split("|"))
            if any(not m for m in members):
                raise ValueError(f"Grid.areas(): {token!r} has an empty tab — write 'a | b'")
            for m in members:
                if m in grid._areas:
                    raise ValueError(
                        f"Grid.areas(): panel {m!r} is placed twice — give each panel one cell"
                    )
                grid._areas[m] = rect
                if len(members) > 1:
                    grid._groups[m] = members
        grid._bare = frozenset(bare)
        unknown = grid._bare - grid.panel_names
        if unknown:
            raise ValueError(
                f"Grid.areas(): unknown bare areas: {', '.join(sorted(unknown))} — "
                "use names placed in the template"
            )
        return grid

    @property
    def panel_names(self) -> frozenset[str]:
        """Every panel name placed by `Grid.areas`, tabbed ones included."""
        return frozenset(self._areas)

    def area(self, name: str) -> _AreaCell:
        """The cell for the panel called ``name`` — use as ``with grid.area("record"):``."""
        if name not in self._areas:
            known = ", ".join(sorted(self._areas)) or "none — build it with Grid.areas(...)"
            raise KeyError(f"no area named {name!r}; this grid has: {known}")
        return _AreaCell(self, name)

    @staticmethod
    def _normalize(specs: list[Track] | None, expected_len: int, axis: str) -> list[Track]:
        if specs is None:
            return [Fr(1.0)] * expected_len
        if len(specs) != expected_len:
            raise ValueError(f"{axis} has {len(specs)} entries but grid has {expected_len} tracks")
        return [_coerce(s, axis, i) for i, s in enumerate(specs)]

    def _init_frame(self) -> None:
        """Compute scaled row heights to fit the window. Called once per frame."""
        current_frame = imgui.get_frame_count()
        if current_frame == self._last_frame:
            return
        self._last_frame = current_frame
        _, content = _content_rect()
        avail_h = content.y - max(self.rows - 1, 0) * _gutter()
        self._scaled_heights = _resolve_tracks(self._row_tracks, avail_h, current_scale())

    def _row_y(self, row: int) -> float:
        """Y offset for the top of the given row."""
        return sum(self._scaled_heights[r] for r in range(row)) + row * _gutter()

    def _row_span_h(self, row_start: int, row_end: int) -> float:
        return (
            sum(self._scaled_heights[r] for r in range(row_start, row_end))
            + max(row_end - row_start - 1, 0) * _gutter()
        )

    def _scaled_col_widths(self, avail_w: float) -> list[float]:
        return _resolve_tracks(self._col_tracks, avail_w, current_scale())

    def _col_x(self, col: int, avail_w: float) -> float:
        scaled = self._scaled_col_widths(avail_w)
        return sum(scaled[c] for c in range(col)) + col * _gutter()

    def _col_span_w(self, col_start: int, col_end: int, avail_w: float) -> float:
        scaled = self._scaled_col_widths(avail_w)
        return (
            sum(scaled[c] for c in range(col_start, col_end))
            + max(col_end - col_start - 1, 0) * _gutter()
        )

    def _place(self, rect: _Rect) -> tuple[imgui.ImVec2, imgui.ImVec2]:
        """Cursor position and size of a cell, in the current window."""
        self._init_frame()
        row_start, row_end, col_start, col_end = rect
        origin, content = _content_rect()
        avail_w = content.x - max(self.cols - 1, 0) * _gutter()
        pos = imgui.ImVec2(
            self._col_x(col_start, avail_w) + origin.x, self._row_y(row_start) + origin.y,
        )
        size = imgui.ImVec2(
            self._col_span_w(col_start, col_end, avail_w), self._row_span_h(row_start, row_end)
        )
        # ImGui truncates child sizes to pixels. Round shared boundaries first,
        # so an odd Fr remainder belongs to a cell rather than an extra gutter.
        right, bottom = math.floor(pos.x + size.x), math.floor(pos.y + size.y)
        pos = imgui.ImVec2(math.floor(pos.x), math.floor(pos.y))
        size = imgui.ImVec2(right - pos.x, bottom - pos.y)
        return pos, size

    def __getitem__(self, key: tuple) -> _Cell:
        row, col = key
        if isinstance(col, slice):
            col_start = col.start if col.start is not None else 0
            col_end = col.stop if col.stop is not None else self.cols
        else:
            col_start = col
            col_end = col + 1
        if isinstance(row, slice):
            row_start = row.start if row.start is not None else 0
            row_end = row.stop if row.stop is not None else self.rows
        else:
            row_start = row
            row_end = row + 1
        return _Cell(self, row_start, row_end, col_start, col_end)


class _Cell:
    """Context manager that positions an ImGui child window in a grid cell."""

    def __init__(
        self,
        grid: Grid,
        row_start: int,
        row_end: int,
        col_start: int,
        col_end: int,
    ):
        self._grid = grid
        self._row_start = row_start
        self._row_end = row_end
        self._col_start = col_start
        self._col_end = col_end

    def __enter__(self) -> _Cell:
        pos, size = self._grid._place(
            (self._row_start, self._row_end, self._col_start, self._col_end)
        )
        imgui.set_cursor_pos(pos)
        # Cell background inherits Col_.child_bg from the active theme
        # rather than hardcoded here — keeps light/dark themes consistent.
        imgui.begin_child(
            f"##grid_{self._row_start}_{self._row_end}_{self._col_start}_{self._col_end}",
            size,
            child_flags=imgui.ChildFlags_.borders,
        )
        return self

    def __exit__(self, *args: object) -> None:
        imgui.end_child()


def _tab_label(name: str) -> str:
    return name.replace("_", " ").capitalize()


class _AreaCell:
    """Context manager for a named area.

    Its child id is the panel name, not its position, so a panel with a cell of
    its own in both of a `Layout`'s arrangements keeps its scroll position when
    the layout switches. (A tabbed panel's child lives inside its group's cell —
    a different parent window — so moving into or out of a group resets it.)

    A panel sharing its cell as a tab draws only while its tab is selected. When
    it is not, its body still runs — so a ``sessions.ui()`` return value keeps
    flowing — inside a child placed outside the window, which ImGui clips whole:
    every widget in it returns early, so it costs next to nothing.
    """

    def __init__(self, grid: Grid, name: str):
        self._grid = grid
        self._name = name
        self._ends = 0

    def __enter__(self) -> _AreaCell:
        g, name = self._grid, self._name
        pos, size = g._place(g._areas[name])
        group = g._groups.get(name)
        bare = name in g._bare
        window_flags = imgui.WindowFlags_.no_background if bare else 0
        imgui.set_cursor_pos(pos)
        if group is None:
            imgui.begin_child(
                f"##area_{name}", size,
                child_flags=(
                    imgui.ChildFlags_.always_use_window_padding if bare else imgui.ChildFlags_.borders
                ),
                window_flags=window_flags,
            )
            self._ends = 1
            return self

        # Shared cell: one bordered child per group, entered again by each member.
        # A child begun twice in a frame appends, so the second member continues
        # right under the tab bar the first one drew.
        key = "|".join(group)
        group_bare = g._selected.get(group, group[0]) in g._bare
        imgui.begin_child(
            f"##group_{key}", size,
            child_flags=(
                imgui.ChildFlags_.always_use_window_padding if group_bare else imgui.ChildFlags_.borders
            ),
            window_flags=imgui.WindowFlags_.no_background if group_bare else 0,
        )
        frame = imgui.get_frame_count()
        if g._tab_frame.get(group) != frame:
            g._tab_frame[group] = frame
            if imgui.begin_tab_bar(f"##tabs_{key}"):
                for member in group:
                    selected, _ = imgui.begin_tab_item(f"{_tab_label(member)}###{member}")
                    if selected:
                        g._selected[group] = member
                        imgui.end_tab_item()
                imgui.end_tab_bar()
        if g._selected.get(group, group[0]) == name:
            imgui.begin_child(f"##area_{name}", imgui.ImVec2(0, 0), window_flags=window_flags)
            self._ends = 2
            return self

        # Hidden tab: leave the group's child, then open this panel's child outside
        # the visible window so ImGui clips it whole.
        imgui.end_child()
        imgui.set_cursor_pos(imgui.ImVec2(-size.x - 10_000, -size.y - 10_000))
        imgui.begin_child(f"##area_{name}", size, window_flags=window_flags)
        self._ends = 1
        return self

    def __exit__(self, *args: object) -> None:
        for _ in range(self._ends):
            imgui.end_child()


class Layout:
    """Two arrangements of the same named panels, picked by window width.

    Above ``breakpoint`` the panels go where ``wide`` puts them; below it, where
    ``narrow`` does — typically one column, with panels used in different phases
    (record, train, predict) sharing a cell as tabs. The breakpoint is in pixels
    at UI scale 1.0, so it switches at the same size *relative to the text* on a
    laptop and on a 4K monitor. ``@app.ui`` code places panels by name and never
    changes between arrangements.

    Parameters
    ----------
    wide
        Arrangement for windows at least ``breakpoint`` wide (from `Grid.areas`).
    narrow
        Arrangement for narrower windows (from `Grid.areas`).
    breakpoint
        Window width, at scale 1.0, where the two swap.

    Raises
    ------
    ValueError
        if either grid has no named areas, or they do not place the same panels.

    Examples
    --------
    >>> from myogestic import Fr, Grid, Layout, Px
    >>> layout = Layout(
    ...     wide=Grid.areas('''
    ...         record  signal
    ...         train   signal
    ...     ''', col_width=[Px(260), Fr(1)]),
    ...     narrow=Grid.areas('''
    ...         signal
    ...         record | train
    ...     '''),
    ...     breakpoint=Px(1100),
    ... )
    >>> sorted(layout.panel_names)
    ['record', 'signal', 'train']
    """

    def __init__(self, *, wide: Grid, narrow: Grid, breakpoint: Px):
        if not isinstance(breakpoint, Px):
            raise TypeError(f"breakpoint={breakpoint!r}: must be Px(...), e.g. Px(1100)")
        for label, grid in (("wide", wide), ("narrow", narrow)):
            if not isinstance(grid, Grid) or not grid.panel_names:
                raise ValueError(f"Layout({label}=...): build it with Grid.areas(...) so panels have names")
        only_wide = wide.panel_names - narrow.panel_names
        only_narrow = narrow.panel_names - wide.panel_names
        if only_wide or only_narrow:
            raise ValueError(
                "Layout(): both arrangements must place the same panels — "
                f"only in wide: {sorted(only_wide)}, only in narrow: {sorted(only_narrow)}"
            )
        self._wide = wide
        self._narrow = narrow
        self._breakpoint = breakpoint
        self._frame = -1
        self._active = wide

    @property
    def panel_names(self) -> frozenset[str]:
        """Every panel the layout places."""
        return self._wide.panel_names

    def _choose(self, logical_width: float) -> Grid:
        return self._wide if logical_width >= self._breakpoint.value else self._narrow

    def _pick(self) -> Grid:
        frame = imgui.get_frame_count()
        if frame != self._frame:
            self._frame = frame
            _, content = _content_rect()
            self._active = self._choose(content.x / current_scale())
        return self._active

    def __getitem__(self, name: str) -> _AreaCell:
        """The cell for ``name`` in this frame's arrangement: ``with layout["record"]:``."""
        return self._pick().area(name)


__all__ = ["Fr", "GUTTER", "Grid", "Layout", "Px", "Track"]
