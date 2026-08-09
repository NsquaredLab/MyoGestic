"""Two of the same widget in one cell must not share controls.

ImGui derives a control's identity from its label plus the enclosing id scope,
and a `Grid` cell is a single `begin_child` — so two panels using the same
literal ids inside one cell drive each other's sliders, popups and plots. The
obvious case is two force transducers, or two amplifiers, in one study.
"""

import pytest
from imgui_bundle import imgui

from myogestic import Stream
from myogestic.core import Context
from myogestic.sources import SyntheticSource
from myogestic.widgets import DevicePicker, PongTask, RecordButton, TrackingTask


def _ctx() -> Context:
    ctx = Context()
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=500.0), window_ms=200)
    assert stream.reconnect()
    stream.status = "connected"
    ctx.streams["emg"] = stream
    return ctx


def _with_ctx(widget, ctx) -> None:
    """Render a widget that reads the app context — most of them."""
    widget.ui(ctx)


@pytest.mark.parametrize(
    ("make", "render"),
    [
        pytest.param(
            lambda i: DevicePicker("emg", widget_id=f"p{i}"), _with_ctx, id="DevicePicker"
        ),
        pytest.param(
            lambda i: TrackingTask("emg", widget_id=f"t{i}"), _with_ctx, id="TrackingTask"
        ),
        pytest.param(
            lambda i: RecordButton(
                on_record=lambda: None, on_stop=lambda: None, widget_id=f"r{i}"
            ),
            _with_ctx,
            id="RecordButton",
        ),
        # `PongTask.ui` takes the command it draws, not the context: it reads no
        # stream and no session, so a `ctx` argument would imply otherwise.
        pytest.param(
            lambda i: PongTask(widget_id=f"g{i}"),
            lambda widget, _ctx: widget.ui(0.25),
            id="PongTask",
        ),
    ],
)
def test_two_instances_render_in_one_cell_without_colliding(make, render, implot_frame):
    """Both must draw, and the ID stack must come back balanced.

    An unbalanced stack surfaces as ``Missing PopID()`` at whatever ``end_child``
    the widgets happen to sit in — far from whichever one leaked it.
    """
    ctx = _ctx()
    first, second = make(1), make(2)

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(700, 500))
        render(first, ctx)
        render(second, ctx)
        imgui.end_child()

    implot_frame(draw)


def test_the_id_scope_defaults_to_something_distinguishing():
    """A caller that never thinks about it still gets a sensible scope."""
    assert DevicePicker("emg")._widget_id == "emg"
    assert TrackingTask("force")._widget_id == "force"
    assert PongTask()._widget_id == "pong"
    assert RecordButton(on_record=lambda: None, on_stop=lambda: None)._widget_id
