"""Tool headers and their original controls stay readable in the real layouts."""

import platform
import runpy
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui

from myogestic import Grid, Px, _scale, _theme
from myogestic.remote import InterfaceSpec
from myogestic.widgets import AppHeader

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def light_ui(imgui_frame, monkeypatch):
    """Use the app's fonts, light theme and scale without a display or GPU."""
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    io = imgui.get_io()
    io.font_default = io.fonts.add_font_from_file_ttf(str(font_path), 14)
    for attr, filename, size in (("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
                                 ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28)):
        font = io.fonts.add_font_from_file_ttf(str(ROOT / "myogestic/assets/fonts" / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)
    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", lambda name: SimpleNamespace(
        texture_id=1, size=imgui.ImVec2(519, 128),
    ))
    monkeypatch.setattr(imgui, "image", lambda texture, size: imgui.dummy(size))
    return imgui_frame


@pytest.mark.parametrize("name,title", [
    ("control_map_studio", "Control map studio"),
    ("vhi_control_hand", "VHI control hand"),
])
@pytest.mark.parametrize("width", [2560, 1600, 960])
@pytest.mark.parametrize("connected", [False, True])
@pytest.mark.parametrize("launchable", [False, True])
def test_tool_header_and_body_fit(light_ui, monkeypatch, name, title, width, connected, launchable):
    """Keep titles, tabs and actions readable at scale two in both arrangements."""
    monkeypatch.setattr(InterfaceSpec, "launchable", lambda self: (
        [("VHI Hand", ["unused-vhi"])] if launchable else []
    ))
    namespace = runpy.run_path(str(ROOT / "examples/synthetic" / f"{name}.py"))
    app = namespace["app"]
    scope = app._ui_fn.__globals__
    header = namespace["header"]
    assert isinstance(header, AppHeader)
    assert header.title == title and not header.show_state
    assert header.steps is None and header.participant is None
    assert "logo" not in namespace
    bus = SimpleNamespace(push=lambda values: None) if connected else None
    if name == "control_map_studio":
        grids = (namespace["layout"]._wide, namespace["layout"]._narrow)
        monkeypatch.setitem(scope, "bus", bus)
        monkeypatch.setitem(scope, "levels", {"close": 0.5} if connected else {})
        monkeypatch.setitem(scope, "states", {})
        monkeypatch.setitem(scope, "_rebuild_if_the_manifest_changed", lambda: None)
    else:
        grids = (namespace["grid"],)
        monkeypatch.setitem(scope, "link", SimpleNamespace(bus=bus))
    for grid in grids:
        assert grid._row_tracks[0] == Px(52)
        assert grid._areas["header"] == (0, 1, 0, grid.cols)
        assert grid._bare == {"header"}

    cells, items, tabs = {}, [], []
    current = [None]
    scroll_fraction = [0.0]
    area = Grid.area

    @contextmanager
    def measured_area(self, cell_name):
        with area(self, cell_name):
            current[0] = cell_name
            imgui.set_scroll_y(scroll_fraction[0] * imgui.get_scroll_max_y())
            yield
            cells[cell_name] = (
                imgui.get_scroll_max_x(), imgui.get_scroll_max_y(),
                imgui.get_cursor_pos_y() - imgui.get_style().item_spacing.y,
                imgui.get_window_size().y,
            )
            current[0] = None

    monkeypatch.setattr(Grid, "area", measured_area)

    def track(method):
        original = getattr(imgui, method)

        def draw(*args, **kwargs):
            result = original(*args, **kwargs)
            draw_list = imgui.get_window_draw_list()
            label = args[1] if method == "text_colored" else args[0]
            items.append((current[0], method, str(label),
                          tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max()),
                          tuple(draw_list.get_clip_rect_min()), tuple(draw_list.get_clip_rect_max())))
            return result

        monkeypatch.setattr(imgui, method, draw)

    for method in ("text_colored", "text_unformatted", "text_wrapped", "button", "small_button",
                   "slider_float", "combo", "dummy"):
        track(method)
    begin_tabs = imgui.begin_tab_bar

    def tab_bar(label, *args, **kwargs):
        tabs.append(label)
        return begin_tabs(label, *args, **kwargs)

    monkeypatch.setattr(imgui, "begin_tab_bar", tab_bar)
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("tool-shell", flags=imgui.WindowFlags_.no_title_bar | imgui.WindowFlags_.no_saved_settings)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        cells.clear()
        items.clear()
        tabs.clear()
        light_ui(draw)
    assert list(cells)[0] == "header"
    assert cells["header"][3] == 104
    assert cells["header"][:2] == (0, 0)
    assert all(horizontal == 0 for horizontal, _, _, _ in cells.values()), cells
    assert all(lo[0] >= clip_lo[0] - 1 and hi[0] <= clip_hi[0] + 1
               for _, _, _, lo, hi, clip_lo, clip_hi in items), items
    header_items = [item for item in items if item[0] == "header"]
    assert any(title in label for _, _, label, *_ in header_items)
    assert all(lo[1] >= clip_lo[1] - 1 and hi[1] <= clip_hi[1] + 1
               for _, _, _, lo, hi, clip_lo, clip_hi in header_items), header_items
    # The default shell keeps its primary actions in view without scrolling.
    if width == 2560:
        assert all(scroll_y == 0 and end_y <= height for _, scroll_y, end_y, height in cells.values()), cells
    if name == "control_map_studio":
        assert tabs == ["maps"]
        assert {"processes", "drive", "keyboard", "editor"} <= cells.keys()
    else:
        assert not tabs
        assert {"processes", "hand"} <= cells.keys()

    # Stacked cards can scroll, but every label and action must be reachable.
    required = {item[:3] for item in items}
    visible = set()
    for fraction in (0.0, 0.5, 1.0):
        scroll_fraction[0] = fraction
        for _ in range(3):
            items.clear()
            light_ui(draw)
        visible.update(item[:3] for item in items
                       if item[3][1] >= item[5][1] - 1 and item[4][1] <= item[6][1] + 1)
    assert required <= visible, required - visible
