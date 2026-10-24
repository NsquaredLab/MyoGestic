"""Automatic UI scale, scaled `Px`, named areas, tabbed cells and `Layout`.

The arithmetic (scale, template parsing, track resolution, which arrangement a
width picks) is tested pure. The parts that only exist inside ImGui — a cell's
rectangle, a panel's child id surviving a reflow, a hidden tab still running its
body — are drawn for real in the headless frame from `conftest.py`.
"""

from __future__ import annotations

import pytest

from myogestic import Fr, Grid, Layout, Px, _scale
from myogestic.grid import _resolve_tracks


@pytest.fixture(autouse=True)
def _fresh_scale(monkeypatch):
    """Every test starts automatic, with no env override and no remembered scale."""
    monkeypatch.delenv("MYOGESTIC_UI_SCALE", raising=False)
    _scale.set_ui_scale(None)
    _scale.reset()
    yield
    _scale.set_ui_scale(None)
    _scale.reset()


# ---------------------------------------------------------------- automatic scale


def test_reference_window_on_a_plain_display_is_scale_one():
    assert _scale.auto_scale(1.0, 1280, 800) == pytest.approx(1.0)


def test_the_os_display_scale_carries_through():
    """Windows at 150 %: the same logical window, everything 1.5x."""
    assert _scale.auto_scale(1.5, 1280, 800) == pytest.approx(1.5)


def test_a_big_window_draws_larger_but_no_more_than_the_ceiling():
    assert _scale.auto_scale(1.0, 1600, 1000) == pytest.approx(1.25)
    assert _scale.auto_scale(1.0, 3840, 2160) == pytest.approx(_scale.FIT_RANGE[1])


def test_a_small_window_never_shrinks_text_past_the_floor():
    """Below the floor the answer is a different arrangement, not smaller text."""
    assert _scale.auto_scale(1.0, 400, 300) == pytest.approx(_scale.FIT_RANGE[0])


def test_the_scale_moves_in_steps_so_a_drag_does_not_restyle_every_frame():
    values = {_scale.auto_scale(1.0, w, 800 * w / 1280) for w in range(1280, 1320)}
    assert len(values) <= 2
    for v in values:
        assert round(v / _scale.STEP) * _scale.STEP == pytest.approx(v)


def test_the_window_fit_uses_the_tighter_axis():
    """A wide but short window is limited by its height."""
    assert _scale.auto_scale(1.0, 2560, 800) == pytest.approx(1.0)


def test_app_ui_scale_turns_automatic_off():
    _scale.set_ui_scale(0.9)
    assert _scale.update(2.0, 3840, 2160) == pytest.approx(0.9)


def test_the_env_var_beats_app_ui_scale(monkeypatch):
    _scale.set_ui_scale(0.9)
    monkeypatch.setenv("MYOGESTIC_UI_SCALE", "1.2")
    assert _scale.update(1.0, 1280, 800) == pytest.approx(1.2)


def test_before_the_first_frame_the_scale_is_one_or_the_override():
    assert _scale.current_scale() == 1.0
    _scale.set_ui_scale(1.1)
    assert _scale.current_scale() == pytest.approx(1.1)


# ------------------------------------------------------------------ scaled tracks


def test_px_follows_the_scale_and_fr_takes_what_is_left():
    widths = _resolve_tracks([Px(200), Fr(1)], 1000, scale=1.5)
    assert widths == pytest.approx([300, 700])


def test_px_at_scale_one_is_unchanged():
    assert _resolve_tracks([Px(200), Fr(1)], 1000) == pytest.approx([200, 800])


# --------------------------------------------------------------- template parsing


def test_a_name_repeated_across_a_block_spans_it():
    grid = Grid.areas("""
        logo    signal  signal
        record  signal  signal
    """)
    assert (grid.rows, grid.cols) == (2, 3)
    assert grid._areas["signal"] == (0, 2, 1, 3)
    assert grid._areas["logo"] == (0, 1, 0, 1)


def test_a_dot_leaves_a_cell_empty():
    grid = Grid.areas("""
        a  .
        b  b
    """)
    assert grid.panel_names == {"a", "b"}


@pytest.mark.parametrize("token", ["sessions|train", "sessions | train", "sessions  |train"])
def test_a_bar_shares_one_cell_as_tabs(token):
    grid = Grid.areas(f"""
        signal
        {token}
    """)
    assert grid._groups["sessions"] == ("sessions", "train")
    assert grid._areas["sessions"] == grid._areas["train"] == (1, 2, 0, 1)


def test_ragged_rows_say_how_to_fix_them():
    with pytest.raises(ValueError, match="same number of cells"):
        Grid.areas("""
            a b
            c
        """)


def test_a_non_rectangular_area_names_the_block():
    with pytest.raises(ValueError, match="not a rectangle"):
        Grid.areas("""
            a a
            a b
        """)


def test_a_panel_placed_twice_is_rejected():
    with pytest.raises(ValueError, match="placed twice"):
        Grid.areas("""
            a      b
            a|b    c
        """)


def test_track_lists_must_match_the_template():
    with pytest.raises(ValueError, match="col_width"):
        Grid.areas("a b", col_width=[Px(100)])


def test_an_unknown_area_lists_the_ones_that_exist():
    grid = Grid.areas("a b")
    with pytest.raises(KeyError, match="this grid has: a, b"):
        grid.area("c")


# ------------------------------------------------------------------------- Layout


def _layout(breakpoint: float = 500) -> Layout:
    return Layout(
        wide=Grid.areas("""
            record  signal
            train   signal
        """, col_width=[Px(200), Fr(1)]),
        narrow=Grid.areas("""
            signal
            record | train
        """),
        breakpoint=Px(breakpoint),
    )


def test_both_arrangements_must_place_the_same_panels():
    with pytest.raises(ValueError, match=r"only in wide: \['train'\]"):
        Layout(
            wide=Grid.areas("signal record train"),
            narrow=Grid.areas("signal record"),
            breakpoint=Px(900),
        )


def test_a_plain_grid_is_not_a_layout_arrangement():
    with pytest.raises(ValueError, match=r"Grid\.areas"):
        Layout(wide=Grid(1, 2), narrow=Grid.areas("a"), breakpoint=Px(900))


def test_the_breakpoint_must_be_px():
    with pytest.raises(TypeError, match="Px"):
        Layout(wide=Grid.areas("a"), narrow=Grid.areas("a"), breakpoint=900)  # type: ignore[arg-type]


def test_the_breakpoint_splits_wide_from_narrow():
    layout = _layout(900)
    assert layout._choose(900) is layout._wide
    assert layout._choose(899) is layout._narrow


# ------------------------------------------------------------------ drawn for real


@pytest.mark.parametrize("title_bar", [False, True])
def test_grid_uses_parent_content_region_when_child_padding_changes(imgui_frame, title_bar):
    from imgui_bundle import imgui

    grid = Grid.areas("header header\nleft right\nstatus status",
                      row_height=[Px(52), Fr(1), Px(26)], bare=("header", "status"))
    scroll = []

    def draw():
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(18, 16))
        imgui.set_next_window_size(imgui.ImVec2(640, 440))
        imgui.begin("parent-padding", flags=0 if title_bar else imgui.WindowFlags_.no_title_bar)
        imgui.pop_style_var()
        origin = imgui.get_cursor_start_pos()
        cursor, avail = imgui.get_cursor_pos(), imgui.get_content_region_avail()
        end = imgui.ImVec2(cursor.x + avail.x, cursor.y + avail.y)
        expected = {name: grid._place(rect) for name, rect in grid._areas.items()}
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(6, 4))
        try:
            for name in ("right", "header", "left", "status"):
                pos, size = grid._place(grid._areas[name])
                assert tuple(pos) == pytest.approx(tuple(expected[name][0]))
                assert tuple(size) == pytest.approx(tuple(expected[name][1]))
                assert pos.x >= origin.x and pos.y >= origin.y
                assert pos.x + size.x <= end.x and pos.y + size.y <= end.y
                with grid.area(name):
                    imgui.text_unformatted(name)
            pos, size = grid._place(grid._areas["status"])
            assert pos.x == origin.x
            assert pos.x + size.x == pytest.approx(end.x)
            assert pos.y + size.y == pytest.approx(end.y)
            scroll.append(imgui.get_scroll_max_y())
        finally:
            imgui.pop_style_var()
            imgui.end()

    imgui_frame(draw)
    imgui_frame(draw)
    assert scroll[-1] == 0


@pytest.mark.parametrize("breakpoint", [Px(500), Px(900)])
def test_bare_area_has_no_border(imgui_frame, monkeypatch, breakpoint):
    from imgui_bundle import imgui

    layout = Layout(
        wide=Grid.areas("header body", bare=iter(["header"])),
        narrow=Grid.areas("header\nbody", bare=["header"]),
        breakpoint=breakpoint,
    )
    begin_child = imgui.begin_child
    flags, padding = {}, {}

    def capture(name, size, child_flags=0, window_flags=0):
        flags[name] = (child_flags, window_flags)
        return begin_child(name, size, child_flags, window_flags)

    monkeypatch.setattr(imgui, "begin_child", capture)

    def draw():
        for name in ("header", "body"):
            with layout[name]:
                padding[name] = tuple(imgui.get_cursor_pos())
                imgui.text_unformatted(name)

    imgui_frame(draw)
    bare_child, bare_window = flags["##area_header"]
    normal_child, normal_window = flags["##area_body"]
    assert not bare_child & imgui.ChildFlags_.borders
    assert bare_window & imgui.WindowFlags_.no_background
    assert normal_child & imgui.ChildFlags_.borders
    assert not normal_window & imgui.WindowFlags_.no_background
    assert padding["header"] == padding["body"]
    assert padding["header"] == tuple(imgui.get_style().window_padding)


def test_bare_area_clips(imgui_frame):
    from imgui_bundle import imgui

    grid = Grid.areas("header body", col_width=[Px(160), Fr(1)], bare=["header"])
    seen = {}

    def draw():
        with grid.area("header"):
            pos, size = imgui.get_window_pos(), imgui.get_window_size()
            draw_list = imgui.get_window_draw_list()
            lo, hi = draw_list.get_clip_rect_min(), draw_list.get_clip_rect_max()
            seen["clip"] = (tuple(lo), tuple(hi), tuple(pos), tuple(size))
            imgui.button("Inside")
            seen["inside"] = imgui.is_item_visible()
            imgui.set_cursor_pos(imgui.ImVec2(size.x + 20, 20))
            imgui.button("Outside this cell, inside the parent")
            seen["outside"] = imgui.is_item_visible()

    for _ in range(2):
        imgui_frame(draw)
    lo, hi, pos, size = seen["clip"]
    assert pos[0] <= lo[0] < hi[0] <= pos[0] + size[0]
    assert pos[1] <= lo[1] < hi[1] <= pos[1] + size[1]
    assert seen["inside"] is True
    assert seen["outside"] is False


def test_bare_rejects_unknown_area():
    with pytest.raises(ValueError, match="footer.*missing"):
        Grid.areas("header body", bare=["header", "missing", "footer"])


def _probe_window():
    from imgui_bundle import imgui

    pos, size = imgui.get_window_pos(), imgui.get_window_size()
    return (pos.x, pos.y, size.x, size.y)


def test_named_cells_do_not_overlap_and_fill_their_track(imgui_frame):
    grid = Grid.areas("""
        record  signal
        train   signal
    """, col_width=[Px(200), Fr(1)])
    seen = {}

    def draw():
        for name in ("record", "train", "signal"):
            with grid.area(name):
                seen[name] = _probe_window()

    for _ in range(2):
        imgui_frame(draw)

    rx, ry, rw, rh = seen["record"]
    tx, ty, tw, th = seen["train"]
    sx, sy, sw, sh = seen["signal"]
    assert rw == pytest.approx(200) and tw == pytest.approx(200)
    assert ty > ry + rh - 1  # train sits below record
    assert sx > rx + rw  # signal sits right of the sidebar
    assert sh == pytest.approx(rh + th + 12)  # spans both rows and the gutter


def test_px_cells_grow_with_the_scale(imgui_frame):
    grid = Grid.areas("side main", col_width=[Px(200), Fr(1)])
    seen = {}

    def draw():
        with grid.area("side"):
            seen["w"] = _probe_window()[2]

    _scale.set_ui_scale(1.5)
    for _ in range(2):
        imgui_frame(draw)
    assert seen["w"] == pytest.approx(300)


def test_a_panel_keeps_its_identity_when_the_layout_reflows(imgui_frame):
    """Scroll position and widget state are keyed by id; a reflow must not change it."""
    from imgui_bundle import imgui

    layout = _layout(500)  # the test window is 680 wide: wide at scale 1.0
    ids, arrangement = [], []

    def draw():
        arrangement.append(layout._pick() is layout._wide)
        with layout["signal"]:
            ids.append(imgui.get_id("probe"))

    imgui_frame(draw)
    _scale.set_ui_scale(2.0)  # 680 px is 340 logical px: below the breakpoint
    imgui_frame(draw)

    assert arrangement == [True, False]
    assert ids[0] == ids[1]


def test_a_hidden_tab_still_runs_but_draws_nothing(imgui_frame):
    from imgui_bundle import imgui

    layout = _layout(5000)  # always narrow: record | train share a cell
    ran = {"record": 0, "train": 0}
    visible = {}

    def draw():
        with layout["signal"]:
            pass
        for name in ("record", "train"):
            with layout[name]:
                ran[name] += 1
                imgui.button(f"btn {name}")
                visible[name] = imgui.is_item_visible()

    for _ in range(3):
        imgui_frame(draw)

    assert ran == {"record": 3, "train": 3}  # return values keep flowing from both
    assert visible == {"record": True, "train": False}  # only the selected tab draws


def test_a_plot_in_a_hidden_tab_does_not_draw(implot_frame):
    from imgui_bundle import implot

    layout = _layout(5000)
    began = {}

    def draw():
        for name in ("signal", "record", "train"):
            with layout[name]:
                began[name] = implot.begin_plot(f"##{name}", (-1, 120))
                if began[name]:
                    implot.end_plot()

    for _ in range(2):
        implot_frame(draw)

    assert began["record"] is True
    assert began["train"] is False


# ------------------------------------------------------------------ live restyling


@pytest.fixture
def _styled(imgui_frame):
    """A context with the theme applied by `apply_live_scale`, as `App` does each frame."""
    from myogestic import _theme

    _theme.reset_live_scale()
    yield _theme
    _theme.reset_live_scale()


def test_restyling_twice_does_not_compound(_styled):
    from imgui_bundle import imgui

    _scale.set_ui_scale(1.3)
    _styled.apply_live_scale(_styled.apply_theme)
    _scale.set_ui_scale(0.85)
    _styled.apply_live_scale(_styled.apply_theme)

    style = imgui.get_style()
    assert style.window_padding.x == pytest.approx(18 * 0.85, abs=1)
    assert style.font_scale_main == pytest.approx(0.85)


def test_borders_survive_a_scale_below_one(_styled):
    """`scale_all_sizes` truncates a 1 px border to 0 at 0.85 — and a bordered child
    without a border also drops its padding, leaving content flush to the cell edge."""
    from imgui_bundle import imgui

    _scale.set_ui_scale(0.85)
    _styled.apply_live_scale(_styled.apply_theme)
    assert imgui.get_style().child_border_size == pytest.approx(1.0)


def test_a_later_tab_draws_under_the_tab_bar_when_selected(imgui_frame, monkeypatch):
    """With the second tab selected, the first member enters the shared cell on the
    hidden path and the second re-enters it — its body must land under the tab bar,
    exactly where the first tab's body sits when that one is selected."""
    from imgui_bundle import imgui

    def bodies():
        layout = _layout(5000)
        seen = {}

        def draw():
            with layout["signal"]:
                pass
            for name in ("record", "train"):
                with layout[name]:
                    imgui.button(f"btn {name}")
                    seen[name] = (imgui.get_window_pos().y, imgui.is_item_visible())

        for _ in range(3):
            imgui_frame(draw)
        return seen

    first = bodies()

    real = imgui.begin_tab_item

    def select_train(label, p_open=None, flags=0):
        if label.startswith("Train"):
            flags |= imgui.TabItemFlags_.set_selected
        return real(label, p_open, flags)

    monkeypatch.setattr(imgui, "begin_tab_item", select_train)
    second = bodies()

    assert first["record"][1] and not first["train"][1]
    assert second["train"][1] and not second["record"][1]
    assert second["train"][0] == pytest.approx(first["record"][0])
