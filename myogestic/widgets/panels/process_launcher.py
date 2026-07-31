"""Process launcher widget for @app.ui.

Usage:
    from myogestic.widgets import ProcessLauncher

    PROCESSES = [
        ("8ch EMG", ["mne_lsl_player", "--n_channels", "8", "--fs", "256"]),
        ("Webcam", [sys.executable, "-m", "myogestic.bridges.webcam", ...]),
    ]

    launcher = ProcessLauncher(PROCESSES)

    @app.ui
    def my_ui(ctx):
        launcher.ui()
"""

import atexit
import subprocess
import threading
from collections import deque

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import DANGER, IDLE, SUCCESS, WARNING, panel_header
from myogestic.widgets.panels.log_box import (
    render_log,
    render_log_buttons,
    render_log_popout,
)

# --- Per-process state ---

type Process = tuple[str, list[str]]  # (label, argv)

_procs: dict[tuple[str, str], "_ProcState"] = {}  # (launcher_uid, proc_name) → state


def _cleanup_all() -> None:
    """Kill all managed processes on exit."""
    for state in _procs.values():
        if state.process is not None and state.process.poll() is None:
            state.process.kill()
            try:
                state.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass


atexit.register(_cleanup_all)


class _ProcState:
    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None  # type: ignore[type-arg]
        self.log: deque[str] = deque(maxlen=200)
        self._reader_thread: threading.Thread | None = None
        #: A Stop was pressed for the process currently held. The one piece of state the
        #: dot cannot infer: after a kill that has not landed yet, `poll()` says "running"
        #: and after one that has, it says "died with a non-zero code" — neither of which
        #: is what happened. Reset by `start`, so it always describes the live process.
        self._kill_wanted = False

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        self._kill_wanted = False
        self.log.clear()
        self.log.append(f"$ {' '.join(self.command)}")
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            shell=False,
        )
        # Background thread reads stdout line by line
        self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        if self.process is None:
            return
        # Use SIGKILL directly — SIGTERM causes crash in some apps
        # (e.g. Godot mono's C# runtime fails during shutdown)
        self._kill_wanted = True
        self.process.kill()
        try:
            # Short on purpose: this runs on the render thread, from the click. A signal a
            # process *can* receive is reaped in single-digit milliseconds, so anything
            # still here at 200 ms is not going to answer this frame either — it is in an
            # uninterruptible wait, and the three seconds this used to spend were three
            # seconds of frozen window in exactly the situation where the window freezing
            # is the complaint.
            self.process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            # SIGKILL does not land on a process blocked in an uninterruptible kernel
            # wait, and a wedged network driver is enough to put it there — VHI's LSL
            # resolver thread sits in exactly that call. So keep holding it rather than
            # forgetting it: dropping the handle reported "Not running", `alive` went
            # False, and the next Launch spawned another VHI on top of one that was
            # still alive and still resolving LSL streams. Four of them stacked up that
            # way, each adding the multicast traffic that keeps the driver wedged.
            self.log.append("[still alive — SIGKILL did not land; press Stop to retry]")
            return
        self.log.append("[process stopped]")
        self.process = None

    def _read_output(self) -> None:
        """Read stdout/stderr line by line into the log deque."""
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self.log.append(line.rstrip("\n"))
        except (ValueError, OSError):
            pass  # pipe closed
        # Check exit code
        if proc.poll() is not None:
            self.log.append(f"[exited with code {proc.returncode}]")


def _status_of(state: _ProcState) -> tuple[imgui.ImVec4, str]:
    """The header dot's colour for a process, and the detail behind it.

    Mostly read off bookkeeping that already exists: `_ProcState.stop` clears ``process``
    once the kill lands, so a process you killed is indistinguishable from one never
    started and therefore *cannot* be mistaken for one that died. Only a process still
    holding a finished `Popen` exited on its own, and only then does a non-zero code mean
    something went wrong.

    The exception, and the one thing `_kill_wanted` is for, is a kill that has **not**
    landed — a process in an uninterruptible wait ignores SIGKILL. `poll()` reports that
    one as plainly running, so the dot went green and the tooltip named its PID for a
    process the user had just pressed Stop on. That reads as "nothing happened, press
    Launch again", which is how four renderers ended up alive at once.

    The string is what the header's tooltip says. Colour alone cannot be the whole signal:
    a dot is small, and red against green is the one pair a reader may not be able to tell
    apart at all.
    """
    proc = state.process
    if proc is None:
        return IDLE, "Not running."
    code = proc.poll()
    if code is None:
        if state._kill_wanted:
            return WARNING, (
                f"Stop was pressed, but PID {proc.pid} has not died — it is ignoring "
                f"SIGKILL, which means it is stuck in the kernel. Launch will refuse "
                f"until it goes, rather than start a second one alongside it."
            )
        return SUCCESS, f"Running (PID {proc.pid})."
    if state._kill_wanted:
        # The kill landed, just not while `stop` was waiting. A killed process carries a
        # non-zero code, and reporting that as a crash would turn Stop into a red dot.
        return IDLE, "Stopped."
    if code == 0:
        return IDLE, "Exited cleanly."
    return DANGER, f"Exited on its own with code {code}."


_selected: dict[str, int] = {}  # label -> selected index
_MIN_COMBO_W = 90.0  # below this the dropdown drops to its own row (see row 1)
_popout_open: dict[tuple[str, str], bool] = {}  # (widget_id, proc_name) -> log popped out

# Delegated to widgets/_log_box.render_log — same implementation shared
# with pipeline_panel so the popout UX stays identical.


class ProcessLauncher:
    """Dropdown + Launch/Stop + scrollable log panel.

    Construct once with the process list, then call [`ui`][] each frame.
    Multiple launchers can coexist — each gets unique ImGui IDs via
    ``widget_id`` (auto-generated from the process names when empty). The
    live subprocess registry is app-global, so processes are still killed on
    exit (``atexit`` + ``App.run`` cleanup) regardless of instance lifetime.

    Examples
    --------
    >>> import sys
    >>> from myogestic.widgets import ProcessLauncher
    >>> launcher = ProcessLauncher([("Worker", [sys.executable, "worker.py"])])
    >>> launcher.ui()
    """

    def __init__(
        self,
        processes: list[Process],
        *,
        widget_id: str = "",
        log_height: float = 0.0,
    ) -> None:
        self._processes = processes
        self._widget_id = widget_id
        self._log_height = log_height

    def ui(self) -> None:
        """Render the launcher. Call once per frame inside ``@app.ui``."""
        _render_process_launcher(self._processes, self._widget_id, self._log_height)


def _render_process_launcher(
    processes: list[Process],
    widget_id: str = "",
    log_height: float = 0.0,
) -> None:
    """Dropdown + Launch/Stop, and the log one click away.

    Two rows: a header whose coloured dot is the selected process's state, then the
    dropdown, Launch/Stop and the log's own buttons. Deliberately compact — it used to
    print the log inline into whatever height its cell had, and spend a whole row on the
    word "Stopped".

    Multiple launchers can coexist in the same UI —
    each gets unique ImGui IDs via the widget_id parameter.

    Parameters
    ----------
    processes
        List of (name, command) tuples.
    widget_id
        Unique ID for this launcher instance. Auto-generated if empty.
    log_height
        Height in pixels of an **optional** inline log. ``<= 0`` (the default) draws no
        inline log at all: the state is the header's dot and the output is one click away
        in the ``↗`` popout window, which can be moved, resized, and left open while the
        dropdown moves to another process. Pass a positive height to get the old strip
        back under the controls.
    """
    if not processes:
        return

    # Auto-generate label from process names
    widget_id = widget_id or "_".join(n for n, _ in processes)

    # Ensure state exists for all processes (keyed by (widget_id, name) so
    # two launchers with same-named but different-command processes don't collide).
    for name, cmd in processes:
        key = (widget_id, name)
        if key not in _procs:
            _procs[key] = _ProcState(name, cmd)

    names = [name for name, _ in processes]

    # Render every popped-out log window owned by this launcher FIRST,
    # before the inline UI. This makes popouts independent of the dropdown
    # selection: once popped out, a log window stays up even when the user
    # switches the dropdown to a different process. (Codex flag: if the
    # popout were rendered from inside the "currently selected" branch,
    # changing selection would stop submitting the popout's Begin/End and
    # the window would silently disappear.)
    _render_open_popouts(widget_id)

    # The dot needs the selected process, which is chosen below — so read the selection
    # first and draw the header with it, rather than splitting the header in two.
    if widget_id not in _selected:
        _selected[widget_id] = 0
    _selected[widget_id] = min(_selected[widget_id], len(names) - 1)
    dot, detail = _status_of(_procs[(widget_id, names[_selected[widget_id]])])
    panel_header("PROCESS", fa.ICON_FA_TERMINAL, status=dot)
    # The detail the removed status row used to carry. On the header, because that is what
    # the dot is attached to, and because colour on its own is not a readable answer.
    imgui.set_item_tooltip(detail)

    # Row 1: dropdown + Launch/Stop + popout. Keep every control
    # reachable when the cell is narrow: the dropdown shares the row with the
    # button cluster only while a usable dropdown (>= _MIN_COMBO_W) still fits;
    # otherwise it takes its own full-width row and the buttons drop below it
    # instead of being pushed off the right edge. Status text gets its own row.
    style = imgui.get_style()
    sp = style.item_spacing.x
    launch_w = imgui.calc_text_size("Launch").x + 2 * style.frame_padding.x
    pop_w = (
        imgui.calc_text_size(fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER).x
        + 2 * style.frame_padding.x
    )
    auto_w = imgui.calc_text_size(fa.ICON_FA_ANGLES_DOWN).x + 2 * style.frame_padding.x
    cluster_w = launch_w + pop_w + auto_w + 2 * sp  # Launch + popout
    # ponytail: below ~cluster_w the icon cluster itself would clip; a third
    # row would fix it but no real cell is that narrow.
    inline = imgui.get_content_region_avail().x >= _MIN_COMBO_W + sp + cluster_w
    imgui.push_item_width(-(cluster_w + sp) if inline else -1.0)
    changed, new_idx = imgui.combo(f"##{widget_id}_select", _selected[widget_id], names)
    if changed:
        _selected[widget_id] = new_idx
    imgui.pop_item_width()

    selected_name = names[_selected[widget_id]]
    state = _procs[(widget_id, selected_name)]
    proc = state.process

    if inline:
        imgui.same_line()
    if proc is not None and proc.poll() is None:
        imgui.push_style_color(imgui.Col_.button, DANGER)
        if imgui.button(f"Stop##{widget_id}"):
            state.stop()
        imgui.pop_style_color()
        imgui.set_item_tooltip(f"Kill the running '{selected_name}' process (SIGKILL).")
    else:
        imgui.push_style_color(imgui.Col_.button, SUCCESS)
        if imgui.button(f"Launch##{widget_id}"):
            try:
                state.start()
            except Exception as e:
                state.log.append(f"[launch failed: {e}]")
        imgui.pop_style_color()
        imgui.set_item_tooltip(
            f"Spawn '{selected_name}' as a subprocess and stream its stdout into the log."
        )

    # Autoscroll + popout toggles — shared widgets/_log_box helpers, so the
    # buttons look + feel identical to the model panel's log controls.
    imgui.same_line()
    pop_key = (widget_id, selected_name)
    popped = render_log_buttons(
        f"{widget_id}_{selected_name}", popped_out=_popout_open.get(pop_key, False)
    )
    _popout_open[pop_key] = popped

    # No status row and no log: the state is the dot in the header, and the log is one click
    # away in its own window. This panel is two rows on purpose — it was filling whatever
    # height its cell gave it with output nobody had asked to see.
    if log_height > 0 and not _popout_open.get(pop_key, False):
        # Opt in to an inline log by asking for a height. `<= 0` no longer means "fill the
        # cell"; it means "do not draw one".
        render_log(
            f"{widget_id}_{selected_name}",
            state.log,
            height=log_height,
        )


def _render_open_popouts(widget_id: str) -> None:
    """Render every popped-out log window owned by this launcher.

    Iterates ``_popout_open`` filtered to this ``widget_id`` and renders one
    floating ImGui window per ``True`` entry. Independent of which process
    is currently selected in the dropdown — once popped out, a log window
    stays open until the user closes it with the window's ``[x]``.
    """
    for (popped_uid, name), open_flag in list(_popout_open.items()):
        if popped_uid != widget_id or not open_flag:
            continue
        state = _procs.get((widget_id, name))
        if state is None:
            continue
        still_open = render_log_popout(
            f"{widget_id}_{name}",
            state.log,
            title=f"{name} log",
        )
        if not still_open:
            _popout_open[(widget_id, name)] = False
