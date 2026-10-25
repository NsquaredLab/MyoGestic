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
        key = (widget_id or "worker", "worker")
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
