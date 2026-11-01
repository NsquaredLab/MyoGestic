"""Record and its Stop share one slot, and a take reads its seconds left at a glance.

The Stop that ended a take used to be a small default-grey button at the right edge
of the recording row, so the second click of every take had to hunt for a target
the first one never needed. Now the whole row is the action, in exactly the
rectangle Record had. While a timed take runs, the row's glyph is the whole
seconds still to go, which is what an operator says aloud to the participant.
"""

from types import SimpleNamespace

import pytest
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import Context
from myogestic.widgets import RecordButton, RecordingControls
from myogestic.widgets.common import (
    DANGER,
    ON_PRIMARY_TEXT,
    RECORD_FILL,
    SUCCESS,
    WARNING,
    muted,
)
from myogestic.widgets.panels import _recording_controls as module
from myogestic.widgets.panels.recording import TakeStatus


@pytest.fixture
def seen(monkeypatch):
    """Record the action buttons' rectangles and every coloured or plain text."""
    out = SimpleNamespace(rects={}, colored=[], plain=[], click=None)
    button, colored, plain = imgui.button, imgui.text_colored, imgui.text_unformatted

    def spy_button(label, *args):
        result = button(label, *args)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        out.rects[label] = (lo.x, lo.y, hi.x, hi.y)
        return result or (out.click is not None and label.endswith(out.click))

    def spy_colored(tone, text):
        out.colored.append((tuple(tone), text))
        colored(tone, text)

    def spy_plain(text, *args):
        out.plain.append(text)
        plain(text, *args)

    monkeypatch.setattr(imgui, "button", spy_button)
    monkeypatch.setattr(imgui, "text_colored", spy_colored)
    monkeypatch.setattr(imgui, "text_unformatted", spy_plain)
    return out


def _timed(now, calls, ctx, warmup=0.0):
    def start():
        ctx.state, ctx.recording = "recording", True
        ctx.session = SimpleNamespace(add_label=lambda _: None)

    def stop():
        calls.append("stop")
        ctx.state, ctx.recording = "idle", False

    controls = RecordingControls(
        ["Rest", "Fist"],
        on_record=start,
        on_stop=stop,
        timed=True,
        take_lengths=(5.0,),
        warmups=(warmup,),
    )
    controls._machine._clock = lambda: now[0]
    return controls


def _ctx():
    ctx = Context(participant="P-001", current_label=0)
    ctx.streams["emg"] = SimpleNamespace(status="connected", info=object())
    return ctx


def test_stop_takes_the_rectangle_record_had_and_ends_the_take(imgui_frame, seen):
    now, calls, ctx = [0.0], [], _ctx()
    controls = _timed(now, calls, ctx)

    imgui_frame(lambda: controls.ui(ctx))
    (record_label,) = [k for k in seen.rects if k.endswith("##rec_btn")]
    record = seen.rects.pop(record_label)
    controls._start(ctx)
    now[0] = 3.2
    imgui_frame(lambda: controls.ui(ctx))
    assert controls.take.phase == "recording"
    assert seen.rects["##rec_btn"] == pytest.approx(record)

    seen.click = "##rec_btn"
    imgui_frame(lambda: controls.ui(ctx))
    assert calls == ["stop"]
    assert controls.take.phase == "saved"


@pytest.mark.parametrize(
    ("status", "glyph"),
    [
        (TakeStatus(phase="warmup", timed=True, length_s=5.0, warmup_left_s=2.4), ("3", WARNING)),
        (TakeStatus(phase="recording", timed=True, elapsed_s=3.2, length_s=5.0), ("2", DANGER)),
        (TakeStatus(phase="recording", elapsed_s=3.2), (fa.ICON_FA_CIRCLE, DANGER)),
        (
            TakeStatus(phase="saved", elapsed_s=5.0, length_s=5.0),
            (fa.ICON_FA_CIRCLE_CHECK, SUCCESS),
        ),
    ],
    ids=["warm-up", "timed", "open-ended", "saved"],
)
def test_the_glyph_counts_whole_seconds_left(imgui_frame, seen, status, glyph):
    """`2` with 1.8 s to go: the number to say aloud, rounded the way a countdown is."""
    controls = RecordingControls(
        ["Rest"],
        on_record=lambda: None,
        on_stop=lambda: None,
        timed=True,
        take_lengths=(5.0,),
        warmups=(3.0,),
    )
    controls._machine.status = status
    imgui_frame(lambda: module._render_recording_controls(_ctx(), controls))
    text, tone = glyph
    assert (tuple(tone), text) in seen.colored


@pytest.mark.parametrize(
    ("elapsed", "detail"),
    [(5.02, "0:05.0 recorded"), (3.2, "stopped early · 0:03.2 of 0:05.0")],
)
def test_saved_reads_like_the_rows_before_it(imgui_frame, seen, elapsed, detail):
    """White title, mono numbers underneath; green is the row and the check, not the text."""
    controls = RecordingControls(["Rest"], on_record=lambda: None, on_stop=lambda: None)
    controls._machine.status = TakeStatus(
        phase="saved", timed=True, gesture="Rest", elapsed_s=elapsed, length_s=5.0
    )
    imgui_frame(lambda: module._render_recording_controls(_ctx(), controls))
    assert "Saved · Rest" in seen.plain
    assert (tuple(muted()), detail) in seen.colored
    assert [text for tone, text in seen.colored if tone == tuple(SUCCESS)] == [
        fa.ICON_FA_CIRCLE_CHECK
    ]


def test_record_button_stop_takes_the_record_rectangle(imgui_frame, seen):
    ctx = Context()
    recorder = RecordButton(on_record=lambda: None, on_stop=lambda: None)
    imgui_frame(lambda: recorder.ui(ctx))
    (record_label,) = [k for k in seen.rects if k.endswith("Record")]
    ctx.state, ctx.recording = "recording", True
    imgui_frame(lambda: recorder.ui(ctx))
    assert seen.rects["##record_stop"] == pytest.approx(seen.rects[record_label])


def _contrast(a, b):
    """WCAG contrast ratio of two colours."""

    def luminance(c):
        channels = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in (c.x, c.y, c.z)
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_record_fill_keeps_white_text_readable():
    assert _contrast(ON_PRIMARY_TEXT, RECORD_FILL) >= 4.5


@pytest.mark.parametrize("dark", [True, False], ids=["dark", "light"])
@pytest.mark.parametrize("warmup", [True, False], ids=["warm-up", "recording"])
def test_the_count_reads_on_its_own_tint_in_both_themes(imgui_frame, monkeypatch, dark, warmup):
    """3:1, the large-text floor, against the very row the digit sits on.

    The light warm-up is held at 2.9:1 instead: it is simpetru-figstyle's darkest
    orange, chosen over an off-palette one. A lighter colour slipping in fails here.
    """
    from myogestic import _theme
    from myogestic.widgets.common import _tinted

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    surface = _tinted(WARNING if warmup else DANGER)
    floor = 2.9 if warmup and not dark else 3.0
    assert _contrast(module._count_color(warmup), surface) >= floor
