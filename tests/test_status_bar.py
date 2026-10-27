"""The session footer fits an unstyled bare row, including long file names."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic import Context, Fr, Grid, Px, _scale, _theme
from myogestic.widgets import StatusBar
from myogestic.widgets.common import IDLE, SUCCESS, muted, ui_px
from myogestic.widgets.panels import status_bar


@pytest.fixture
def probe(imgui_frame, monkeypatch):
    """Capture actual text rectangles, clipping, tooltips and the top rule."""
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    items, tooltips, rules = [], [], []
    text, rule = imgui.text_colored, status_bar.edge_rule

    def remember(color, label):
        text(color, label)
        draw = imgui.get_window_draw_list()
        items.append(
            SimpleNamespace(
                label=label,
                color=tuple(color),
                lo=tuple(imgui.get_item_rect_min()),
                hi=tuple(imgui.get_item_rect_max()),
                clip_lo=tuple(draw.get_clip_rect_min()),
                clip_hi=tuple(draw.get_clip_rect_max()),
            )
        )

    def edge(*, bottom):
        rules.append(bottom)
        rule(bottom=bottom)

    monkeypatch.setattr(imgui, "text_colored", remember)
    monkeypatch.setattr(imgui, "is_item_hovered", lambda: True)
    monkeypatch.setattr(imgui, "set_tooltip", tooltips.append)
    monkeypatch.setattr(status_bar, "edge_rule", edge)
    grid = Grid.areas("body\nstatus", row_height=[Fr(1), Px(26)], bare=("status",))
    ctx = Context(participant="P-014")

    def render(bar, width=1100, scale=1.0):
        monkeypatch.setattr(_scale, "_current", scale)
        _theme.apply_theme()
        imgui.get_style().scale_all_sizes(scale)
        imgui.get_style().font_scale_main = scale
        imgui.get_io().display_size = imgui.ImVec2(ui_px(width + 100), ui_px(300))
        bounds, scroll = [], []

        def draw():
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(ui_px(width), ui_px(250)))
            imgui.begin("status-probe", flags=imgui.WindowFlags_.no_title_bar)
            with grid.area("status"):
                origin, size = imgui.get_window_pos(), imgui.get_window_size()
                bounds[:] = [tuple(origin), (origin.x + size.x, origin.y + size.y)]
                bar.ui(ctx)
                scroll[:] = [imgui.get_scroll_max_x(), imgui.get_scroll_max_y()]
            imgui.end()

        for _ in range(4):
            items.clear()
            tooltips.clear()
            rules.clear()
            imgui_frame(draw)
        return SimpleNamespace(
            items=list(items),
            tooltips=list(tooltips),
            rules=list(rules),
            bounds=bounds,
            scroll=scroll,
        )

    return SimpleNamespace(render=render, ctx=ctx)


@pytest.mark.parametrize("connection", ["absent", "disconnected", "missing_info", "connected"])
@pytest.mark.parametrize("participant", ["", "P-014"])
def test_stream_participant_and_folder_text(probe, connection, participant):
    probe.ctx.participant = participant
    if connection != "absent":
        probe.ctx.streams["force"] = SimpleNamespace(
            name="force",
            status="connected" if connection != "disconnected" else "disconnected",
            info=None if connection == "missing_info" else SimpleNamespace(n_channels=8, fs=2048.0),
        )
    view = probe.render(StatusBar("force", sessions_dir=Path("captures")))
    source = "force · 8 ch / 2048 Hz" if connection == "connected" else "force · disconnected"
    text = f"{source} · {participant or 'No participant'} · {Path('captures') / participant}"
    assert [item.label for item in view.items] == [fa.ICON_FA_CIRCLE, text]
    assert view.items[0].color == tuple(SUCCESS if connection == "connected" else IDLE)
    assert view.items[1].color == tuple(muted())
    assert view.tooltips == [text]
    assert view.rules == [False]


@pytest.mark.parametrize(
    "model,saved,expected",
    [
        (None, "old.pkl", "Model: none"),
        (object(), "sessions/P-014/classifier.pkl", "Model: classifier.pkl"),
        (object(), None, "Model: fitted (not saved)"),
    ],
)
def test_model_text_is_optional_and_duck_typed(probe, model, saved, expected):
    pipeline = SimpleNamespace(model=model, last_saved_model=saved)
    view = probe.render(StatusBar(pipeline=pipeline))
    assert view.items[-1].label == expected
    assert view.tooltips[-1] == expected
    view = probe.render(StatusBar())
    assert len(view.items) == 2
    assert all("Model:" not in item.label for item in view.items)
    assert view.items[-1].label.startswith("emg · disconnected")


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("width", [640, 1100, 1800])
@pytest.mark.parametrize("with_pipeline", [False, True])
@pytest.mark.parametrize("long", [False, True])
def test_bare_footer_fits_in_light_theme(probe, width, scale, with_pipeline, long):
    participant = "long-participant-" * 24 if long else "P-014"
    probe.ctx.participant = participant
    saved = (
        "sessions/" + participant + "/" + ("long-model-" * 40 if long else "classifier") + ".pkl"
    )
    pipeline = SimpleNamespace(model=object(), last_saved_model=saved)
    view = probe.render(StatusBar(pipeline=pipeline if with_pipeline else None), width, scale)
    assert view.scroll == [0, 0]
    assert len(view.items) == (3 if with_pipeline else 2)
    assert len({item.lo[1] for item in view.items}) == 1
    for item in view.items:
        for axis in (0, 1):
            assert item.lo[axis] >= max(item.clip_lo[axis], view.bounds[0][axis]) - 1
            assert item.hi[axis] <= min(item.clip_hi[axis], view.bounds[1][axis]) + 1
    for left, right in zip(view.items, view.items[1:], strict=False):
        assert left.hi[0] < right.lo[0]
    if with_pipeline:
        right = view.bounds[1][0] - imgui.get_style().window_padding.x
        assert abs(view.items[-1].hi[0] - right) <= 1
    if long:
        detail = f"emg · disconnected · {participant} · {Path('sessions') / participant}"
        assert view.items[1].label.endswith("…")
        assert view.tooltips[0] == detail
        if with_pipeline:
            assert view.items[-1].label.endswith("…")
            assert view.tooltips[-1] == f"Model: {Path(saved).name}"
