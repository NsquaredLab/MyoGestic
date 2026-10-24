"""Notification delivery, expiry, overlay rendering, and recording feedback."""

import contextlib
import threading
import time

import pytest
from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.core import App, Context


def test_notify_appends_and_mirrors_to_log(monkeypatch):
    ctx = Context()
    monkeypatch.setattr(time, "monotonic", lambda: 123.0)

    ctx.notify("Recording saved", "a.session.zip", "success")

    from myogestic.widgets.panels.notifications import Notification

    assert len(ctx.notifications) == 1
    notification = ctx.notifications[0]
    assert isinstance(notification, Notification)
    assert (notification.title, notification.detail, notification.kind, notification.created) == (
        "Recording saved", "a.session.zip", "success", 123.0
    )
    assert ctx.logs[-1].endswith("Recording saved — a.session.zip")
    ctx.notify("Ready")
    assert ctx.notifications[-1].kind == "info"
    assert ctx.logs[-1].endswith("Ready")
    assert "—" not in ctx.logs[-1]
    assert Context().notifications == []


def test_notify_rejects_unknown_kind():
    ctx = Context()
    with pytest.raises(ValueError, match="kind"):
        ctx.notify("Bad", kind="oops")
    assert ctx.notifications == []
    assert ctx.logs == []


@pytest.mark.parametrize("kind,lifetime", [("success", 6.0), ("info", 6.0), ("warning", 10.0)])
def test_expiry_by_kind(kind, lifetime, monkeypatch, imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    ctx = Context()
    ctx.notify("Temporary", kind=kind)
    ctx.notify("Persistent", kind="danger")
    now += lifetime - 0.01
    imgui_frame(lambda: render_notifications(ctx))
    assert [n.title for n in ctx.notifications] == ["Temporary", "Persistent"]
    now += 0.01
    imgui_frame(lambda: render_notifications(ctx))
    assert [n.title for n in ctx.notifications] == ["Persistent"]
    now += 1_000_000
    imgui_frame(lambda: render_notifications(ctx))
    assert [n.title for n in ctx.notifications] == ["Persistent"]


def test_at_most_three_visible(monkeypatch, imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    ctx = Context()
    for index in range(5):
        ctx.notify(f"Notice {index}")
    drawn = []
    original = imgui.text_unformatted

    def text(value):
        drawn.append(value)
        original(value)

    monkeypatch.setattr(imgui, "text_unformatted", text)
    imgui_frame(lambda: render_notifications(ctx))
    assert drawn == ["Notice 2", "Notice 3", "Notice 4"]
    assert [n.title for n in ctx.notifications] == drawn
    assert len(ctx.logs) == 5


def test_overlay_renders_headless(imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    ctx = Context()
    imgui_frame(lambda: render_notifications(ctx))
    for kind in ("success", "info", "warning", "danger"):
        ctx.notify("A completed step", "Details " * 25, kind)
        imgui_frame(lambda: render_notifications(ctx))


@pytest.mark.parametrize("browser", [False, True])
@pytest.mark.parametrize("docking", [False, True])
def test_app_renders_overlay_after_user_ui(browser, docking, monkeypatch, tmp_path, imgui_frame):
    from imgui_bundle import immapp

    from myogestic import _browser, core
    from myogestic.widgets.panels import notifications

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(_browser, "IS_BROWSER", browser)
    calls = []
    monkeypatch.setattr(_browser, "tick_all", lambda: calls.append("tick"))
    monkeypatch.setattr(core, "_collapse_glfw_monitor_spam", contextlib.nullcontext)
    monkeypatch.setattr(core.gc, "freeze", lambda: None)
    monkeypatch.setattr(core.gc, "set_threshold", lambda *args: None)
    app = App("notifications", theme=False, docking=docking)

    @app.ui
    def ui(ctx):
        calls.append("ui")
        ctx.notify("Raised by user UI")

    original = notifications.render_notifications

    def render(ctx):
        calls.append("overlay")
        assert ctx is app.ctx
        assert ctx.notifications[0].title == "Raised by user UI"
        original(ctx)

    monkeypatch.setattr(notifications, "render_notifications", render)
    monkeypatch.setattr(
        immapp, "run", lambda **kwargs: imgui_frame(kwargs["runner_params"].callbacks.show_gui)
    )
    app._gui_loop()
    assert calls == (["tick"] if browser else []) + ["ui", "overlay"]


def test_hover_pauses_expiry(monkeypatch, imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    now = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    ctx = Context()
    ctx.notify("Read me")
    imgui_frame(lambda: render_notifications(ctx))
    monkeypatch.setattr(imgui, "is_window_hovered", lambda *args: True)
    imgui.get_io().delta_time = 1.0
    for _ in range(10):
        now += 1.0
        imgui_frame(lambda: render_notifications(ctx))
    assert len(ctx.notifications) == 1
    monkeypatch.setattr(imgui, "is_window_hovered", lambda *args: False)
    now += 6.0
    imgui_frame(lambda: render_notifications(ctx))
    assert ctx.notifications == []


def test_dismiss_removes_only_that_toast(monkeypatch, imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    ctx = Context()
    for _ in range(2):
        ctx.notify("Same title", kind="danger")
    kept = ctx.notifications[1]
    clicked = iter((True, False))

    def click(label):
        assert fa.ICON_FA_XMARK in label
        return next(clicked)

    monkeypatch.setattr(imgui, "small_button", click)
    imgui_frame(lambda: render_notifications(ctx))
    assert len(ctx.notifications) == 1
    assert ctx.notifications[0] is kept
    assert len(ctx.logs) == 2


def test_notify_from_thread_while_rendering(monkeypatch, imgui_frame):
    from myogestic.widgets.panels.notifications import render_notifications

    ctx = Context()
    ctx.notify("Already visible")
    drawing = threading.Event()
    finished = threading.Event()
    errors = []

    def worker():
        try:
            assert drawing.wait(timeout=5)
            for index in range(200):
                ctx.notify(f"From worker {index}")
        except Exception as error:
            errors.append(error)
        finally:
            finished.set()

    original = imgui.text_unformatted

    def text(value):
        if value == "Already visible":
            drawing.set()
            assert finished.wait(timeout=5)
        original(value)

    monkeypatch.setattr(imgui, "text_unformatted", text)
    thread = threading.Thread(target=worker)
    thread.start()
    try:
        imgui_frame(lambda: render_notifications(ctx))
    finally:
        drawing.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not errors
    assert len(ctx.logs) == 201
    assert ctx.notifications[-1].title == "From worker 199"
    for _ in range(3):
        imgui_frame(lambda: render_notifications(ctx))
    assert [n.title for n in ctx.notifications] == [f"From worker {i}" for i in range(197, 200)]


def _wait_for_finalize(app, monkeypatch):
    from myogestic.widgets.training import session_manager

    finished = threading.Event()
    monkeypatch.setattr(session_manager, "add_recorded_session", lambda path: finished.set())
    app.stop_recording()
    assert finished.wait(timeout=10), "recording finalizer never finished"


def test_stop_recording_notifies_saved(tmp_path, monkeypatch):
    from tests.test_record_button import _recorded_app

    app, _ = _recorded_app(tmp_path)
    _wait_for_finalize(app, monkeypatch)

    saved = [n for n in app.ctx.notifications if n.title == "Recording saved"]
    assert len(saved) == 1
    assert saved[0].kind == "success"
    assert saved[0].detail == next((tmp_path / "sessions").glob("*.session.zip")).name


def test_stop_recording_notifies_pack_failure(tmp_path, monkeypatch):
    from tests.test_record_button import _recorded_app

    app, _ = _recorded_app(tmp_path)
    session = app.ctx.session

    def fail():
        raise OSError("Disk full")

    monkeypatch.setattr(session, "pack_to_zip", fail)
    _wait_for_finalize(app, monkeypatch)

    assert session.path.is_dir()
    assert len(app.ctx.notifications) == 1
    notification = app.ctx.notifications[0]
    assert (notification.title, notification.detail, notification.kind) == (
        "Recording not packed", "Disk full — folder kept", "danger"
    )
