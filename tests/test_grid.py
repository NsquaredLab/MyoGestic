"""Tests for myogestic.grid layout math.

These don't actually invoke ImGui — we only test the pure-math methods that
don't depend on the rendering context."""

import pytest

from myogestic.grid import GUTTER, Fr, Grid, Px, _resolve_tracks


def test_grid_default_construction():
    g = Grid(rows=3, cols=4)
    assert g.rows == 3
    assert g.cols == 4
    # Default = all Fr(1) on both axes (equal share).
    assert g._row_tracks == [Fr(1.0)] * 3
    assert g._col_tracks == [Fr(1.0)] * 4


def test_grid_explicit_col_widths_px():
    g = Grid(rows=2, cols=3, col_width=[Px(100), Px(200), Px(50)])
    assert g._col_tracks == [Px(100.0), Px(200.0), Px(50.0)]


def test_bare_numbers_are_rejected():
    """Bare ints/floats must be wrapped — no silent 'pixels-or-fractions'
    ambiguity at call sites like [300, 1, 1]."""
    with pytest.raises(TypeError, match="Bare numbers are not accepted"):
        Grid(rows=2, cols=3, col_width=[1, 2.5, 1])


def test_px_rejects_bool():
    """bool is an int subclass; Px(True) would otherwise pass silently."""
    with pytest.raises(TypeError, match="value must be an int or float"):
        Px(True)


def test_px_rejects_string():
    """Clean error for Px('300') instead of a math.isfinite traceback."""
    with pytest.raises(TypeError, match="value must be an int or float"):
        Px("300")


def test_fr_rejects_none():
    with pytest.raises(TypeError, match="value must be an int or float"):
        Fr(None)


def test_grid_rejects_zero_rows():
    with pytest.raises(ValueError, match="rows must be a positive int"):
        Grid(rows=0, cols=3)


def test_grid_rejects_negative_cols():
    with pytest.raises(ValueError, match="cols must be a positive int"):
        Grid(rows=3, cols=-1)


def test_repr_is_compact():
    """Reads like the call site, not the dataclass field syntax."""
    assert repr(Px(300)) == "Px(300)"
    assert repr(Fr(1.0)) == "Fr(1)"
    assert repr(Fr(2.5)) == "Fr(2.5)"


def test_track_resolver_px_only():
    """Px tracks keep their declared value regardless of avail."""
    out = _resolve_tracks([Px(100), Px(200)], avail=500)
    assert out == [100.0, 200.0]


def test_track_resolver_fr_only():
    """Fr tracks split the full available space proportionally."""
    out = _resolve_tracks([Fr(1), Fr(3)], avail=400)
    assert out == [100.0, 300.0]


def test_track_resolver_mixed():
    """Px tracks carve out first; Fr tracks share the remainder."""
    out = _resolve_tracks([Px(100), Fr(1), Fr(3)], avail=500)
    # Px = 100, Fr remainder = 400 split 1:3 = 100, 300
    assert out == [100.0, 100.0, 300.0]


def test_track_resolver_px_overflow_not_shrunk():
    """If Px tracks exceed avail, Fr tracks get 0 — Px is never shrunk."""
    out = _resolve_tracks([Px(600), Fr(1)], avail=500)
    assert out == [600.0, 0.0]


def test_grid_rejects_wrong_length():
    with pytest.raises(ValueError, match="row_height has 2 entries but grid has 3"):
        Grid(rows=3, cols=4, row_height=[Fr(1), Fr(1)])


def test_grid_rejects_negative_value():
    with pytest.raises(ValueError, match="non-negative"):
        Grid(rows=2, cols=2, col_width=[Px(-100), Px(50)])


def test_grid_rejects_bad_type():
    with pytest.raises(TypeError, match="must be Px"):
        Grid(rows=2, cols=2, col_width=["100px", Px(50)])


def test_col_x_for_equal_share():
    """Column N starts at N * (cell_width + GUTTER)."""
    g = Grid(rows=1, cols=3)
    avail_w = 300.0  # avail already excludes (cols-1)*GUTTER per _Cell.__enter__

    assert g._col_x(0, avail_w) == 0
    cell_w = avail_w / 3  # 100
    assert g._col_x(1, avail_w) == cell_w + GUTTER
    assert g._col_x(2, avail_w) == 2 * (cell_w + GUTTER)


def test_col_span_w_for_equal_share():
    """A span of N cells takes N*cell_w + (N-1)*GUTTER."""
    g = Grid(rows=1, cols=3)
    avail_w = 300.0
    cell_w = avail_w / 3

    assert g._col_span_w(0, 1, avail_w) == cell_w
    assert g._col_span_w(0, 2, avail_w) == 2 * cell_w + GUTTER
    assert g._col_span_w(0, 3, avail_w) == 3 * cell_w + 2 * GUTTER


def test_col_x_plus_span_covers_whole_avail_w():
    """Sum of cell offsets + spans should equal the original (pre-gutter) width.

    avail_w is already net-of-gutters when passed in by _Cell.__enter__,
    so a full-row span starting at col 0 should equal cols * cell_w + (cols-1)*GUTTER.
    """
    g = Grid(rows=1, cols=4)
    avail_w = 400.0  # caller has subtracted (cols-1)*GUTTER

    full_span = g._col_span_w(0, 4, avail_w)
    expected = avail_w + 3 * GUTTER  # net + gutters back in
    assert abs(full_span - expected) < 1e-6


def test_row_y_increments_by_height_plus_gutter():
    g = Grid(rows=3, cols=1)
    g._scaled_heights = [100.0, 100.0, 100.0]

    assert g._row_y(0) == 0
    assert g._row_y(1) == 100.0 + GUTTER
    assert g._row_y(2) == 200.0 + 2 * GUTTER


def test_row_span_h_includes_inner_gutters_only():
    g = Grid(rows=3, cols=1)
    g._scaled_heights = [100.0, 100.0, 100.0]

    assert g._row_span_h(0, 1) == 100.0
    assert g._row_span_h(0, 2) == 200.0 + GUTTER
    assert g._row_span_h(0, 3) == 300.0 + 2 * GUTTER


def test_grid_indexing_returns_cell_with_bounds():
    g = Grid(rows=3, cols=4)

    cell = g[0, 0]
    assert cell._row_start == 0 and cell._row_end == 1
    assert cell._col_start == 0 and cell._col_end == 1

    cell_span = g[0, 1:3]
    assert cell_span._col_start == 1 and cell_span._col_end == 3

    cell_full = g[0:3, :]
    assert cell_full._row_start == 0 and cell_full._row_end == 3
    assert cell_full._col_start == 0 and cell_full._col_end == 4
