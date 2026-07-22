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

from myogestic.widgets.common import IDLE, SUCCESS, panel_header
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

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
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
        self.process.kill()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
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


_selected: dict[str, int] = {}  # label -> selected index
_MIN_COMBO_W = 90.0  # below this the dropdown drops to its own row (see row 1)
_popout_open: dict[tuple[str, str], bool] = {}  # (widget_id, proc_name) -> log popped out
# Autoscroll defaults ON for every (widget_id, proc_name); flipped off when the
# user clicks the autoscroll toggle so they can scroll back to inspect
# earlier output without being yanked back to the tail.
_autoscroll: dict[tuple[str, str], bool] = {}


# Delegated to widgets/_log_box.render_log — same implementation shared
# with pipeline_panel so the autoscroll + popout UX stays identical.


class ProcessLauncher:
    """Dropdown + Launch/Stop + scrollable log panel.

    Construct once with the process list, then call :meth:`ui` each frame.
    Multiple launchers can coexist — each gets unique ImGui IDs via
    ``widget_id`` (auto-generated from the process names when empty). The
    live subprocess registry is app-global, so processes are still killed on
    exit (``atexit`` + ``App.run`` cleanup) regardless of instance lifetime.
    """

    def __init__(
        self,
        processes: list[Process],
        *,
        widget_id: str = "",
        log_height: float = -1.0,
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
    log_height: float = -1.0,
) -> None:
    """Dropdown + Launch/Stop + scrollable log panel.

    Multiple launchers can coexist in the same UI —
    each gets unique ImGui IDs via the widget_id parameter.

    Parameters
    ----------
    processes
        List of (name, command) tuples.
    widget_id
        Unique ID for this launcher instance. Auto-generated if empty.
    log_height
        Height of the inline log panel in pixels. Pass ``<= 0``
        (default) to fill the remaining vertical space of the parent
        cell — matches the ImGui convention where ``-1`` means "fill
        available". When the log is popped out (see ``↗`` button), the
        inline log is replaced by a placeholder and the full log is
        rendered in a separate floating ImGui window.
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

    # Persistent selected index per launcher
    if widget_id not in _selected:
        _selected[widget_id] = 0

    # Render every popped-out log window owned by this launcher FIRST,
    # before the inline UI. This makes popouts independent of the dropdown
    # selection: once popped out, a log window stays up even when the user
    # switches the dropdown to a different process. (Codex flag: if the
    # popout were rendered from inside the "currently selected" branch,
    # changing selection would stop submitting the popout's Begin/End and
    # the window would silently disappear.)
    _render_open_popouts(widget_id)

    panel_header("PROCESS", fa.ICON_FA_TERMINAL)

    # Row 1: dropdown + Launch/Stop + popout + autoscroll. Keep every control
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
    cluster_w = launch_w + pop_w + auto_w + 2 * sp  # Launch + popout + autoscroll
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
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.6, 0.15, 0.15, 1.0))
        if imgui.button(f"Stop##{widget_id}"):
            state.stop()
        imgui.pop_style_color()
        imgui.set_item_tooltip(f"Kill the running '{selected_name}' process (SIGKILL).")
    else:
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.15, 0.4, 0.15, 1.0))
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
    autoscroll_on = _autoscroll.setdefault(pop_key, True)
    popped = _popout_open.get(pop_key, False)
    autoscroll_on, popped = render_log_buttons(
        f"{widget_id}_{selected_name}",
        autoscroll=autoscroll_on,
        popped_out=popped,
    )
    _autoscroll[pop_key] = autoscroll_on
    _popout_open[pop_key] = popped

    # Row 2: status text on its own line so it can never get cropped.
    if proc is not None and proc.poll() is None:
        imgui.text_colored(SUCCESS, f"Running (PID {proc.pid})")
    else:
        imgui.text_colored(IDLE, "Stopped")

    # Log area: inline if not popped, placeholder otherwise. The popout
    # itself is rendered at the top of the function (see _render_open_popouts).
    h = log_height if log_height > 0 else -1.0
    if _popout_open.get(pop_key, False):
        imgui.text_disabled(f"(log popped out — see '{selected_name} log' window)")
    else:
        render_log(
            f"{widget_id}_{selected_name}",
            state.log,
            height=h,
            autoscroll=_autoscroll.get(pop_key, True),
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
            autoscroll=_autoscroll.get((widget_id, name), True),
        )
        if not still_open:
            _popout_open[(widget_id, name)] = False
