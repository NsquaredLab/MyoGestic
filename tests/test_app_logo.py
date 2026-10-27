"""Brand assets retain their aspect and fit the workflow header at every scale."""

import runpy
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui

from myogestic import _scale, _theme
from myogestic.widgets import AppLogo
from myogestic.widgets.common import hairline, ui_px

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def logo_image(monkeypatch):
    """Use the shipped PNG geometry without needing an OpenGL texture backend."""
    asset = _ROOT / "myogestic/assets/myogestic_logo_line.png"
    width, height = struct.unpack(">II", asset.read_bytes()[16:24])
    assert (width, height) == (519, 128)
    loaded, drawn = [], []

    def load(name):
        loaded.append(name)
        natural = struct.unpack(">II", (_ROOT / "myogestic/assets" / name).read_bytes()[16:24])
        return SimpleNamespace(texture_id=1, size=imgui.ImVec2(*natural))

    def draw(_texture, size):
        imgui.dummy(size)
        drawn.append((tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max())))

    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)
    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", load)
    monkeypatch.setattr(imgui, "image", draw)
    return loaded, drawn


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_line_logo_has_fixed_height_and_natural_aspect(imgui_frame, monkeypatch, logo_image, scale):
    monkeypatch.setattr(_scale, "_current", scale)
    loaded, drawn = logo_image
    origins = []

    def draw():
        origins.append(tuple(imgui.get_cursor_screen_pos()))
        AppLogo(variant="line", height=ui_px(26)).ui()

    imgui_frame(draw)
    assert loaded == ["myogestic_logo_line.png"]
    lo, hi = drawn[0]
    assert lo == pytest.approx(origins[0])
    assert hi[0] - lo[0] == pytest.approx(ui_px(26) * 519 / 128)
    assert hi[1] - lo[1] == pytest.approx(ui_px(26))


def test_default_logo_keeps_fit_to_cell_behaviour(imgui_frame, logo_image):
    loaded, drawn = logo_image
    imgui_frame(lambda: AppLogo(max_size=240).ui())
    assert loaded == ["myogestic_logo.png"]
    lo, hi = drawn[0]
    assert hi[0] - lo[0] == pytest.approx(240)
    assert hi[1] - lo[1] == pytest.approx(240 * 540 / 800)


@pytest.mark.parametrize("variant", ["stacked", "line"])
@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_missing_logo_uses_display_wordmark(imgui_frame, monkeypatch, variant, scale):
    from myogestic.widgets.panels import app_logo

    monkeypatch.setattr(_scale, "_current", scale)
    imgui.get_style().font_scale_main = scale
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: False)
    monkeypatch.setattr(
        hello_imgui,
        "image_and_size_from_asset",
        lambda name: pytest.fail("A missing logo must not be loaded"),
    )
    fonts, labels, heights = [], [], []
    push_font, text = imgui.push_font, imgui.text_unformatted

    def capture_font(font, size):
        fonts.append(font)
        push_font(font, size)

    def capture_text(label):
        labels.append(label)
        text(label)
        heights.append(imgui.get_item_rect_size().y)

    monkeypatch.setattr(imgui, "push_font", capture_font)
    monkeypatch.setattr(imgui, "text_unformatted", capture_text)
    imgui_frame(lambda: AppLogo(variant=variant, height=ui_px(26)).ui())
    assert labels == ["MyoGestic"]
    assert fonts == [app_logo.display_font()]
    assert heights == pytest.approx([ui_px(26)])


@pytest.fixture
def workflow(monkeypatch):
    import myogestic.core
    import myogestic.remote

    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    return runpy.run_path(str(_ROOT / "examples/start_here/myocontrol.py"))


@pytest.mark.parametrize(
    "scale,width,show_title",
    [
        (1.0, 1280, True),
        (1.0, 900, False),
        (2.0, 2560, True),
        (2.0, 1800, False),
    ],
)
@pytest.mark.parametrize("dark", [False, True])
def test_header_is_left_aligned_and_stays_in_one_row(
    imgui_frame,
    monkeypatch,
    logo_image,
    workflow,
    scale,
    width,
    show_title,
    dark,
):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    imgui.get_io().display_size = imgui.ImVec2(width, ui_px(200))
    controls, titles, dividers, right_edges = [], [], [], []
    button, text, add_line = imgui.button, imgui.text_colored, imgui.ImDrawList.add_line

    def rect():
        return tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max())

    def track_button(label, *args, **kwargs):
        clicked = button(label, *args, **kwargs)
        if "###step" in label or label.endswith("###chip"):
            controls.append(rect())
        return clicked

    def track_text(color, label):
        text(color, label)
        if label == "Myocontrol":
            titles.append(rect())

    def track_line(draw_list, start, end, color, thickness=1.0):
        if start.x == end.x:
            dividers.append((tuple(start), tuple(end), color, thickness))
        return add_line(draw_list, start, end, color, thickness=thickness)

    pill = workflow["header"].ui.__func__.__globals__["status_pill"]

    def track_pill(label, color):
        pill(label, color)
        controls.append(rect())

    monkeypatch.setattr(imgui, "button", track_button)
    monkeypatch.setattr(imgui, "text_colored", track_text)
    monkeypatch.setattr(imgui.ImDrawList, "add_line", track_line)
    monkeypatch.setitem(workflow["header"].ui.__func__.__globals__, "status_pill", track_pill)
    ctx = workflow["app"].ctx
    ctx.participant = "P-014"

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, ui_px(52)))
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(ui_px(12), ui_px(4)))
        imgui.begin("brand-header", flags=imgui.WindowFlags_.no_title_bar)
        right_edges.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        workflow["header"].ui(ctx, workflow["_step_done"](ctx))
        imgui.end()
        imgui.pop_style_var()

    # Cached pill widths settle on the second frame, as they do on screen.
    imgui_frame(draw)
    controls.clear()
    titles.clear()
    dividers.clear()
    imgui_frame(draw)
    assert len(controls) == 6
    assert bool(titles) is show_title
    assert bool(dividers) is show_title
    logo = logo_image[1][-1]
    assert logo[1][1] - logo[0][1] == pytest.approx(ui_px(26))
    group_end = titles[-1][1][0] if show_title else logo[1][0]
    assert controls[0][0][0] - group_end == pytest.approx(ui_px(14), abs=1)
    items = [logo, *titles, *controls]
    assert all(left[1][0] <= right[0][0] for left, right in zip(items, items[1:], strict=False))
    centers = [(lo[1] + hi[1]) / 2 for lo, hi in items]
    assert max(centers) - min(centers) <= 2 * scale
    assert all(hi[0] <= right_edges[-1] and hi[1] <= ui_px(52) for _, hi in items)
    assert controls[-1][1][0] == pytest.approx(right_edges[-1])
    if show_title:
        start, end, color, thickness = dividers[0]
        assert end[1] - start[1] == pytest.approx(ui_px(20))
        assert thickness == ui_px(1)
        assert color == imgui.get_color_u32(hairline())


def test_header_pill_stays_inside_on_the_first_frame_after_scaling(
    imgui_frame,
    monkeypatch,
    logo_image,
    workflow,
):
    pill = workflow["header"].ui.__func__.__globals__["status_pill"]
    right_edges, pill_edges = [], []

    def track_pill(label, color):
        pill(label, color)
        pill_edges.append(imgui.get_item_rect_max().x)

    monkeypatch.setitem(workflow["header"].ui.__func__.__globals__, "status_pill", track_pill)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(ui_px(1280), ui_px(52)))
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(ui_px(12), ui_px(4)))
        imgui.begin("resizing-header", flags=imgui.WindowFlags_.no_title_bar)
        right_edges.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        workflow["header"].ui(workflow["app"].ctx)
        imgui.end()
        imgui.pop_style_var()

    for scale in [1.0, 2.0]:
        monkeypatch.setattr(_scale, "_current", scale)
        _theme.apply_theme()
        imgui.get_style().scale_all_sizes(scale)
        imgui.get_style().font_scale_main = scale
        imgui.get_io().display_size = imgui.ImVec2(ui_px(1280), ui_px(200))
        imgui_frame(draw)
        assert pill_edges[-1] <= right_edges[-1]
