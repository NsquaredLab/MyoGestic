"""Bridge lifecycle: the handle is only dropped when the kill actually landed.

Same incident as `TestTheProcessDotSaysTheState` in test_viz.py, one class over: a
process in an uninterruptible kernel wait ignores SIGKILL, and a `stop` that records
success anyway lets the next `start` stack a second process on a live one.
"""

import logging
import subprocess
import sys
import time

from myogestic.bridges import base
from myogestic.bridges.base import Bridge


def _bridge(process):
    bridge = Bridge("x", ["true"])
    bridge.process = process
    return bridge


class _Running:
    pid = 1234

    def poll(self):
        return None

    def terminate(self):
        pass


class _Unkillable(_Running):
    def __init__(self):
        self.kills = 0

    def kill(self):
        self.kills += 1

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired("bridge", timeout)


def test_a_bridge_that_survives_the_kill_is_still_held(caplog):
    """Neither signal landed, so nothing may claim it stopped."""
    proc = _Unkillable()
    bridge = _bridge(proc)
    with caplog.at_level(logging.WARNING, logger="myogestic.bridges"):
        bridge.stop()

    # No widget renders a bridge, so the log is the only place a human sees this.
    assert "ignored SIGKILL" in caplog.text, "a failed kill was reported nowhere"

    assert bridge.process is not None, "the handle was dropped on a live process"
    assert bridge.alive, "a process that ignored SIGKILL must still read as alive"
    assert bridge.status == "running", "it is still running, and that is what to say"
    assert proc.kills == 1, "SIGTERM timing out must escalate to SIGKILL"

    bridge.start()  # must refuse rather than spawn a second one
    assert bridge.process is proc, "start() stacked a process on a live one"

    bridge.stop()  # and stop stays usable, so the kill can be retried
    assert proc.kills == 2


def test_a_kill_that_lands_late_is_stopped_not_a_crash():
    """SIGKILL leaves -9, so no exit-code branch may creep into `status`."""
    bridge = _bridge(_Unkillable())
    bridge.stop()
    bridge.process.poll = lambda: -9  # it died, just not while stop was waiting

    assert bridge.status == "stopped"
    assert not bridge.alive


def test_a_bridge_that_dies_on_its_own_stops_reading_running(monkeypatch):
    """The stale-status bug: nothing called stop, so status must follow poll()."""
    proc = _Running()
    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: proc)
    bridge = Bridge("x", ["true"])
    bridge.start()
    assert bridge.status == "running"

    proc.poll = lambda: 1  # died, unasked
    assert bridge.status == "stopped", "a stored status kept saying 'running' here"
    assert not bridge.alive


def test_a_bridge_can_be_restarted_once_the_kill_lands(monkeypatch):
    """`start` refuses only while the held process is alive, not forever.

    The other half of the guard: keeping the handle after a kill that did not land
    must not wedge the bridge shut once it finally does.
    """
    bridge = _bridge(_Unkillable())
    bridge.stop()
    bridge.process.poll = lambda: -9  # the kill landed after all

    fresh = _Running()
    monkeypatch.setattr(base.subprocess, "Popen", lambda *a, **k: fresh)
    bridge.start()

    assert bridge.process is fresh, "start() refused a bridge whose process had died"
    assert bridge.status == "running"


def test_a_child_that_finished_its_job_is_not_a_failure():
    """A CustomBridge script that completes exits 0, and nobody calls `stop`.

    The stale-status bug the other way round: a vocabulary richer than the two states
    this class publishes has to guess, and a `code != 0` rule guessed "crashed" for a
    job well done. The exit code stays on `process`, which `stop` keeps, for whoever
    actually cares which it was.
    """
    bridge = Bridge("finisher", [sys.executable, "-c", "pass"])
    bridge.start()
    bridge.process.wait(timeout=10)

    assert bridge.status == "stopped", "a clean exit must not read as a failure"
    assert bridge.process.returncode == 0, "the handle is kept, so the code is still there"


def test_stop_without_start_is_a_no_op():
    """App.run() stops every registered bridge, including ones never started."""
    bridge = Bridge("x", ["true"])
    bridge.stop()  # must not raise: core.py only logs what this throws
    assert bridge.status == "stopped"
    assert not bridge.alive


def test_a_chatty_child_is_not_wedged_by_an_undrained_pipe(tmp_path):
    """The real defect (c): a PIPE nobody reads stalls the child at the buffer.

    Spawns a real subprocess, because a fake Popen cannot show this: the child blocks
    inside `write()` while `alive` still reports True.
    """
    done = tmp_path / "done"
    script = (
        "import sys, pathlib\n"
        "sys.stdout.write('x' * 400_000)\n"
        "sys.stderr.write('e' * 400_000)\n"
        f"pathlib.Path({str(done)!r}).write_text('done')\n"
    )
    bridge = Bridge("chatty", [sys.executable, "-c", script])
    bridge.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not done.exists():
            time.sleep(0.05)
        assert done.exists(), "the child never got past its own output (undrained pipe)"
    finally:
        bridge.stop()
    assert not bridge.alive
    assert bridge.status == "stopped"
