"""The training cursor leaves a bounded history, never a preview of its next move."""

import math
from itertools import pairwise

import pytest
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, ui_px
from myogestic.widgets.pong import PongTask


def test_cursor_history_uses_the_ui_clock_and_belongs_to_each_widget(imgui_frame, monkeypatch):
    now = [10.0]
    monkeypatch.setattr("myogestic.widgets.pong.time.monotonic", lambda: now[0])
    task, twin = PongTask(widget_id="history"), PongTask(widget_id="twin")

    imgui_frame(lambda: task.ui(-0.9, target=0.25))
    now[0] = 10.5
    imgui_frame(lambda: task.ui(0.9, target=-0.5))
    assert task._cursor_history == [(10.0, task._ghost_y(0.25)), (10.5, task._ghost_y(-0.5))]
    assert twin._cursor_history == []

    imgui_frame(lambda: twin.ui(0.0, target=1.0))
    imgui_frame(lambda: task.ui(0.0))
    assert task._cursor_history == [], "ending a block left its old cursor path behind"
    assert twin._cursor_history == [(10.5, twin._ghost_y(1.0))]
    now[0] = 11.0
    imgui_frame(lambda: task.ui(0.0, target=0.0))
    assert task._cursor_history == [(11.0, 0.0)], "a new block inherited the last one's path"


def test_cursor_history_drops_points_older_than_three_seconds():
    task = PongTask()
    for now in (10.0, 11.0, 12.0, 13.0):
        task._remember_cursor(now, 0.25)
    assert task._cursor_history[0][0] == 10.0
    task._remember_cursor(13.1, -0.25)
    assert task._cursor_history[0][0] == 11.0
    task._remember_cursor(17.0, 0.5)
    assert task._cursor_history == [(17.0, 0.5)], "a gap joined two unrelated observations"


def test_a_long_fast_block_keeps_three_seconds_in_bounded_space():
    task = PongTask()
    for frame in range(6001):  # 25 seconds at 240 Hz
        now = frame / 240.0
        task._remember_cursor(now, math.sin(now))
        assert len(task._cursor_history) <= 120
    assert task._cursor_history[-1] == (25.0, math.sin(25.0))
    assert 2.9 <= 25.0 - task._cursor_history[0][0] <= 3.0
    assert all(a[0] < b[0] for a, b in pairwise(task._cursor_history))


class _TrailRecorder:
    """Observe real draw calls, including the clipping active for each red dash."""

    def __init__(self, get_draw_list):
        self.get_draw_list = get_draw_list
        self.lines = []
        self.fills = []
        self.labels = []
        self.clips = []

    def add_line(self, a, b, color, **kwargs):
        self.lines.append(
            (a.x, a.y, b.x, b.y, color, kwargs["thickness"], self.clips[-1] if self.clips else None)
        )
        self.get_draw_list().add_line(a, b, color, **kwargs)

    def add_rect_filled(self, a, b, color, **kwargs):
        self.fills.append((a.x, a.y, b.x, b.y))
        self.get_draw_list().add_rect_filled(a, b, color, **kwargs)

    def add_text(self, pos, color, text):
        self.labels.append((pos.x, pos.x + imgui.calc_text_size(text).x))
        self.get_draw_list().add_text(pos, color, text)

    def push_clip_rect(self, a, b, *args, **kwargs):
        self.clips.append((a.x, a.y, b.x, b.y))
        self.get_draw_list().push_clip_rect(a, b, *args, **kwargs)

    def pop_clip_rect(self):
        self.clips.pop()
        self.get_draw_list().pop_clip_rect()

    def __getattr__(self, name):
        return getattr(self.get_draw_list(), name)

    def red_lines(self):
        rgb = imgui.get_color_u32(DANGER) & 0xFFFFFF
        # The command meter also has a red reference tick, outside the court clip.
        return [line for line in self.lines if line[4] & 0xFFFFFF == rgb and line[6] is not None]


@pytest.mark.parametrize("targets", [(0.25, 0.25, 0.25), (-0.6, 0.4, -0.2)])
def test_cursor_trail_runs_from_the_ghost_into_observed_history(imgui_frame, monkeypatch, targets):
    task = PongTask()
    now = [10.0]
    monkeypatch.setattr("myogestic.widgets.pong.time.monotonic", lambda: now[0])
    rec = _TrailRecorder(imgui.get_window_draw_list)
    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: rec)
    for stamp, target in zip((10.0, 11.5, 13.0), targets, strict=True):
        now[0] = stamp
        rec.lines.clear()
        rec.fills.clear()
        imgui_frame(lambda target=target: task.ui(0.0, target=target))

    lines = rec.red_lines()
    assert lines, "the block drew no cursor history"
    x0, y0, x1, y1 = court = rec.fills[0]
    width, height = x1 - x0, y1 - y0
    assert lines[0][:2] == pytest.approx((x1, y0 + (1 - task._ghost_y(targets[-1])) * height / 2))
    assert x0 + width * 0.5 <= min(line[2] for line in lines) <= x0 + width * 0.5 + ui_px(11)
    assert all(x0 <= line[2] < line[0] <= x1 for line in lines), (
        "the trail anticipated a future position"
    )
    assert all(line[6] == court for line in lines), "the trail was not clipped to the court"
    assert not rec.clips, "the trail left its clip rect pushed"

    # Every dash endpoint lies on an interpolation of observations we actually saw.
    for line in lines:
        for x, y in (line[:2], line[2:4]):
            age = (x1 - x) * 6.0 / width
            levels = targets[::-1]
            segment = min(int(age / 1.5), 1)
            fraction = (age - segment * 1.5) / 1.5
            level = levels[segment] + fraction * (levels[segment + 1] - levels[segment])
            assert y == pytest.approx(y0 + (1 - task._ghost_y(level)) * height / 2, abs=1e-3)
    alphas = [(line[4] >> 24) / 255 for line in lines]
    assert alphas[0] > 0.55
    assert alphas[-1] == pytest.approx(0.15, abs=0.06)
    assert all(a >= b for a, b in pairwise(alphas))

    if len(set(targets)) == 1:
        assert max(line[0] - line[2] for line in lines) == pytest.approx(ui_px(5), abs=1e-3)
        gaps = [a[2] - b[0] for a, b in pairwise(lines) if a[2] - b[0] > 1e-3]
        assert gaps and all(gap == pytest.approx(ui_px(6), abs=1e-3) for gap in gaps)


def test_a_court_without_a_target_does_not_draw_stale_cursor_history(imgui_frame, monkeypatch):
    task = PongTask()
    for now in (10.0, 11.5, 13.0):
        task._remember_cursor(now, 0.5)
    rec = _TrailRecorder(imgui.get_window_draw_list)
    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: rec)
    imgui_frame(lambda: task._court_ui(None))
    assert rec.fills, "the court itself did not draw"
    assert not rec.red_lines()


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_cursor_trail_fits_a_light_320px_court_at_ui_scale(imgui_frame, monkeypatch, scale):
    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    task = PongTask(court_height=0)
    now = [10.0]
    monkeypatch.setattr("myogestic.widgets.pong.time.monotonic", lambda: now[0])
    rec = _TrailRecorder(imgui.get_window_draw_list)
    monkeypatch.setattr(imgui, "get_window_draw_list", lambda: rec)
    bounds = []

    def draw(target):
        imgui.begin_child("court-320", imgui.ImVec2(320, 440))
        left = imgui.get_cursor_screen_pos().x
        bounds.append((left, left + imgui.get_content_region_avail().x))
        task.ui(0.0, target=target, effort=0.4)
        imgui.end_child()

    for frame in range(7):
        now[0] = 10.0 + frame * 0.5
        rec.lines.clear()
        rec.fills.clear()
        rec.labels.clear()
        imgui_frame(lambda frame=frame: draw(1.0 if frame % 2 else -1.0))

    lines = rec.red_lines()
    assert lines
    x0, y0, x1, y1 = court = rec.fills[0]
    lo, hi = bounds[-1]
    assert lo <= x0 < x1 <= hi
    assert all(lo - 1 <= a <= b <= hi + 1 for a, b in rec.labels)
    for ax, ay, bx, by, _color, thickness, clip in lines:
        assert x0 <= bx < ax <= x1
        assert y0 <= ay <= y1 and y0 <= by <= y1
        assert thickness == pytest.approx(ui_px(2))
        assert math.hypot(bx - ax, by - ay) <= ui_px(5) + 1e-3
        assert clip == court
    assert not rec.clips
