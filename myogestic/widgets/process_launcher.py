"""Process launcher widget for @app.ui.

Usage:
    from myogestic.proc import process_launcher

    PROCESSES = [
        ("8ch EMG", ["mne_lsl_player", "--n_channels", "8", "--fs", "256"]),
        ("Webcam", [sys.executable, "-m", "myogestic.bridges.webcam", ...]),
    ]

    @app.ui
    def my_ui(ctx):
        process_launcher(PROCESSES)
"""

import atexit
import subprocess
import threading
from collections import deque

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets._common import panel_header
from myogestic.widgets._log_box import render_log, render_log_buttons, render_log_popout

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
_popout_open: dict[tuple[str, str], bool] = {}  # (uid, proc_name) -> log popped out
# Autoscroll defaults ON for every (uid, proc_name); flipped off when the
# user clicks the autoscroll toggle so they can scroll back to inspect
# earlier output without being yanked back to the tail.
_autoscroll: dict[tuple[str, str], bool] = {}


# Delegated to widgets/_log_box.render_log — same implementation shared
# with pipeline_panel so the autoscroll + popout UX stays identical.


def process_launcher(
    processes: list[Process],
    label: str = "",
    log_height: float = -1.0,
) -> None:
    """Dropdown + Launch/Stop + scrollable log panel.

    Multiple process_launcher() calls can coexist in the same UI —
    each gets unique ImGui IDs via the label parameter.

    Parameters
    ----------
    processes
        List of (name, command) tuples.
    label
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
    uid = label or "_".join(n for n, _ in processes)

    # Ensure state exists for all processes (keyed by (uid, name) so
    # two launchers with same-named but different-command processes don't collide).
    for name, cmd in processes:
        key = (uid, name)
        if key not in _procs:
            _procs[key] = _ProcState(name, cmd)

    names = [name for name, _ in processes]

    # Persistent selected index per launcher
    if uid not in _selected:
        _selected[uid] = 0

    # Render every popped-out log window owned by this launcher FIRST,
    # before the inline UI. This makes popouts independent of the dropdown
    # selection: once popped out, a log window stays up even when the user
    # switches the dropdown to a different process. (Codex flag: if the
    # popout were rendered from inside the "currently selected" branch,
    # changing selection would stop submitting the popout's Begin/End and
    # the window would silently disappear.)
    _render_open_popouts(uid)

    panel_header("PROCESS", fa.ICON_FA_TERMINAL)

    # Row 1: dropdown + Launch/Stop button + popout toggle + autoscroll toggle
    # (compact — status text would crop on narrow cells, so it gets its own
    # row below). Reserve the right side dynamically based on the actual
    # button widths at the current font scale, instead of a hardcoded fudge.
    style = imgui.get_style()
    launch_w = imgui.calc_text_size("Launch").x + 2 * style.frame_padding.x
    pop_w = (
        imgui.calc_text_size(fa.ICON_FA_UP_RIGHT_AND_DOWN_LEFT_FROM_CENTER).x
        + 2 * style.frame_padding.x
    )
    auto_w = (
        imgui.calc_text_size(fa.ICON_FA_ANGLES_DOWN).x + 2 * style.frame_padding.x
    )
    # 3 spacings: combo→launch, launch→pop, pop→autoscroll.
    reserved = launch_w + pop_w + auto_w + 3 * style.item_spacing.x
    imgui.push_item_width(-reserved)
    changed, new_idx = imgui.combo(f"##{uid}_select", _selected[uid], names)
    if changed:
        _selected[uid] = new_idx
    imgui.pop_item_width()

    selected_name = names[_selected[uid]]
    state = _procs[(uid, selected_name)]
    proc = state.process

    imgui.same_line()
    if proc is not None and proc.poll() is None:
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.6, 0.15, 0.15, 1.0))
        if imgui.button(f"Stop##{uid}"):
            state.stop()
        imgui.pop_style_color()
        imgui.set_item_tooltip(f"Kill the running '{selected_name}' process (SIGKILL).")
    else:
        imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.15, 0.4, 0.15, 1.0))
        if imgui.button(f"Launch##{uid}"):
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
    pop_key = (uid, selected_name)
    autoscroll_on = _autoscroll.setdefault(pop_key, True)
    popped = _popout_open.get(pop_key, False)
    autoscroll_on, popped = render_log_buttons(
        f"{uid}_{selected_name}",
        autoscroll=autoscroll_on,
        popped_out=popped,
    )
    _autoscroll[pop_key] = autoscroll_on
    _popout_open[pop_key] = popped

    # Row 2: status text on its own line so it can never get cropped.
    if proc is not None and proc.poll() is None:
        imgui.text_colored(
            imgui.ImVec4(0.2, 0.8, 0.2, 1.0),
            f"Running (PID {proc.pid})",
        )
    else:
        imgui.text_colored(imgui.ImVec4(0.5, 0.5, 0.5, 1.0), "Stopped")

    # Log area: inline if not popped, placeholder otherwise. The popout
    # itself is rendered at the top of the function (see _render_open_popouts).
    h = log_height if log_height > 0 else -1.0
    if _popout_open.get(pop_key, False):
        imgui.text_disabled(
            f"(log popped out — see '{selected_name} log' window)"
        )
    else:
        render_log(
            f"{uid}_{selected_name}",
            state.log,
            height=h,
            autoscroll=_autoscroll.get(pop_key, True),
        )


def _render_open_popouts(uid: str) -> None:
    """Render every popped-out log window owned by this launcher.

    Iterates ``_popout_open`` filtered to this ``uid`` and renders one
    floating ImGui window per ``True`` entry. Independent of which process
    is currently selected in the dropdown — once popped out, a log window
    stays open until the user closes it with the window's ``[x]``.
    """
    for (popped_uid, name), open_flag in list(_popout_open.items()):
        if popped_uid != uid or not open_flag:
            continue
        state = _procs.get((uid, name))
        if state is None:
            continue
        still_open = render_log_popout(
            f"{uid}_{name}",
            state.log,
            title=f"{name} log",
            autoscroll=_autoscroll.get((uid, name), True),
        )
        if not still_open:
            _popout_open[(uid, name)] = False
