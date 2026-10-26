"""The shared header fits a bare Grid row, with independent widget identities."""

import platform
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui
from imgui_bundle import icons_fontawesome_6 as fa

from myogestic import Context, Fr, Grid, Px, _scale, _theme
from myogestic.widgets import AppHeader, ParticipantPanel, StepBar
from myogestic.widgets.common import ui_px
from myogestic.widgets.panels import app_header


@pytest.fixture
def real_fonts(imgui_frame):
    """Measure the body font and merged check glyph used by the application."""
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    atlas = imgui.get_io().fonts
    imgui.get_io().font_default = atlas.add_font_from_file_ttf(str(font_path), 14)
    config = imgui.ImFontConfig()
    config.merge_mode = True
    atlas.add_font_from_file_ttf(
        hello_imgui.asset_file_full_path("fonts/Font_Awesome_6_Free-Solid-900.otf"), 14, config,
    )


@pytest.fixture
def probe(imgui_frame, monkeypatch, tmp_path):
    """Measure real ImGui items and clip bounds without an image backend."""
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: True)
    monkeypatch.setattr(hello_imgui, "image_and_size_from_asset", lambda name: SimpleNamespace(
        texture_id=1, size=imgui.ImVec2(519, 128),
    ))
    records = []

    def remember(kind, label=""):
        draw = imgui.get_window_draw_list()
        records.append(SimpleNamespace(
            kind=kind, label=label,
            lo=tuple(imgui.get_item_rect_min()), hi=tuple(imgui.get_item_rect_max()),
            clip_lo=tuple(draw.get_clip_rect_min()), clip_hi=tuple(draw.get_clip_rect_max()),
            padding=imgui.get_style().frame_padding.x,
        ))

    def image(texture, size):
        imgui.dummy(size)
        remember("logo")

    button, text, plain, pill = imgui.button, imgui.text_colored, imgui.text_unformatted, app_header.status_pill

    def track_button(label, *args, **kwargs):
        result = button(label, *args, **kwargs)
        if "###step" in label or label.endswith("###chip"):
            remember("step" if "###step" in label else "participant", label)
        return result

    def track_text(color, label):
        text(color, label)
        remember("text", label)

    def track_plain(label):
        plain(label)
        remember("text", label)

    def track_pill(label, color):
        pill(label, color)
        remember("pill", label)

    monkeypatch.setattr(imgui, "image", image)
    monkeypatch.setattr(imgui, "button", track_button)
    monkeypatch.setattr(imgui, "text_colored", track_text)
    monkeypatch.setattr(imgui, "text_unformatted", track_plain)
    monkeypatch.setattr(app_header, "status_pill", track_pill)
    grid = Grid.areas("header\nbody", row_height=[Px(52), Fr(1)], bare=("header",))
    ctx = Context(participant="P-014")
    participant = ParticipantPanel(key_file=tmp_path / "key.csv", widget_id="header-participant")

    def render(header, width=1100, scale=1.0, done=None):
        monkeypatch.setattr(_scale, "_current", scale)
        _theme.apply_theme()
        imgui.get_style().scale_all_sizes(scale)
        imgui.get_style().font_scale_main = scale
        imgui.get_io().display_size = imgui.ImVec2(width + 100, 1656)
        bounds, scroll, result = [], [], []

        def draw():
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(width, 1656))
            imgui.begin("header-probe", flags=imgui.WindowFlags_.no_title_bar)
            with grid.area("header"):
                origin, size = imgui.get_window_pos(), imgui.get_window_size()
                bounds[:] = [tuple(origin), (origin.x + size.x, origin.y + size.y)]
                result[:] = [header.ui(ctx, done)]
                scroll[:] = [imgui.get_scroll_max_x(), imgui.get_scroll_max_y()]
            imgui.end()

        frames = []
        for _ in range(4):
            records.clear()
            imgui_frame(draw)
            frames.append(list(records))
        return SimpleNamespace(items=list(records), frames=frames, bounds=bounds, scroll=scroll, active=result[0])

    return SimpleNamespace(render=render, participant=participant, ctx=ctx)


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("width", [640, 720, 1100, 1800])
@pytest.mark.parametrize("done", [[False] * 4, [True, True, True, False], [True] * 4])
@pytest.mark.parametrize("active", range(4))
@pytest.mark.parametrize("state", ["idle", "predicting"])
def test_physical_window_contains_every_header_item(real_fonts, probe, scale, width, done, active, state):
    probe.ctx.state = state
    steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="physical-header")
    steps.active = active
    view = probe.render(AppHeader("Myocontrol", steps=steps, participant=probe.participant),
                        width, scale, done)
    assert view.active == active
    assert view.scroll == [0, 0]
    for items in view.frames:
        pill, = [item for item in items if item.kind == "pill"]
        assert pill.hi[0] == pytest.approx(view.bounds[1][0] - ui_px(18), abs=1)
        assert len([item for item in items if item.kind == "step"]) == 4
        for item in items:
            # Only the participant lives in an intentionally clipped child.
            # Navigation must fit its actual item bounds, without relying on clipping.
            right = min(item.hi[0], item.clip_hi[0]) if item.kind == "participant" else item.hi[0]
            assert right <= view.bounds[1][0], (item.kind, item.label, item.hi, view.bounds)
            if item.kind != "pill":
                assert right <= pill.lo[0], (item.kind, item.label, item.hi, pill.lo)
    # A missing icon would use the fallback glyph and hide the completion-width bug.
    assert imgui.calc_text_size(fa.ICON_FA_CHECK).x > imgui.calc_text_size("1").x


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("width", [640, 1100, 1800])
@pytest.mark.parametrize("with_steps", [False, True])
@pytest.mark.parametrize("state,participant", [
    ("idle", "P-014"), ("recording", ""), ("training", "P-014"),
    ("predicting", "a-long-participant-identifier-that-yields-to-the-state"),
])
def test_bare_header_fits_and_reserves_the_state(probe, scale, width, with_steps, state, participant):
    probe.ctx.state, probe.ctx.participant = state, participant
    steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="header-steps")
    steps.active = 2
    header = AppHeader("Myocontrol", steps=steps if with_steps else None,
                       participant=probe.participant)
    view = probe.render(header, width, scale)
    assert view.active == (2 if with_steps else None)
    assert view.scroll == [0, 0]
    logo, = [item for item in view.items if item.kind == "logo"]
    pill, = [item for item in view.items if item.kind == "pill"]
    assert 0 < logo.hi[1] - logo.lo[1] <= ui_px(26)
    if width >= 1100 or not with_steps:
        assert logo.hi[1] - logo.lo[1] == pytest.approx(ui_px(26))
    assert pill.hi[0] == pytest.approx(view.bounds[1][0] - ui_px(18), abs=1)
    visible = []
    for item in view.items:
        if item.kind == "text":
            continue
        lo = tuple(max(a, b) for a, b in zip(item.lo, item.clip_lo, strict=True))
        hi = tuple(min(a, b) for a, b in zip(item.hi, item.clip_hi, strict=True))
        if hi[0] <= lo[0]:
            continue
        assert item.lo[1] >= item.clip_lo[1] - 1
        assert item.hi[1] <= item.clip_hi[1] + 1
        if item.kind != "pill":
            assert hi[0] <= pill.lo[0]
        visible.append((lo, hi))
    assert all(left[1][0] <= right[0][0] for left, right in zip(visible, visible[1:], strict=False))
    centers = [(lo[1] + hi[1]) / 2 for lo, hi in visible]
    assert max(centers) - min(centers) <= 2 * scale


def test_participant_then_title_yield_before_step_padding(probe):
    title = "Myocontrol " * 6
    header = AppHeader(title, steps=StepBar(["Connect", "Record", "Train", "Drive"]),
                       participant=probe.participant)
    wide = probe.render(header, 1800)
    yielding_participant = probe.render(header, 1200)
    middle = probe.render(header, 1100)
    narrow = probe.render(header, 640)
    assert any(item.label == title for item in wide.items)
    assert any(item.kind == "participant" for item in wide.items)
    assert any(item.label == title for item in yielding_participant.items)
    chip, = [item for item in yielding_participant.items if item.kind == "participant"]
    assert chip.hi[0] > chip.clip_hi[0]
    assert not any(item.label == title for item in middle.items)
    assert {item.padding for item in wide.items if item.kind == "step"} == {10}
    assert {item.padding for item in middle.items if item.kind == "step"} == {10}
    assert {item.padding for item in narrow.items if item.kind == "step"} == {4}


@pytest.mark.parametrize("active", range(4))
@pytest.mark.parametrize("done", [[False] * 4, [True] * 4])
def test_narrow_active_label_ellipsizes_with_full_label_on_hover(real_fonts, probe, monkeypatch, active, done):
    steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="ellipsis-header")
    steps.active = active
    probe.ctx.state = "predicting"
    tooltips = []
    monkeypatch.setattr(imgui, "is_item_hovered", lambda *args: True)
    monkeypatch.setattr(imgui, "set_tooltip", tooltips.append)
    view = probe.render(AppHeader("Session", steps=steps), 640, 2, done)
    labels = [item.label.split("###")[0] for item in view.items if item.kind in {"text", "step"}]
    assert any(label.endswith("…") for label in labels)
    assert set(steps.steps) <= set(tooltips)
    logo, = [item for item in view.items if item.kind == "logo"]
    assert 0 < logo.hi[1] - logo.lo[1] < ui_px(26)


def test_title_without_steps_ellipsizes_and_exposes_full_text(probe, monkeypatch):
    title = "An intentionally long title for the signal acquisition and analysis viewer " * 4
    tooltips = []
    monkeypatch.setattr(imgui, "is_item_hovered", lambda *args: True)
    monkeypatch.setattr(imgui, "set_tooltip", tooltips.append)
    view = probe.render(AppHeader(title, participant=probe.participant), 640)
    labels = [item.label for item in view.items if item.kind == "text"]
    assert view.active is None
    assert any(label.endswith("…") and title.startswith(label[:-1]) for label in labels)
    assert title in tooltips


@pytest.mark.parametrize("scale", [1., 2.])
def test_header_shows_participant_id_without_revealing_the_local_name(probe, scale):
    probe.participant._state.active_pid = probe.ctx.participant
    probe.participant._state.local_name = "A very long local name " * 20
    header = AppHeader("Myocontrol", participant=probe.participant,
                       steps=StepBar(["Connect", "Record", "Train", "Drive"]))
    view = probe.render(header, 900 * scale, scale)
    pill, = [item for item in view.items if item.kind == "pill"]
    chip, = [item for item in view.items if item.kind == "participant"]
    assert chip.label == f"{probe.ctx.participant}###chip"
    assert not any(probe.participant._state.local_name in item.label for item in view.items)
    assert chip.hi[0] <= chip.clip_hi[0] < pill.lo[0]
    for item in view.items:
        assert view.bounds[0][0] <= item.lo[0] <= item.hi[0] <= view.bounds[1][0]
    assert view.scroll == [0, 0]


def test_optional_state_and_participant_are_absent(probe):
    view = probe.render(AppHeader("Viewer", show_state=False), 640)
    assert [item.kind for item in view.items] == ["logo", "text"]
    assert view.items[-1].label == "Viewer"


def test_done_flags_and_selection_are_forwarded(probe, monkeypatch):
    steps = StepBar(["Connect", "Record"], widget_id="click-header")
    button = imgui.button

    def click(label, *args, **kwargs):
        result = button(label, *args, **kwargs)
        return True if label.endswith("###step1") else result

    monkeypatch.setattr(imgui, "button", click)
    view = probe.render(AppHeader("Session", steps=steps), done=[True, False])
    assert view.active == steps.active == 1
    assert any(item.label == "###step0" for item in view.items)


def test_width_caches_are_owned_by_each_header(probe):
    first = AppHeader("First", widget_id="first")
    second = AppHeader("Second", widget_id="second")
    probe.render(first)
    probe.render(second, scale=2)
    # Rendering a second identity at another scale must not replace the first cache.
    assert first._widths is not second._widths
    assert "first" in first._widths and "second" not in first._widths
    assert "second" in second._widths and "first" not in second._widths


def test_very_narrow_navigation_labels_only_the_active_step(probe, monkeypatch):
    steps = StepBar(["Connect", "Record", "Train", "Drive"], widget_id="narrow-header")
    steps.active = 1
    tooltips = []
    monkeypatch.setattr(imgui, "is_item_hovered", lambda *args: True)
    monkeypatch.setattr(imgui, "set_tooltip", tooltips.append)
    view = probe.render(AppHeader("Session", steps=steps, participant=probe.participant), 500)
    buttons = [item for item in view.items if item.kind == "step"]
    assert [item.label for item in buttons] == ["1###step0", "2  Record###step1", "3###step2", "4###step3"]
    assert {"Connect", "Train", "Drive"} <= set(tooltips)
    pill, = [item for item in view.items if item.kind == "pill"]
    assert buttons[-1].hi[0] < pill.lo[0]


@pytest.mark.parametrize("state,recording,expected", [
    ("idle", False, ["IDLE"]),
    ("recording", True, ["RECORDING"]),
    ("predicting", False, ["PREDICTING"]),
    ("predicting", True, ["PREDICTING", "REC"]),
])
def test_recording_pill_follows_state_in_header(imgui_frame, monkeypatch, state, recording, expected):
    from myogestic.widgets.panels import app_header
    from myogestic.widgets.panels.recording import STATE_COLORS

    seen = []
    pill = app_header.status_pill

    def capture(label, color):
        pill(label, color)
        seen.append((label, tuple(color)))

    monkeypatch.setattr(app_header, "status_pill", capture)
    header = app_header.AppHeader("Test")
    imgui_frame(lambda: header.ui(Context(state=state, recording=recording)))
    assert [label for label, _ in seen] == expected
    if "REC" in expected:
        assert seen[-1][1] == tuple(STATE_COLORS["recording"])
