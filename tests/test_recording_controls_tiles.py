"""Gesture targets share the kit's captions, selection and categorical colours."""

from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from myogestic import _scale, _theme
from myogestic.core import Context
from myogestic.widgets import RecordingControls
from myogestic.widgets.common import PALETTE, muted, ui_px
from myogestic.widgets.panels import _recording_controls as module


@pytest.fixture
def tiles(monkeypatch):
    """Observe real ImGui items and draw commands while injecting button clicks."""
    seen = SimpleNamespace(tiles={}, dots=[], names=[], captions=[], depth=0, click=None)
    button, text_colored = imgui.button, imgui.text_colored
    push, pop = module.push_selected, module.pop_selected
    get_draw_list = imgui.get_window_draw_list

    def push_selected():
        seen.depth += 1
        push()

    def pop_selected():
        pop()
        seen.depth -= 1
        assert seen.depth == 0

    def draw_button(label, *args):
        result = button(label, *args)
        key = label.split("##")[-1]
        if key.startswith("rec_gesture"):
            lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
            seen.tiles[int(key.removeprefix("rec_gesture"))] = (
                bool(seen.depth), imgui.get_style().alpha, (lo.x, lo.y, hi.x, hi.y),
            )
        return key == seen.click or result

    def caption(tone, text):
        seen.captions.append((text, tuple(tone), imgui.get_style().alpha))
        text_colored(tone, text)

    class DrawList:
        def __init__(self, draw):
            self.draw = draw

        def __getattr__(self, name):
            return getattr(self.draw, name)

        def add_circle_filled(self, pos, radius, color, *args):
            seen.dots.append((pos.x, pos.y, radius, color))
            self.draw.add_circle_filled(pos, radius, color, *args)

        def add_text(self, pos, color, text, *args):
            size = imgui.calc_text_size(text)
            seen.names.append((text, (pos.x, pos.y, pos.x + size.x, pos.y + size.y)))
            self.draw.add_text(pos, color, text, *args)

    monkeypatch.setattr(module, "push_selected", push_selected)
    monkeypatch.setattr(module, "pop_selected", pop_selected)
    monkeypatch.setattr(imgui, "button", draw_button)
    monkeypatch.setattr(imgui, "text_colored", caption)
    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: DrawList(get_draw_list()))
    return seen


@pytest.mark.parametrize("dark", [False, True])
def test_gesture_caption_is_muted_without_colon(imgui_frame, monkeypatch, tiles, dark):
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    controls = RecordingControls(["Rest", "Fist"], on_record=lambda: None, on_stop=lambda: None)
    imgui_frame(lambda: controls.ui(Context()))
    assert ("Gesture", tuple(muted()), 1.0) in tiles.captions
    assert all(text != "Gesture:" for text, _, _ in tiles.captions)


@pytest.mark.parametrize("initial,expected", [(-1, 0), (0, 0), (1, 1), (99, 0)])
def test_default_and_clicked_gesture_match_the_next_take(imgui_frame, tiles, initial, expected):
    labels, callbacks = [], []
    ctx = Context(current_label=initial)

    def start():
        ctx.state = "recording"
        ctx.recording = True
        ctx.session = SimpleNamespace(add_label=labels.append)

    controls = RecordingControls(["Rest", "Fist"], on_record=start, on_stop=lambda: None,
                                 on_gesture=callbacks.append)
    imgui_frame(lambda: controls.ui(ctx))
    assert [i for i, (on, _, _) in tiles.tiles.items() if on] == [expected]
    # Showing the default does not relabel the shared context until an action.
    assert ctx.current_label == (initial if initial < 2 else -1)
    assert callbacks == []

    # Click in both directions: changing the live index mid-loop must never
    # leave a frame with zero or two selected targets, or an unpaired style.
    chosen = 1 - expected
    tiles.click = f"rec_gesture{chosen}"
    imgui_frame(lambda: controls.ui(ctx))
    assert sum(on for on, _, _ in tiles.tiles.values()) == 1
    assert tiles.depth == 0
    assert callbacks == [chosen]
    tiles.click = None
    imgui_frame(lambda: controls.ui(ctx))
    assert [i for i, (on, _, _) in tiles.tiles.items() if on] == [chosen]
    tiles.click = "rec_btn"
    imgui_frame(lambda: controls.ui(ctx))
    assert labels == [chosen]
    assert controls.take.gesture == ["Rest", "Fist"][chosen]


@pytest.mark.parametrize("timed", [False, True])
def test_record_uses_the_visible_default_without_a_tile_click(imgui_frame, tiles, timed):
    ctx = Context()
    labels = []

    def start():
        ctx.state = "recording"
        ctx.recording = True
        ctx.session = SimpleNamespace(add_label=labels.append)

    controls = RecordingControls(["Rest", "Fist"], on_record=start, on_stop=lambda: None,
                                 take_lengths=(5,), timed=timed)
    imgui_frame(lambda: controls.ui(ctx))
    assert ctx.current_label == -1
    assert tiles.tiles[0][0] is True
    tiles.click = "rec_btn"
    imgui_frame(lambda: controls.ui(ctx))
    assert labels == [0]
    assert controls.take.gesture == "Rest"


def test_tile_dots_use_the_shared_palette_index_cycle(imgui_frame, tiles):
    names = [f"Gesture {i}" for i in range(len(PALETTE) + 2)]
    controls = RecordingControls(names, on_record=lambda: None, on_stop=lambda: None)
    expected = []

    def draw():
        expected.extend(imgui.get_color_u32(imgui.ImVec4(*PALETTE[i % len(PALETTE)], 1.0))
                        for i in range(len(names)))
        controls.ui(Context())

    imgui_frame(draw)
    assert [color for _, _, _, color in tiles.dots] == expected


@pytest.mark.parametrize("phase", ["warmup", "recording"])
def test_timed_take_keeps_selected_gesture_and_explains_locked_tiles(imgui_frame, tiles, phase):
    labels = []
    ctx = Context(current_label=1)

    def start():
        ctx.state = "recording"
        ctx.recording = True
        ctx.session = SimpleNamespace(add_label=labels.append)

    controls = RecordingControls(["Rest", "Fist"], on_record=start, on_stop=lambda: None,
                                 timed=True, take_lengths=(5,), warmups=(2,))
    now = [0.0]
    controls._machine._clock = lambda: now[0]
    controls._start(ctx)
    now[0] = 2.0 if phase == "recording" else 0.0
    tiles.click = "rec_gesture0"
    imgui_frame(lambda: controls.ui(ctx))
    assert controls.take.phase == phase
    assert controls.take.gesture == "Fist"
    assert ctx.current_label == 1
    assert tiles.tiles[1][:2] == (True, 1.0)
    assert tiles.tiles[0][0] is False
    assert tiles.tiles[0][1] < tiles.tiles[1][1]
    caption = ("Cancel the warm-up to change gestures." if phase == "warmup"
               else "Stop the recording to change gestures.")
    assert (caption, tuple(muted()), 1.0) in tiles.captions
    assert labels == ([1] if phase == "recording" else [])


@pytest.mark.parametrize("width", [600, 320])
def test_large_tiles_and_dot_labels_fit_light_theme_at_scale_two(
    imgui_frame, monkeypatch, tiles, width,
):
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    controls = RecordingControls(["Rest", "A very long gesture name that needs clipping"],
                                 on_record=lambda: None, on_stop=lambda: None)
    bounds = []

    def draw():
        tiles.dots.clear()
        tiles.names.clear()
        imgui.begin_child("tiles", imgui.ImVec2(width, 400), child_flags=imgui.ChildFlags_.borders)
        left = imgui.get_cursor_screen_pos().x
        bounds[:] = [left, left + imgui.get_content_region_avail().x]
        controls.ui(Context())
        imgui.end_child()

    for _ in range(4):
        imgui_frame(draw)
    assert len(tiles.dots) == len(tiles.names) == len(tiles.tiles) == 2
    for (_, _, box), (x, y, radius, _), (_, text) in zip(
        tiles.tiles.values(), tiles.dots, tiles.names, strict=True,
    ):
        assert bounds[0] <= box[0] < box[2] <= bounds[1] + 1
        assert box[3] - box[1] == pytest.approx(ui_px(44))
        assert box[0] <= x - radius < x + radius < text[0] < text[2] <= box[2]
        assert box[1] <= y - radius < y + radius <= box[3]
        assert box[1] <= text[1] < text[3] <= box[3]
    if width == 320:
        assert tiles.tiles[0][2][3] <= tiles.tiles[1][2][1]
