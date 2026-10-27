"""Training review chips keep row state and fit narrow, scaled panels."""

from pathlib import Path

import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme
from myogestic.widgets import TemplateInspector, TemplateInspectorRow
from myogestic.widgets.training.template_inspector import clear_selection


def _rows():
    return [
        TemplateInspectorRow("session#0", "OPEN", info_text="first source", energy=0.8),
        TemplateInspectorRow("session#1", "CLOSED", False, "second source", 0.4),
        TemplateInspectorRow("session#2", "OPEN", info_text="third source"),
    ]


def _buttons(monkeypatch):
    seen, click = [], {"label": None}
    button = imgui.small_button

    def press(label):
        seen.append(label)
        button(label)
        return label == click["label"]

    monkeypatch.setattr(imgui, "small_button", press)
    monkeypatch.setattr(imgui, "checkbox", lambda *a: pytest.fail("keep/out must be chips"))
    return seen, click


def test_kept_chip_toggles_both_directions_and_bulk_actions(imgui_frame, monkeypatch):
    rows = _rows()
    inspector = TemplateInspector("keep-test")
    seen, click = _buttons(monkeypatch)
    imgui_frame(lambda: inspector.ui(rows))
    assert "Kept##keep" in seen and "Out##keep" in seen
    click["label"] = "Kept##keep"
    imgui_frame(lambda: inspector.ui(rows))
    assert not any(row.accepted for row in rows)
    click["label"] = "Out##keep"
    imgui_frame(lambda: inspector.ui(rows))
    assert all(row.accepted for row in rows)
    click["label"] = "None##keep_none"
    imgui_frame(lambda: inspector.ui(rows))
    assert not any(row.accepted for row in rows)
    click["label"] = "All##keep_all"
    imgui_frame(lambda: inspector.ui(rows))
    assert all(row.accepted for row in rows)


def test_filter_counts_and_selection_are_per_widget_identity(imgui_frame, monkeypatch):
    rows = _rows()
    seen, click = _buttons(monkeypatch)
    select = imgui.selectable
    visible = []
    selecting = {"enabled": True}

    def choose(label, *args, **kwargs):
        visible.append(label)
        result = select(label, *args, **kwargs)
        return (True, True) if selecting["enabled"] and "first source" in label else result

    monkeypatch.setattr(imgui, "selectable", choose)
    result = []
    imgui_frame(lambda: result.append(TemplateInspector("filter-a").ui(rows)))
    assert result[-1] == "session#0"
    selecting["enabled"] = False
    click["label"] = next(label for label in seen if "CLOSED" in label and "filter" in label)
    assert any("OPEN · 2" in label for label in seen)
    visible.clear()
    imgui_frame(lambda: result.append(TemplateInspector("filter-a").ui(rows)))
    assert len(visible) == 1 and "second source" in visible[0]
    assert result[-1] == "session#0"  # Filtering never discards the preview selection.
    click["label"] = "All##keep_all"
    imgui_frame(lambda: TemplateInspector("filter-a").ui(rows))
    assert all(row.accepted for row in rows)  # Bulk actions include hidden rows.
    click["label"] = None
    visible.clear()
    imgui_frame(lambda: result.append(TemplateInspector("filter-b").ui(rows)))
    assert result[-1] is None and len(visible) == 3
    imgui_frame(lambda: result.append(TemplateInspector("filter-a").ui(rows[1:])))
    assert result[-1] is None
    clear_selection("filter-a")


def test_row_ids_follow_keys_when_rows_reorder(imgui_frame, monkeypatch):
    rows = _rows()
    inspector = TemplateInspector("row-ids")
    ids = []
    select = imgui.selectable

    def capture(label, *args, **kwargs):
        ids.append((label.split("##")[0], imgui.get_id(label)))
        return select(label, *args, **kwargs)

    monkeypatch.setattr(imgui, "selectable", capture)
    imgui_frame(lambda: inspector.ui(rows))
    first = dict(ids)
    ids.clear()
    imgui_frame(lambda: inspector.ui(rows[::-1]))
    assert dict(ids) == first


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
def test_review_rows_fit_narrow_panels(imgui_frame, monkeypatch, scale, dark):
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    font_path = Path(_theme.__file__).parent / "assets/fonts/IBMPlexMono-Regular.ttf"
    mono_font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 13)
    monkeypatch.setattr(_theme, "_MONO_FONT", mono_font)
    rows = [
        TemplateInspectorRow(
            "session#123",
            "A very long gesture name",
            True,
            "a very long source path / recording / trial",
            0.8,
        )
    ]
    inspector = TemplateInspector("narrow", label_colors={rows[0].label: (1.0, 1.0, 1.0, 1.0)})
    boxes, sources, bars, heights, colors = [], [], [], [], []
    button, select, progress = imgui.small_button, imgui.selectable, imgui.progress_bar
    begin, colored, plain = imgui.begin_table, imgui.text_colored, imgui.text_unformatted
    mono_items = []

    def capture_button(label):
        result = button(label)
        boxes.append(imgui.get_item_rect_max().x)
        return result

    def capture_source(label, *args, **kwargs):
        assert imgui.get_font() == mono_font
        result = select(label, *args, **kwargs)
        sources.append(label.split("##")[0])
        boxes.append(imgui.get_item_rect_max().x)
        return result

    def capture_bar(value, size, overlay):
        bars.append((value, size.y))
        progress(value, size, overlay)
        boxes.append(imgui.get_item_rect_max().x)

    def capture_table(label, columns, flags, size):
        heights.append(size.y)
        return begin(label, columns, flags, size)

    def capture_text(color, label):
        colors.append((color.x, color.y, color.z))
        colored(color, label)
        boxes.append(imgui.get_item_rect_max().x)

    def capture_plain(label):
        plain(label)
        boxes.append(imgui.get_item_rect_max().x)
        if label.startswith("#"):
            mono_items.append((label, imgui.get_font()))

    monkeypatch.setattr(imgui, "small_button", capture_button)
    monkeypatch.setattr(imgui, "selectable", capture_source)
    monkeypatch.setattr(imgui, "progress_bar", capture_bar)
    monkeypatch.setattr(imgui, "begin_table", capture_table)
    monkeypatch.setattr(imgui, "text_colored", capture_text)
    monkeypatch.setattr(imgui, "text_unformatted", capture_plain)
    bounds = []

    def draw():
        imgui.begin_child("narrow-panel", imgui.ImVec2(320, 420))
        bounds.append(imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x)
        inspector.ui(rows)
        imgui.end_child()

    for _ in range(2):
        boxes.clear()
        imgui_frame(draw)
    assert heights[-1] == 240 * scale
    assert sources[-1].endswith("…")
    assert all(right <= bounds[-1] + 1 for right in boxes)
    assert bars[-1][0] == 1 and 0 < bars[-1][1] < imgui.get_text_line_height()
    assert mono_items[-1] == ("#123", mono_font)
    # Caller white remains an identity tint; it cannot turn label text white on light.
    if not dark:
        assert (1.0, 1.0, 1.0) not in colors


def test_empty_review_gives_next_step(imgui_frame, monkeypatch):
    text = []
    disabled = imgui.text_disabled

    def capture(label):
        text.append(label)
        disabled(label)

    monkeypatch.setattr(imgui, "text_disabled", capture)
    imgui_frame(lambda: TemplateInspector("empty-review").ui([]))
    assert any("Extract templates" in label for label in text)


def test_gesture_tints_and_selection_use_the_theme(imgui_frame, monkeypatch):
    from myogestic.widgets.common import PALETTE

    rows = _rows()
    inspector = TemplateInspector("tints", label_colors={"OPEN": (0.1, 0.2, 0.3, 1.0)})
    select, convert, background = imgui.selectable, imgui.get_color_u32, imgui.table_set_bg_color
    colors, backgrounds = [], []

    def choose(label, *args, **kwargs):
        result = select(label, *args, **kwargs)
        return (True, True) if "first source" in label else result

    def capture_color(color, *args):
        if isinstance(color, imgui.ImVec4):
            colors.append(tuple(color))
        return convert(color, *args)

    def capture_background(target, color, *args):
        backgrounds.append(color)
        background(target, color, *args)

    monkeypatch.setattr(imgui, "selectable", choose)
    monkeypatch.setattr(imgui, "get_color_u32", capture_color)
    monkeypatch.setattr(imgui, "table_set_bg_color", capture_background)
    for _ in range(2):
        imgui_frame(lambda: inspector.ui(rows))
    assert any(color == pytest.approx((*PALETTE[0], 0.18)) for color in colors)
    assert any(color == pytest.approx((0.1, 0.2, 0.3, 0.18)) for color in colors)
    assert convert(imgui.Col_.text_selected_bg) in backgrounds
