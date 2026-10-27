"""Public process actions work before any launcher UI is rendered."""

import sys

import pytest

from myogestic.widgets.panels import process_launcher as module


@pytest.mark.parametrize("widget_id", ["", "custom-launcher"])
def test_launch_and_stop_use_the_same_registry_as_running(monkeypatch, widget_id):
    monkeypatch.setattr(module, "_procs", {})
    launcher = module.ProcessLauncher(
        [("worker", [sys.executable, "-c", "import time; time.sleep(60)"])],
        widget_id=widget_id,
    )
    try:
        assert not launcher.running("worker")
        launcher.launch("worker")
        assert launcher.running("worker")
        key = (launcher._widget_id, "worker")
        process = module._procs[key].process
        launcher.launch("worker")
        assert module._procs[key].process is process
    finally:
        launcher.stop("worker")
    assert not launcher.running("worker")
    assert process.poll() is not None


def test_unknown_process_actions_raise_a_useful_error():
    launcher = module.ProcessLauncher([])
    for action in (launcher.launch, launcher.stop):
        with pytest.raises(ValueError, match="missing"):
            action("missing")


class _Process:
    pid = 4212
    stdout = ()
    returncode = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_elapsed_time_freezes_on_exit_and_resets_on_relaunch(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: _Process())
    monkeypatch.setattr(module.threading.Thread, "start", lambda self: None)
    state = module._ProcState("worker", ["worker"])
    state.start()
    clock[0] = 52.0
    assert state.elapsed == 42.0
    state.process.returncode = 1
    assert state.elapsed == 42.0
    clock[0] = 90.0
    assert state.elapsed == 42.0
    state.start()
    assert state.elapsed == 0.0
    clock[0] = 93.0
    state.stop()
    clock[0] = 100.0
    assert state.elapsed == 3.0


def test_failed_spawn_is_reported_and_retry_clears_it(monkeypatch):
    state = module._ProcState("worker", ["missing-command"])

    def fail(*a, **k):
        raise FileNotFoundError("missing-command")

    monkeypatch.setattr(module.subprocess, "Popen", fail)
    with pytest.raises(FileNotFoundError):
        state.start()
    tone, detail = module._status_of(state)
    assert tone is module.DANGER
    assert "missing-command" in detail
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: _Process())
    monkeypatch.setattr(module.threading.Thread, "start", lambda self: None)
    state.start()
    assert module._status_of(state)[0] is module.SUCCESS
    state.stop()


def test_default_launcher_instances_do_not_share_processes(monkeypatch):
    monkeypatch.setattr(module, "_procs", {})
    first = module.ProcessLauncher([("worker", ["first"])])
    second = module.ProcessLauncher([("worker", ["second"])])
    assert first._process_state("worker") is not second._process_state("worker")


@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("status", ["stopped", "running", "failed", "stopping"])
def test_process_states_fit_narrow_cells(imgui_frame, monkeypatch, scale, dark, status):
    from contextlib import contextmanager

    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets import common

    monkeypatch.setattr(module, "_procs", {})
    monkeypatch.setattr(module, "_selected", {})
    monkeypatch.setattr(module, "_popout_open", {})
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: dark)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    launcher = module.ProcessLauncher([("worker", ["worker"])], widget_id="states")
    state = launcher._process_state("worker")
    if status != "stopped":
        state.process = _Process()
        state._started_at = 10.0
        state._ended_at = 13.0 if status == "failed" else None
        state._kill_wanted = status == "stopping"
        if status == "failed":
            state.process.returncode = 1
    monkeypatch.setattr(module, "monotonic", lambda: 52.0, raising=False)
    rows, texts, primary, buttons, headers, combos = [], [], [], [], [], []
    bounds = {}
    tooltips = []
    monkeypatch.setattr(imgui, "set_item_tooltip", tooltips.append)

    @contextmanager
    def row(tone=None, **kwargs):
        rows.append(tone)
        with common.tinted_row(tone, **kwargs) as width:
            yield width

    def mono(label, *args):
        texts.append(label)
        common.mono_text(label, *args)
        assert imgui.get_item_rect_max().x <= bounds["right"] + 1

    def forward(label, size=(0, 0)):
        primary.append(label.split("##")[0])
        return common.primary_button(label, size)

    real_button, real_small, real_combo = imgui.button, imgui.small_button, imgui.combo

    def button(label, *args):
        result = real_button(label, *args)
        buttons.append((label.split("##")[0], imgui.get_item_rect_min().y))
        assert imgui.get_item_rect_max().x <= bounds["right"] + 1
        return result

    def small(label):
        result = real_small(label)
        buttons.append((label.split("##")[0], imgui.get_item_rect_min().y))
        assert imgui.get_item_rect_max().x <= bounds["right"] + 1
        return result

    def combo(*args):
        result = real_combo(*args)
        combos.append((imgui.get_item_rect_min().y, imgui.get_item_rect_size().x))
        assert imgui.get_item_rect_max().x == pytest.approx(bounds["right"], abs=1)
        return result

    def header(*args, **kwargs):
        headers.append(kwargs["status"])
        common.panel_header(*args, **kwargs)

    monkeypatch.setattr(module, "tinted_row", row, raising=False)
    monkeypatch.setattr(module, "mono_text", mono, raising=False)
    monkeypatch.setattr(module, "primary_button", forward, raising=False)
    monkeypatch.setattr(module, "panel_header", header)
    monkeypatch.setattr(imgui, "button", button)
    monkeypatch.setattr(imgui, "small_button", small)
    monkeypatch.setattr(imgui, "combo", combo)

    def draw():
        imgui.begin_child("narrow-process", imgui.ImVec2(320, 380))
        bounds["right"] = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        launcher.ui()
        imgui.end_child()

    imgui_frame(draw)
    assert buttons[0][1] < combos[0][0], "the log action belongs in the header"
    if status == "stopped":
        assert primary == ["Launch"]
        assert headers == [common.IDLE]
    else:
        tone = {"running": common.SUCCESS, "failed": common.DANGER, "stopping": common.WARNING}[
            status
        ]
        assert rows == [tone] and headers == [tone]
        if status == "failed":
            assert primary == ["Launch again"]
            assert "Show output" in [label for label, _ in buttons]
            assert "exited with code 1 · 0:03" in tooltips
        else:
            assert "Stop" in [label for label, _ in buttons]
            assert primary == []
            expected = "running" if status == "running" else "stop pending"
            assert f"{expected} · PID 4212 · 0:42" in tooltips
    state.process = None


def test_actions_launch_stop_retry_and_keep_output_open(imgui_frame, monkeypatch):
    from imgui_bundle import imgui

    monkeypatch.setattr(module, "_procs", {})
    monkeypatch.setattr(module, "_selected", {})
    monkeypatch.setattr(module, "_popout_open", {})
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: _Process())
    monkeypatch.setattr(module.threading.Thread, "start", lambda self: None)
    launcher = module.ProcessLauncher(
        [("worker", ["worker"]), ("other", ["other"])], widget_id="actions"
    )
    action = ["Launch"]
    real = imgui.button

    def click(label, *args):
        real(label, *args)
        return label.split("##")[0] == action[0]

    monkeypatch.setattr(imgui, "button", click)
    popped = []
    monkeypatch.setattr(
        module, "render_log_popout", lambda wid, *a, **k: popped.append(wid) or True
    )
    imgui_frame(launcher.ui)
    assert launcher.running("worker")
    action[0] = "Stop"
    imgui_frame(launcher.ui)
    assert not launcher.running("worker")
    action[0] = "Launch"
    imgui_frame(launcher.ui)
    state = launcher._process_state("worker")
    state.process.returncode = 1
    action[0] = "Show output"
    imgui_frame(launcher.ui)
    assert module._popout_open[("actions", "worker")]
    action[0] = "Launch again"
    imgui_frame(launcher.ui)
    assert launcher.running("worker")
    module._selected["actions"] = 1
    action[0] = ""
    imgui_frame(launcher.ui)
    assert popped[-1] == "actions_worker"
    launcher.stop("worker")


def test_output_reader_freezes_duration_without_rendering_and_ignores_old_runs(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    state = module._ProcState("worker", ["worker"])
    state._started_at = 10.0
    first = _Process()
    first.returncode = 1
    first.stdout = ["failed\n"]
    state.process = first
    clock[0] = 13.0
    state._read_output(first)
    clock[0] = 52.0
    assert state.elapsed == 3.0
    assert list(state.log) == ["failed", "[exited with code 1]"]
    state.process = _Process()
    state._started_at = 52.0
    state._ended_at = None
    state.log.clear()
    state._read_output(first)
    assert not state.log
    clock[0] = 54.0
    assert state.elapsed == 2.0
