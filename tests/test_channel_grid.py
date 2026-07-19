"""Tests for the ChannelGrid topology and StreamInfo.channel_grids field."""

import random

import pytest
from imgui_bundle import imgui

from myogestic.stream import ChannelGrid, StreamInfo
from myogestic.widgets.signals._channel_grid import (
    auto_shape,
    normalize_layout,
    rect_to_channels,
    reduce_selection,
    resolve_initial,
)
from myogestic.widgets.signals._controls import (
    _finalize_drag,
    _grid_ui,
    _GridUIState,
    _hit_test,
    _hit_test_xy,
    render_channel_controls,
    render_grid,
)
from myogestic.widgets.signals._state import ViewerState


def test_channel_grid_columns_and_streaminfo_field():
    g = ChannelGrid("IN1", [[0, 1], [2, None]])
    assert g.columns == [0, 1, 2]  # row-major, skips None
    info = StreamInfo(n_channels=3, fs=2048.0, channel_grids=[g])
    assert info.channel_grids[0].label == "IN1"
    assert StreamInfo(n_channels=3, fs=2048.0).channel_grids is None  # default
    # a malformed layout must NOT raise at construction (viewer validates)
    StreamInfo(n_channels=2, fs=2048.0, channel_grids=[ChannelGrid("x", [[9, 9]])])


def test_auto_shape_covers_all_columns_near_square():
    cells = auto_shape(list(range(10)))
    flat = [c for row in cells for c in row if c is not None]
    assert flat == list(range(10))  # every column, in order
    assert all(len(row) == len(cells[0]) for row in cells)  # rectangular
    assert len(cells[0]) <= 4 and len(cells) <= 4  # near-square (ceil(sqrt(10))=4)


def test_normalize_none_makes_one_auto_grid():
    layout = normalize_layout(None, 8)
    assert len(layout) == 1 and sorted(layout[0].columns) == list(range(8))


def test_normalize_drops_out_of_range_and_dupes_then_falls_back_if_empty():
    good = normalize_layout([ChannelGrid("IN1", [[0, 1, 99], [1, 2]])], 4)
    assert sorted(good[0].columns) == [0, 1, 2]  # 99 dropped, dup 1 dropped
    empty = normalize_layout([ChannelGrid("bad", [[50]])], 4)
    assert sorted(empty[0].columns) == [0, 1, 2, 3]  # invalid -> auto "all"


def test_normalize_nulls_invalid_cells_in_place_for_rectangular_grid():
    # Rectangular (both rows length 3) -> nulled in place, NOT re-auto-shaped.
    layout = normalize_layout([ChannelGrid("R", [[0, 1, 99], [1, 2, None]])], 4)
    assert layout[0].cells == [[0, 1, None], [None, 2, None]]  # 99 out-of-range, dup 1 nulled
    assert layout[0].columns == [0, 1, 2]


GRID = ChannelGrid("g", [[0, 1, 2], [3, None, 5]])  # note the hole at (1,1)


def test_rect_skips_holes_and_is_direction_invariant():
    a = rect_to_channels(GRID, 0, 0, 1, 2)
    b = rect_to_channels(GRID, 1, 2, 0, 0)  # dragged the other way
    assert a == b == {0, 1, 2, 3, 5}  # (1,1) hole excluded


def test_rect_clamps_out_of_range_corners_without_wraparound():
    # All four corners out of range (including small negatives) must clamp
    # to the grid bounds, NOT wrap around via Python's negative-index rule.
    full = rect_to_channels(GRID, 0, 0, 1, 2)
    assert rect_to_channels(GRID, -1, -1, 99, 99) == full == {0, 1, 2, 3, 5}
    # Asymmetric: negative row clamps to 0, single top-left cell only.
    assert rect_to_channels(GRID, -5, 0, 0, 0) == {0}


def test_invert_twice_is_identity_and_in_bounds():
    for _ in range(50):
        n = random.randint(1, 64)
        sel = set(random.sample(range(n), k=random.randint(0, n)))
        once = reduce_selection(sel, "invert", range(n))
        twice = reduce_selection(once, "invert", range(n))
        assert twice == sel
        assert once <= set(range(n))


def test_resolve_initial_policy():
    assert resolve_initial(None, 16, []) == set(range(16))  # small -> all
    assert resolve_initial(None, 256, []) == set(range(16))  # large -> first 16
    assert resolve_initial(range(4), 256, []) == {0, 1, 2, 3}
    assert resolve_initial([1, 2, 999], 8, []) == {1, 2}  # clamp out-of-range


# --- _hit_test geometry: row/col axes must use the matching spacing -------
#
# Cells are laid out with `same_line()` horizontally (column stride
# `cell + item_spacing.x`) and wrap onto a new line vertically (row stride
# `cell + item_spacing.y`). The app theme (`myogestic/_theme.py`) sets
# `item_spacing = (8, 6)` — x != y — so a hit-test that reuses one spacing
# value for both axes drifts on the row axis. These values (cell=14,
# spacing_x=8, spacing_y=6) reproduce that theme; rows >= 8 are where the
# ~2px/row drift from a single-spacing implementation first flips the
# computed row (verified by hand against the buggy `step = cell +
# spacing_x` formula for both axes).
_HIT_TEST_CELL = 14.0
_HIT_TEST_SPACING_X = 8.0
_HIT_TEST_SPACING_Y = 6.0


def _cell_center(row: int, col: int) -> tuple[float, float]:
    """Mouse (x, y) at the exact center of `(row, col)` under the real layout."""
    step_x = _HIT_TEST_CELL + _HIT_TEST_SPACING_X
    step_y = _HIT_TEST_CELL + _HIT_TEST_SPACING_Y
    return col * step_x + step_x / 2.0, row * step_y + step_y / 2.0


@pytest.mark.parametrize(
    "row,col",
    [
        (0, 0),
        (1, 1),
        (5, 0),  # vertical center of row 5 -> must be row 5, not 5 +/- drift
        (5, 5),
        (8, 1),
        (10, 10),
        (15, 15),  # last row of a 16x16 (256-ch) grid: drift is largest here
    ],
)
def test_hit_test_xy_matches_actual_row_col_layout(row, col):
    mouse_x, mouse_y = _cell_center(row, col)
    got_row, got_col = _hit_test_xy(
        mouse_x,
        mouse_y,
        0.0,
        0.0,
        _HIT_TEST_CELL,
        _HIT_TEST_SPACING_X,
        _HIT_TEST_SPACING_Y,
    )
    assert (got_row, got_col) == (row, col)


def test_hit_test_wraps_pure_core_with_imgui_vec_types():
    origin = imgui.ImVec2(100.0, 50.0)
    row, col = 8, 3
    dx, dy = _cell_center(row, col)
    mouse = imgui.ImVec2(origin.x + dx, origin.y + dy)
    assert _hit_test(origin, _HIT_TEST_CELL, _HIT_TEST_SPACING_X, _HIT_TEST_SPACING_Y, mouse) == (
        row,
        col,
    )


def test_hit_test_row_axis_uses_spacing_y_not_spacing_x():
    # Directly pins the bug: swapping spacing_x/spacing_y on the row axis
    # (i.e. reusing one spacing value for both axes, as the old code did)
    # must change the result for a non-square spacing pair.
    mouse_x, mouse_y = _cell_center(10, 0)
    correct = _hit_test_xy(
        mouse_x, mouse_y, 0.0, 0.0, _HIT_TEST_CELL, _HIT_TEST_SPACING_X, _HIT_TEST_SPACING_Y
    )
    buggy_single_spacing = _hit_test_xy(
        mouse_x, mouse_y, 0.0, 0.0, _HIT_TEST_CELL, _HIT_TEST_SPACING_X, _HIT_TEST_SPACING_X
    )
    assert correct == (10, 0)
    assert buggy_single_spacing != correct


# --- render_channel_controls smoke test (imgui widget shell) ---------------
#
# `render_channel_controls` only builds ImGui's CPU-side draw list (no
# rasterization) — it never needs an actual GPU/window backend. A real
# backend would call `io.fonts.get_tex_data_as_...()` (or the newer
# texture-streaming callback) during `new_frame()` to build the font atlas;
# without one, ImGui asserts unless the backend advertises that it owns
# texture updates itself. Setting `BackendFlags_.renderer_has_textures`
# sidesteps that — we never draw glyphs that need the atlas here — letting
# this test drive the *real* imgui-bundle widget code (invisible_button,
# draw-list calls, tooltip/hover/focus queries) headlessly.


class _FakeStream:
    def __init__(self, info: StreamInfo) -> None:
        self.info = info


@pytest.fixture
def imgui_ctx():
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = imgui.ImVec2(800, 600)
    io.delta_time = 1.0 / 60.0
    io.backend_flags = io.backend_flags | imgui.BackendFlags_.renderer_has_textures
    yield
    imgui.destroy_context()


def _assert_valid_render_channel_controls_result(result: object, n_channels: int) -> None:
    assert isinstance(result, tuple)
    assert len(result) == 3
    enabled, names, hovered_ch = result
    assert isinstance(enabled, set)
    assert all(isinstance(c, int) for c in enabled)
    assert names is None or isinstance(names, list)
    assert isinstance(hovered_ch, int)


@pytest.mark.parametrize("n_channels", [4, 64, 256])
@pytest.mark.parametrize("with_grids", [False, True])
def test_render_channel_controls_smoke(imgui_ctx, n_channels, with_grids):
    """Never raises, and always returns a valid `(set, names_or_None, int)`.

    Exercises both the closed state — `render_channel_controls` draws only
    the compact bar inline, `hovered_ch` is always -1 since nothing can be
    hovered — and, with `_GridUIState.show_grid` set True, the open state,
    where the grid renders in its own floating window.
    """
    channel_grids = [ChannelGrid("g0", auto_shape(list(range(n_channels))))] if with_grids else None
    info = StreamInfo(n_channels=n_channels, fs=1000.0, channel_grids=channel_grids)
    stream = _FakeStream(info)
    v = ViewerState(channels=set(range(n_channels)), channels_initialized=True)
    stream_name = f"emg_{n_channels}_{with_grids}"

    # Closed (default): compact bar only, no popup window.
    imgui.new_frame()
    imgui.begin(f"test##{stream_name}")
    result = render_channel_controls(stream_name, stream, v, n_channels)
    imgui.end()
    imgui.render()
    _assert_valid_render_channel_controls_result(result, n_channels)
    assert result[2] == -1  # hovered_ch: nothing hoverable while closed

    # Open: flip `show_grid` (as the `[Edit…]` button would) and render
    # again — the floating grid window now draws too.
    _grid_ui[stream_name].show_grid = True
    imgui.new_frame()
    imgui.begin(f"test##{stream_name}")
    result = render_channel_controls(stream_name, stream, v, n_channels)
    imgui.end()
    imgui.render()
    _assert_valid_render_channel_controls_result(result, n_channels)


# --- popup-window regression: nested-window origin correctness -------------
#
# `render_grid` now always renders inside the floating grid window
# (`render_grid_window`), itself invoked from inside the caller's own
# window — one level deeper than before this revision. `render_grid`'s
# rectangle-drag hit-test relies entirely on `imgui.get_cursor_screen_pos()`
# and `imgui.get_mouse_pos()`, both already in *absolute* screen
# coordinates, so extra window nesting shouldn't change anything — but
# that's an assumption worth pinning down with a real headless render plus
# a simulated click/drag, not just re-asserting the pure-geometry formula
# above (which never touches a window at all).


def _draw_nested_grid_frame(
    grid: ChannelGrid, enabled: set[int], ui: _GridUIState, cell: float, stream_id: str
) -> tuple[int, imgui.ImVec2, imgui.ImVec2]:
    """Render `grid` inside a window nested inside another window.

    Mirrors the real layout: `render_channel_controls` draws the compact
    bar in the caller's window, then `render_grid_window` opens a *second*,
    separate `imgui.begin` window for the grid itself. Both windows are
    pinned to a fixed position/size every frame so the geometry a test
    derives from one frame stays valid in the next.
    """
    imgui.new_frame()
    imgui.set_next_window_pos(imgui.ImVec2(50, 50), imgui.Cond_.always)
    imgui.set_next_window_size(imgui.ImVec2(150, 150), imgui.Cond_.always)
    imgui.begin("outer##nested_origin")
    imgui.set_next_window_pos(imgui.ImVec2(220, 180), imgui.Cond_.always)
    imgui.set_next_window_size(imgui.ImVec2(300, 300), imgui.Cond_.always)
    imgui.begin(f"popup##{stream_id}")
    hovered = render_grid(stream_id, 0, grid, enabled, None, ui, cell, -1)
    rect_min = imgui.get_item_rect_min()
    rect_max = imgui.get_item_rect_max()
    imgui.end()
    imgui.end()
    imgui.render()
    return hovered, rect_min, rect_max


def test_grid_click_hits_correct_cell_when_nested_inside_another_window(imgui_ctx):
    """A click on cell (0, 0) toggles channel 0 — even though `render_grid`
    now always renders inside a *second*, nested `imgui.begin` window (the
    popup), not directly in the caller's own window as before this revision.
    """
    grid = ChannelGrid("g", auto_shape(list(range(9))))  # 3x3, channels 0..8
    enabled: set[int] = set()
    ui = _GridUIState()
    cell = 30.0
    stream_id = "nested_click"

    # Dry-run frame (mouse far away) just to read back cell 8's real
    # on-screen rect from the actual, unmodified `render_grid` code path —
    # not hand-derived — from which cell 0's center is backed out.
    io = imgui.get_io()
    io.mouse_pos = imgui.ImVec2(-1000.0, -1000.0)
    _, rect_min, _ = _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)

    style = imgui.get_style()
    step_x = cell + style.item_spacing.x
    step_y = cell + style.item_spacing.y
    # Cell 8 is the bottom-right (row 2, col 2) of the 3x3 grid.
    origin = imgui.ImVec2(rect_min.x - 2 * step_x, rect_min.y - 2 * step_y)
    mouse = imgui.ImVec2(origin.x + step_x / 2, origin.y + step_y / 2)

    io.mouse_pos = mouse
    hovered, _, _ = _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)
    assert hovered == 0  # imgui's own hover test, independent of `_hit_test`

    io.add_mouse_button_event(0, True)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)
    io.add_mouse_button_event(0, False)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)
    _finalize_drag(ui, enabled)

    assert enabled == {0}


def test_grid_drag_rectangle_works_when_nested_inside_another_window(imgui_ctx):
    """A drag from cell (0, 0) to cell (1, 1) selects the 2x2 block
    `{0, 1, 3, 4}` — the rectangle-select path — inside the nested popup
    window, driven frame by frame through a real mouse-down / drag / release
    sequence (not a direct call into the pure `rect_to_channels` core).
    """
    grid = ChannelGrid("g", auto_shape(list(range(9))))
    enabled: set[int] = set()
    ui = _GridUIState()
    cell = 30.0
    stream_id = "nested_drag"

    io = imgui.get_io()
    io.mouse_pos = imgui.ImVec2(-1000.0, -1000.0)
    _, rect_min, _ = _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)

    style = imgui.get_style()
    step_x = cell + style.item_spacing.x
    step_y = cell + style.item_spacing.y
    origin = imgui.ImVec2(rect_min.x - 2 * step_x, rect_min.y - 2 * step_y)

    io.mouse_pos = imgui.ImVec2(origin.x + step_x / 2, origin.y + step_y / 2)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)  # settle hover
    io.add_mouse_button_event(0, True)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)  # arm the drag

    io.mouse_pos = imgui.ImVec2(origin.x + step_x * 1.5, origin.y + step_y * 1.5)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)  # past the threshold
    assert ui.drag.dragged
    assert enabled == {0, 1, 3, 4}

    io.add_mouse_button_event(0, False)
    _draw_nested_grid_frame(grid, enabled, ui, cell, stream_id)
    _finalize_drag(ui, enabled)
    assert enabled == {0, 1, 3, 4}
