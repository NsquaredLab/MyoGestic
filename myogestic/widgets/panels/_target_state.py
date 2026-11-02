"""What a `TargetPanel` row says, worked out without a window.

Kept apart from the drawing so every state can be checked headless: the row's tone,
its state in words, its values, and the one action it offers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from myogestic.widgets.common import DANGER, IDLE, SUCCESS, WARNING

if TYPE_CHECKING:
    from imgui_bundle import imgui

    from myogestic.widgets.panels.process_launcher import _ProcState


@dataclass
class Row:
    """What one row remembers between frames, beyond its process and its connector."""

    #: Connect was pressed: launch if the attempt it forced finds nothing.
    pending: bool = False
    #: The last press could not launch anything: nothing answered, or nothing to start.
    unlaunched: bool = False
    #: Why ``launcher()`` refused when last asked; empty while it can launch.
    refusal: str = ""
    #: Stop was pressed while an attempt was in flight: disconnect once it finishes.
    disconnect: bool = False
    #: The exited process whose bus was already dropped, so it is dropped only once.
    dropped: object = None


@dataclass(frozen=True)
class View:
    """One frame of a row: tint and dot, state in words, mono values, action."""

    tone: imgui.ImVec4
    words: str
    detail: str
    action: str
    enabled: bool = True


def _clock(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def view(
    row: Row,
    process: _ProcState | None,
    *,
    bindable: bool,
    connected: bool,
    error: Exception | None,
) -> View:
    """The row as drawn this frame.

    Parameters
    ----------
    row
        The row's memory.
    process
        The process this panel launched for the row, or ``None`` before it launched one.
    bindable
        Whether the row has a connector, so its forward action is Connect, not Launch.
    connected
        Whether that connector is bound.
    error
        The connector's last error: a target answered and refused.
    """
    forward = "Connect" if bindable else "Launch"
    if process is not None and process._launch_error is not None:
        return View(DANGER, "Launch failed", process._launch_error, "Retry")
    if process is not None and process.alive:
        values = f"PID {process.process.pid} · {_clock(process.elapsed)}"
        if process._kill_wanted:
            return View(WARNING, "Stopping", values, "Stop")
        if bindable and not connected:
            return View(WARNING, "Waiting for it to answer", values, "Stop")
        return View(SUCCESS, "Connected" if bindable else "Running", values, "Stop")
    if bindable and connected:
        return View(SUCCESS, "Connected", "", "")  # someone else started it: not ours to stop
    if process is not None and process.process is not None and not process._kill_wanted:
        code = process.process.poll()
        if code not in (None, 0):
            again = "Connect" if bindable else "Launch again"
            return View(DANGER, "Exited", f"code {code} · {_clock(process.elapsed)}", again)
    if bindable and error is not None:
        return View(DANGER, "Connection failed", str(error), "Retry")
    if row.pending:
        return View(WARNING, "Looking for one running", "", forward, enabled=False)
    if row.unlaunched:
        words = "Nothing answered" if bindable else "Cannot launch"
        return View(DANGER, words, "cannot launch here", "Retry")
    return View(IDLE, "Not running", "cannot launch here" if row.refusal else "", forward)
