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
from myogestic.widgets.signals._controls import render_channel_controls
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


@pytest.mark.parametrize("n_channels", [4, 64, 256])
@pytest.mark.parametrize("with_grids", [False, True])
def test_render_channel_controls_smoke(imgui_ctx, n_channels, with_grids):
    """Never raises, and always returns a valid `(set, names_or_None, int)`."""
    channel_grids = [ChannelGrid("g0", auto_shape(list(range(n_channels))))] if with_grids else None
    info = StreamInfo(n_channels=n_channels, fs=1000.0, channel_grids=channel_grids)
    stream = _FakeStream(info)
    v = ViewerState(channels=set(range(n_channels)), channels_initialized=True)

    imgui.new_frame()
    imgui.begin(f"test##{n_channels}_{with_grids}")
    result = render_channel_controls(f"emg_{n_channels}_{with_grids}", stream, v, n_channels)
    imgui.end()
    imgui.render()

    assert isinstance(result, tuple)
    assert len(result) == 3
    enabled, names, hovered_ch = result
    assert isinstance(enabled, set)
    assert all(isinstance(c, int) for c in enabled)
    assert names is None or isinstance(names, list)
    assert isinstance(hovered_ch, int)
