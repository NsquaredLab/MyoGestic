"""Matplotlib-style grid layout for @app.ui functions.

Track sizes use CSS-Grid-style units that mean the same thing on both axes:

* :class:`Px(n) <Px>` — exactly ``n`` pixels (fixed-size track).
* :class:`Fr(n) <Fr>` — ``n`` shares of the *remaining* space after the
  Px tracks are subtracted (proportional track).

Track entries must be ``Px(...)`` or ``Fr(...)``: bare numbers are
deliberately rejected so a reader can never confuse "300 pixels" with
"300 shares of leftover space". Default (no track list) is all-``Fr(1)``,
i.e. equal distribution.

Example::

    from myogestic.grid import Grid, Px, Fr

    grid = Grid(3, 4)                             # 3 equal rows × 4 equal cols
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
from dataclasses import dataclass
from typing import Union

from imgui_bundle import imgui

GUTTER: float = 6


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
        raise ValueError(
            f"{kind}({value!r}): value must be finite and non-negative"
        )
    return v


@dataclass(frozen=True, slots=True)
class Px:
    """Fixed pixel size. ``Px(300)`` means "exactly 300 px wide/tall"."""

    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validate_value(self.value, "Px"))

    def __repr__(self) -> str:
        return f"Px({self.value:g})"


@dataclass(frozen=True, slots=True)
class Fr:
    """Fractional unit (CSS-grid ``fr``). ``Fr(1)`` means "1 share of the
    space remaining after :class:`Px` tracks are subtracted". Multiple
    ``Fr`` entries split the remainder proportionally to their values, so
    ``[Fr(1), Fr(2)]`` splits leftover space 1:2.
    """

    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validate_value(self.value, "Fr"))

    def __repr__(self) -> str:
        return f"Fr({self.value:g})"


Track = Union[Px, Fr]


def _coerce(spec: object, axis: str, index: int) -> Track:
    """Track entries must be ``Px(...)`` or ``Fr(...)`` — bare numbers
    rejected so ``[300, 1, 1]`` can't be silently misread as pixels.
    """
    if isinstance(spec, (Px, Fr)):
        return spec
    raise TypeError(
        f"{axis}[{index}] = {spec!r}: must be Px(...) or Fr(...). "
        f"Bare numbers are not accepted — wrap in Px (pixels) or Fr (fractional)."
    )


def _resolve_tracks(tracks: list[Track], avail: float) -> list[float]:
    """Resolve a list of Px/Fr tracks to pixel sizes for ``avail`` total space.

    Px tracks keep their declared value. Fr tracks share whatever remains
    (clamped at zero — Px overflow is preserved, never auto-shrunk).
    """
    fixed_total = sum(t.value for t in tracks if isinstance(t, Px))
    fr_total = sum(t.value for t in tracks if isinstance(t, Fr))
    fr_avail = max(0.0, avail - fixed_total)
    fr_scale = (fr_avail / fr_total) if fr_total > 0 else 0.0
    return [
        t.value if isinstance(t, Px) else t.value * fr_scale for t in tracks
    ]


class Grid:
    """Grid layout manager. Index with ``[row, col]`` or ``[row, col_start:col_end]``.

    Both axes accept the same Px/Fr track specs. See module docstring for
    examples.

    Args:
        rows: Number of rows.
        cols: Number of columns.
        row_height: Per-row track specs (length must equal ``rows``).
            Default ``None`` → all rows share equally (``[Fr(1)] * rows``).
        col_width: Per-column track specs (length must equal ``cols``).
            Default ``None`` → all columns share equally (``[Fr(1)] * cols``).

    Raises:
        ValueError: if a list length doesn't match ``rows`` / ``cols``, or
            if any track value is non-finite or negative.
        TypeError: if a track entry isn't Px, Fr, or a number.
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
        self._row_tracks: list[Track] = self._normalize(
            row_height, rows, "row_height"
        )
        self._col_tracks: list[Track] = self._normalize(
            col_width, cols, "col_width"
        )
        self._scaled_heights: list[float] = [0.0] * rows
        self._last_frame: int = -1

    @staticmethod
    def _normalize(
        specs: list[Track] | None, expected_len: int, axis: str
    ) -> list[Track]:
        if specs is None:
            return [Fr(1.0)] * expected_len
        if len(specs) != expected_len:
            raise ValueError(
                f"{axis} has {len(specs)} entries but grid has {expected_len} tracks"
            )
        return [_coerce(s, axis, i) for i, s in enumerate(specs)]

    def _init_frame(self) -> None:
        """Compute scaled row heights to fit the window. Called once per frame."""
        current_frame = imgui.get_frame_count()
        if current_frame == self._last_frame:
            return
        self._last_frame = current_frame
        # Use window height minus padding, not content_region_avail
        # (which changes as child windows are drawn)
        padding = (
            imgui.get_style().window_padding.y * 2
            + max(self.rows - 1, 0) * GUTTER
        )
        avail_h = imgui.get_window_height() - padding
        self._scaled_heights = _resolve_tracks(self._row_tracks, avail_h)

    def _row_y(self, row: int) -> float:
        """Y offset for the top of the given row."""
        return sum(self._scaled_heights[r] for r in range(row)) + row * GUTTER

    def _row_span_h(self, row_start: int, row_end: int) -> float:
        return sum(
            self._scaled_heights[r] for r in range(row_start, row_end)
        ) + max(row_end - row_start - 1, 0) * GUTTER

    def _scaled_col_widths(self, avail_w: float) -> list[float]:
        return _resolve_tracks(self._col_tracks, avail_w)

    def _col_x(self, col: int, avail_w: float) -> float:
        scaled = self._scaled_col_widths(avail_w)
        return sum(scaled[c] for c in range(col)) + col * GUTTER

    def _col_span_w(
        self, col_start: int, col_end: int, avail_w: float
    ) -> float:
        scaled = self._scaled_col_widths(avail_w)
        return sum(scaled[c] for c in range(col_start, col_end)) + max(
            col_end - col_start - 1, 0
        ) * GUTTER

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

    def end_frame(self) -> None:
        """No-op. Frame reset is handled automatically via frame counter."""


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
        g = self._grid
        g._init_frame()

        avail_w = (
            imgui.get_window_width()
            - imgui.get_style().window_padding.x * 2
            - max(g.cols - 1, 0) * GUTTER
        )
        h = g._row_span_h(self._row_start, self._row_end)
        w = g._col_span_w(self._col_start, self._col_end, avail_w)
        x = g._col_x(self._col_start, avail_w) + imgui.get_style().window_padding.x
        y = g._row_y(self._row_start) + imgui.get_style().window_padding.y

        imgui.set_cursor_pos(imgui.ImVec2(x, y))
        # Cell background inherits Col_.child_bg from the active theme
        # rather than hardcoded here — keeps light/dark themes consistent.
        imgui.begin_child(
            f"##grid_{self._row_start}_{self._row_end}_{self._col_start}_{self._col_end}",
            imgui.ImVec2(w, h),
            child_flags=imgui.ChildFlags_.borders,
        )
        return self

    def __exit__(self, *args: object) -> None:
        imgui.end_child()


__all__ = ["Fr", "GUTTER", "Grid", "Px", "Track"]
