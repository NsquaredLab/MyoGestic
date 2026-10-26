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
from time import monotonic
from uuid import uuid4

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import mono_font
from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    _truncate_to_width,
    destructive_button,
    mono_text,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)
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
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._launch_error: str | None = None

    @property
    def elapsed(self) -> float:
        """Seconds since launch, frozen when the process exits or is stopped."""
        if self._started_at is None:
            return 0.0
        if self._ended_at is None and not self.alive:
            self._ended_at = monotonic()
        end = self._ended_at if self._ended_at is not None else monotonic()
        return max(0.0, end - self._started_at)

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        self._kill_wanted = False
        self.log.clear()
        self.log.append(f"$ {' '.join(self.command)}")
        self._launch_error = None
        self._started_at = monotonic()
        self._ended_at = None
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                shell=False,
            )
        except Exception as error:
            self.process = None
            self._ended_at = monotonic()
            self._launch_error = str(error)
            self.log.append(f"[launch failed: {error}]")
            raise
        # Capture this launch so an old reader cannot finish a later run's timer.
        self._reader_thread = threading.Thread(
            target=self._read_output, args=(self.process,), daemon=True,
        )
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
        self._ended_at = monotonic()
        self.log.append("[process stopped]")
        self.process = None

    def _read_output(self, proc: subprocess.Popen) -> None:
        """Read stdout/stderr and freeze the timer when this launch exits."""
        if proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                if self.process is proc:
                    self.log.append(line.rstrip("\n"))
        except (ValueError, OSError):
            pass  # pipe closed
        code = proc.wait()
        if self.process is proc:
            if self._ended_at is None:
                self._ended_at = monotonic()
            self.log.append(f"[exited with code {code}]")


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
    Launch again", which is how four VHI processes ended up alive at once.

    The string is what the header's tooltip says. Colour alone cannot be the whole signal:
    a dot is small, and red against green is the one pair a reader may not be able to tell
    apart at all.
    """
    if state._launch_error is not None:
        return DANGER, f"Launch failed: {state._launch_error}"
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


_selected: dict[str, int] = {}  # widget_id -> selected index
_popout_open: dict[tuple[str, str], bool] = {}  # (widget_id, proc_name) -> log popped out

# Delegated to widgets/_log_box.render_log — same implementation shared
# with pipeline_panel so the popout UX stays identical.


class ProcessLauncher:
    """Select a process, launch it, and read its running or failed state.

    Shows PID and elapsed time while running, with output in a popout.
    Failed processes can be relaunched.

    Construct once with the process list, then call [`ui`][] each frame.
    Multiple launchers can coexist — each gets unique ImGui IDs via
    ``widget_id`` (unique per instance when empty). The
    live subprocess registry is app-global, so processes are still killed on
    exit (``atexit`` + ``App.run`` cleanup) regardless of instance lifetime.

    Parameters
    ----------
    processes
        The launchable processes, as ``(name, argv)`` tuples.
    widget_id
        ImGui id scope for this launcher. A unique instance ID is generated
        when empty; an explicit ID can preserve state across reconstruction.
    log_height
        Height in pixels of an **optional** inline log. ``<= 0`` (the default)
        draws no inline log at all: state and elapsed time stay visible and output
        is one click away in the ``↗`` popout window, which can be moved, resized
        and left open while the dropdown moves to another process. Pass a
        positive height to get a strip under the controls instead.

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
        self._widget_id = widget_id or f"process_launcher:{uuid4().hex}"
        self._log_height = log_height

    def ui(self) -> None:
        """Render the launcher. Call once per frame inside ``@app.ui``."""
        _render_process_launcher(self._processes, self._widget_id, self._log_height)

    def launch(self, name: str) -> None:
        """Start a configured process, unless it is already running.

        Parameters
        ----------
        name
            The process name from the configured ``(name, argv)`` tuples.

        Raises
        ------
        ValueError
            If ``name`` is not configured for this launcher.
        """
        self._process_state(name).start()

    def stop(self, name: str) -> None:
        """Stop a process started by this launcher.

        Parameters
        ----------
        name
            The process name from the configured ``(name, argv)`` tuples.

        Raises
        ------
        ValueError
            If ``name`` is not configured for this launcher.
        """
        self._process_state(name).stop()

    def _process_state(self, name: str) -> _ProcState:
        """Resolve the same per-launcher state used by the UI and ``running``."""
        for configured, command in self._processes:
            if configured == name:
                key = (self._widget_id, name)
                if key not in _procs:
                    _procs[key] = _ProcState(name, command)
                return _procs[key]
        raise ValueError(f"No process named {name!r}; use a configured process name.")

    def running(self, name: str) -> bool:
        """Whether the process called ``name`` is alive **because this panel started it**.

        For an app that has something to do once a target is up — bind a control map to a
        target it just launched, enable a control that needs it — rather than asking the
        operator to press a second button confirming the press they already made.

        Says nothing about a process started outside the app: the registry only holds what
        this panel launched, so a target that was already running reads ``False``. Treat it
        as "I started this", not as "this is reachable"; the target's own handshake is what
        answers reachability.

        Parameters
        ----------
        name
            The process name, as given in the ``(name, argv)`` tuple.
        """
        state = _procs.get((self._widget_id, name))
        return state is not None and state.alive


def _render_process_launcher(
    processes: list[Process],
    widget_id: str = "",
    log_height: float = 0.0,
) -> None:
    """Render a full-width selector, state row and the next process action."""
    if not processes:
        panel_header("Process", fa.ICON_FA_TERMINAL, status=IDLE)
        imgui.text_wrapped("Add a process to the launcher to enable Launch.")
        return

    widget_id = widget_id or "_".join(n for n, _ in processes)
    for name, cmd in processes:
        key = (widget_id, name)
        if key not in _procs:
            _procs[key] = _ProcState(name, cmd)
    names = [name for name, _ in processes]
    _render_open_popouts(widget_id)
    _selected[widget_id] = min(_selected.get(widget_id, 0), len(names) - 1)
    name = names[_selected[widget_id]]
    dot, detail = _status_of(_procs[(widget_id, name)])

    style = imgui.get_style()
    pop_key = (widget_id, name)
    popped = _popout_open.get(pop_key, False)
    icon = (fa.ICON_FA_DOWN_LEFT_AND_UP_RIGHT_TO_CENTER if popped
            else fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER)
    action_w = imgui.calc_text_size(icon).x + 2 * style.frame_padding.x
    panel_header("Process", fa.ICON_FA_TERMINAL, status=dot,
                 reserve=action_w + style.item_spacing.x)
    imgui.set_item_tooltip(detail)
    imgui.same_line()
    imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(
        0.0, imgui.get_content_region_avail().x - action_w,
    ))
    _popout_open[pop_key] = render_log_buttons(f"{widget_id}_{name}", popped_out=popped)

    imgui.set_next_item_width(-1.0)
    changed, index = imgui.combo(f"##{widget_id}_select", _selected[widget_id], names)
    if changed:
        _selected[widget_id] = index
    name = names[_selected[widget_id]]
    state = _procs[(widget_id, name)]
    pop_key = (widget_id, name)
    tone, detail = _status_of(state)
    seconds = int(state.elapsed)
    duration = f"{seconds // 60}:{seconds % 60:02d}"
    if state.alive:
        status = "stop pending" if state._kill_wanted else "running"
        text = f"{status} · PID {state.process.pid} · {duration}"
        if _render_state_row(text, tone, f"Stop##{widget_id}", destructive=True):
            state.stop()
    else:
        failed = tone is DANGER
        if failed:
            text = (f"launch failed · {state._launch_error}" if state._launch_error else
                    f"exited with code {state.process.poll()} · {duration}")
            if _render_state_row(text, DANGER, f"Show output##{widget_id}"):
                _popout_open[pop_key] = True
        label = "Launch again" if failed else "Launch"
        if primary_button(f"{label}##{widget_id}", (-1.0, 0.0)):
            try:
                state.start()
            except Exception:
                pass  # start records the error for the state row and output log
        imgui.set_item_tooltip(f"Launch {name} and capture its output.")

    if log_height > 0 and not _popout_open.get(pop_key, False):
        render_log(f"{widget_id}_{name}", state.log, height=ui_px(log_height))


def _render_state_row(
    text: str, tone: imgui.ImVec4, action: str, *, destructive: bool = False,
) -> bool:
    """Keep a mono state and its action on one line, with full detail on hover."""
    style = imgui.get_style()
    action_w = imgui.calc_text_size(action.split("##")[0]).x + 2 * style.frame_padding.x
    with tinted_row(tone) as width:
        left = imgui.get_cursor_pos_x()
        budget = max(0.0, width - action_w - style.item_spacing.x)
        imgui.push_font(mono_font(), style.font_size_base)
        label = text
        if imgui.calc_text_size(label).x > budget:
            label = _truncate_to_width(label, budget - imgui.calc_text_size("…").x) + "…"
        imgui.pop_font()
        imgui.align_text_to_frame_padding()
        mono_text(label)
        imgui.set_item_tooltip(text)
        imgui.same_line()
        imgui.set_cursor_pos_x(left + max(0.0, width - action_w))
        if destructive:
            return destructive_button(action, tooltip="Stop the process (SIGKILL).")
        return imgui.button(action)


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
