"""FollowRun without a device or VHI: follow the target with a prediction slider.

Press Start, then move Prediction to match the control level. The saved take holds
both signals and the card scores it after Stop or the automatic deadline.

Run with:
    uv run python examples/panels/follow_run.py
"""

from imgui_bundle import imgui
from mne_lsl.lsl import local_clock

from myogestic import App, Context, Fr, Grid, Px
from myogestic.widgets import AppHeader, FollowRun
from myogestic.widgets.common import muted, panel_header

app = App("panel: follow_run")
header = AppHeader("FollowRun", show_state=True)
layout = Grid.areas("header\ninput\nfollow", row_height=[Px(52), Px(175), Fr(1)], bare=("header",))
follow = FollowRun(
    ["Fist", "Pinch"],
    drive=lambda index, level: None,  # This demo displays follow.target instead of driving a hand.
    on_record=app.start_recording,
    on_stop=app.stop_recording,
)
prediction = 0.0
app.cleanup_hooks.append(lambda _app: follow.stop(app.ctx))


@app.ui
def ui(ctx: Context) -> None:
    global prediction
    follow.sync(ctx)
    now = local_clock()
    target = follow.target
    with layout.area("header"):
        header.ui(ctx)
    with layout.area("input"):
        panel_header("Demo input")
        imgui.text_colored(muted(), "Control target")
        imgui.progress_bar(target[1] if target else 0.0, imgui.ImVec2(-1, 0))
        imgui.text_colored(muted(), "Prediction")
        imgui.set_next_item_width(-1)
        _, prediction = imgui.slider_float("##prediction", prediction, 0.0, 1.0, "%.2f")
    if target is not None:
        ctx.session.append_event("controls", [prediction], now, channel_names=["prediction"])
    with layout.area("follow"):
        follow.ui(ctx)


if __name__ == "__main__":
    app.run()
