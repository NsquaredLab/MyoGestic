import gc
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from myogestic._platform import _register_assets_folder, _try_set_macos_dock_icon
from myogestic.session import Session
from myogestic.stream import Stream

log = logging.getLogger("myogestic")


class AppState(StrEnum):
    """Core app-state values. Extensions (e.g. myogestic.ml.PipelineState) add more.

    `Context.state` is a bare `str` so extensions can introduce their own states
    without subclassing. Each module validates transitions within its own
    namespace only.
    """
    IDLE = "idle"
    RECORDING = "recording"


TRANSITIONS: dict[str, set[str]] = {
    AppState.IDLE: {AppState.RECORDING},
    AppState.RECORDING: {AppState.IDLE},
}


# --- Docking integration (experimental) -----------------------------------
#
# `popout_panel(...)` (myogestic.widgets.popout) appends `DockableWindow`
# objects here. `App._gui_loop` drains the list into the active
# `RunnerParams.docking_params.dockable_windows` before launching the
# render loop. List + flag live at module scope so the widget can resolve
# the active App lazily without circular imports.

_pending_popouts: list[Any] = []  # list[hello_imgui.DockableWindow]
_active_app: "App | None" = None


def can_transition(current: str, target: str) -> bool:
    """Core-level transition check (idle ↔ recording).

    Extensions validate their own transitions independently - this function
    returns False for non-core states rather than raising.
    """
    return target in TRANSITIONS.get(current, set())


@dataclass
class Context:
    """Shared state all threads read/write. Extensions may add own fields
    dynamically on the owning `App`, but `Context` itself is core-only."""
    streams: dict[str, Stream] = field(default_factory=dict)
    bridges: dict[str, Any] = field(default_factory=dict)
    state: str = AppState.IDLE
    session: Session | None = None
    class_names: list[str] = field(default_factory=list)
    current_label: int = -1
    status_message: str = ""
    logs: list[str] = field(default_factory=list)

    def log(self, message: str, max_lines: int = 500) -> None:
        """Append a one-line app event for the `log_panel` widget.

        Bounded to `max_lines` (oldest dropped). Use for high-level events -
        recording saved, training start/done, model load - not per-frame
        chatter. Safe to call from any thread (list.append/pop are GIL-atomic).
        """
        from time import strftime
        line = f"[{strftime('%H:%M:%S')}] {message}"
        self.logs.append(line)
        if len(self.logs) > max_lines:
            del self.logs[0 : len(self.logs) - max_lines]


class App:
    """Top-level application object. Owns the GUI loop, the `Context`,
    the run-loop lifecycle hooks, and the recording state machine.

    Construct one per process. Register streams via `app.streams(...)`,
    register your UI via `@app.ui`, then call `app.run()`. Optional
    extensions like `Pipeline(app)` register themselves via
    `app.before_run_hooks` / `app.cleanup_hooks` - user code rarely
    needs to touch those lists directly.

    Args:
        name: Window title. Also used for the persisted ImGui state
            file (``.imgui_state/<name>.ini``) when ``docking=True``.
        theme: Apply MyoGestic's built-in ImGui theme. Set ``False`` to
            keep the Dear ImGui defaults.
        docking: Experimental - enable ImGui docking + multi-viewport
            so panels registered via ``app.popout(...)`` become tearable
            DockableWindows. macOS Retina viewport sizing of detached
            windows can be wrong on initial draw; treat as experimental.
        ui_scale: Global UI zoom factor - scales the font and imgui's style
            metrics (padding, spacing, rounding). ``None`` uses
            ``$MYOGESTIC_UI_SCALE`` then ``1.0``. The env var, if set,
            overrides this - a per-machine display fix beats the example's
            value. Clamped to ``[0.5, 2.0]``. Has no effect when ``theme=False``.
    """

    def __init__(self, name: str, theme: bool = True, docking: bool = False,
                 ui_scale: float | None = None):
        self.name = name
        self.ctx = Context()
        self._ui_fn: Callable[[Context], None] | None = None
        self._theme_enabled = theme
        self._ui_scale = ui_scale
        # Experimental: when True, _gui_loop enables ImGui docking +
        # multi-viewport so widgets wrapped in `popout_panel(...)` become
        # tearable, dock-able windows. macOS Metal/Retina caveats apply
        # - see the README "Status" note.
        self._docking = docking
        self._running = False
        # Extensions register here (e.g. myogestic.ml.attach_pipeline).
        # before_run: after streams.start, before _gui_loop, on main thread.
        # cleanup: in finally - always runs, each wrapped in try/except.
        self.before_run_hooks: list[Callable[[App], None]] = []
        self.cleanup_hooks: list[Callable[[App], None]] = []
        self._popout_specs: list[tuple[str, Callable[[], None], bool, bool, bool | None]] = []

    def streams(self, *streams: Stream) -> None:
        """Register one or more streams with the app.

        Each stream is keyed by its ``name`` into ``ctx.streams``.
        Acquisition threads start when ``app.run()`` is called, not at
        registration time. Calling this with the same name overwrites
        the previous registration - typically you call it once at setup.

        Args:
            *streams: One or more :class:`Stream` instances.
        """
        for s in streams:
            self.ctx.streams[s.name] = s

    def bridges(self, *bridges: Any) -> None:
        """Register one or more Bridge subprocesses with the app.

        Bridges run in their own process (webcam, ultrasound, depth
        camera, …) and publish an LSL clock stream the main app
        subscribes to. The cockpit's ``process_launcher`` widget shows
        their start/stop state. Mirrors :meth:`streams` exactly: each
        bridge is keyed by its ``.name`` into ``ctx.bridges``; calling
        with the same name overwrites the previous registration.

        Args:
            *bridges: One or more bridge instances - each must expose a
                ``.name`` attribute and a Bridge-like interface
                (``.start()``, ``.stop()``).
        """
        for b in bridges:
            self.ctx.bridges[b.name] = b

    def ui(self, fn: Callable[[Context], None]) -> Callable[[Context], None]:
        """Decorator. Register the render callback.

        @app.ui
        def my_ui(ctx):
            imgui.text(f"State: {ctx.state}")
        """
        self._ui_fn = fn
        return fn

    def popout(
        self,
        title: str,
        gui_fn: Callable[[], None],
        *,
        default_open: bool = True,
        can_be_closed: bool = True,
        remember_is_visible: bool | None = None,
    ) -> None:
        """Register a dockable window before `run()`.

        This is the preferred path for examples/apps using `App(docking=True)`.
        It gives Hello ImGui the complete DockableWindow list before launch,
        instead of discovering windows on the first render frame.
        """
        self._popout_specs = [spec for spec in self._popout_specs if spec[0] != title]
        self._popout_specs.append(
            (title, gui_fn, default_open, can_be_closed, remember_is_visible)
        )

    # --- Recording (universal; ML is in myogestic.ml) ---

    def start_recording(self, base_path: str = "sessions") -> None:
        """Begin recording all connected streams to a new session.

        Creates ``base_path/<timestamp>/`` and starts appending each
        stream's data + timestamps to per-stream Zarr arrays. Streams
        whose ``info`` is still ``None`` (disconnected) are skipped -
        they won't be retroactively captured if they connect later in
        the recording. Refuses to start if ``ctx.state`` isn't
        ``"idle"``; updates ``ctx.status_message`` with the result.

        Args:
            base_path: Directory where the per-session subfolder is
                created. Defaults to ``"sessions"``.
        """
        if not can_transition(self.ctx.state, AppState.RECORDING):
            self.ctx.status_message = (
                f"Cannot start recording: state is {self.ctx.state!r}, expected 'idle'."
            )
            return
        # Only record from streams that have connected - a stream with info=None
        # has no zarr schema and would fail on append. Disconnected streams are
        # skipped; if they connect later they won't be retroactively captured.
        self.ctx.state = AppState.RECORDING
        self.ctx.session = Session(base_path=base_path)
        n_ready = 0
        for name, stream in self.ctx.streams.items():
            if stream.info is None:
                continue
            self.ctx.session.init_stream(name, stream.info)
            stream.attach_session(self.ctx.session)
            n_ready += 1
        if n_ready == 0:
            self.ctx.status_message = "No connected streams to record"
            self.ctx.log("Recording: no connected streams")
        else:
            self.ctx.status_message = f"Recording to {self.ctx.session.path}"
            self.ctx.log(f"Recording → {self.ctx.session.path}")

    def stop_recording(self) -> None:
        """Stop the active recording and pack the session to a ``.session.zip``.

        Finalises the per-stream Zarr arrays, writes the label track to
        ``labels.json``, and kicks off a daemon thread that packs the
        session folder into a single ``<timestamp>.session.zip`` archive
        (the original folder is kept until the pack succeeds). Refuses
        to stop if ``ctx.state`` isn't ``"recording"``.
        """
        if not can_transition(self.ctx.state, AppState.IDLE):
            self.ctx.status_message = (
                f"Cannot stop recording: state is {self.ctx.state!r}, expected 'recording'."
            )
            return
        self.ctx.state = AppState.IDLE
        # Detach every stream *before* finalising/packing the session.
        # detach_session() waits for any in-flight append on the acquire
        # thread, so the daemon pack thread below can clear the Zarr stores
        # without racing the acquire loop (was: KeyError mid-append).
        for stream in self.ctx.streams.values():
            stream.detach_session()
        if self.ctx.session is not None:
            session = self.ctx.session
            session.save_meta(self.name, class_names=self.ctx.class_names or None)
            n = len(session.label_track)
            self.ctx.status_message = f"Saved {n} labels - finalizing…"

            # Pack session folder → .session.zip in a daemon thread so the
            # UI stays responsive during finalization. Register with
            # session_manager only after pack succeeds.
            import threading

            def _finalize() -> None:
                try:
                    zip_path = session.pack_to_zip()
                    self.ctx.status_message = f"Saved {n} labels"
                    self.ctx.log(f"Session saved → {zip_path}")
                    from myogestic.widgets.session_manager import add_recorded_session
                    add_recorded_session(str(zip_path))
                    log.info("packed session to %s", zip_path)
                except Exception as e:
                    log.exception("pack_to_zip failed: %s", e)
                    self.ctx.status_message = f"Pack failed: {e} - folder kept"
                    self.ctx.log(f"Pack failed: {e} - folder kept at {session.path}")
                    # Fall back: register the folder so user doesn't lose it
                    try:
                        from myogestic.widgets.session_manager import (
                            add_recorded_session,
                        )
                        add_recorded_session(str(session.path))
                    except Exception:
                        pass

            threading.Thread(target=_finalize, daemon=True).start()

    # --- Run ---

    def run(
        self,
        mode: str = "gui",
        window_size: tuple[int, int] = (1280, 800),
        fullscreen: bool = False,
    ) -> None:
        """Blocking entry point.

        Call tree (top → bottom = runtime order):

            App.run()
            ├─ 1. Stream.start()          per stream → daemon acquire thread
            ├─ 2. before_run_hooks(app)  extensions register here
            │    └─ e.g. myogestic.ml.attach_pipeline → starts predict thread
            ├─ 3. self._gui_loop()  ← main thread, BLOCKS
            │    └─ immapp.run → per frame: self._ui_fn(self.ctx)  (your @app.ui)
            └─ 4. [finally] cleanup - always runs, even on startup failure
                 ├─ cleanup_hooks(app)   each wrapped in try/except
                 ├─ Stream.stop()         per stream
                 ├─ Bridge.stop()         per bridge
                 └─ process_launcher._cleanup_all()

        Core has only idle ↔ recording. `myogestic.ml.attach_pipeline(app)` adds
        training/predicting states + their transition methods.
        """
        if self._running:
            raise RuntimeError("App.run() is not re-entrant")
        if mode not in ("gui", "headless"):
            raise ValueError(
                f"App.run(mode={mode!r}) - unknown mode. "
                "Supported: 'gui', 'headless'."
            )
        self._running = True

        log.info("run() - streams=%s mode=%s", list(self.ctx.streams), mode)

        from myogestic._browser import IS_BROWSER

        def _do_cleanup() -> None:
            log.info("run() - cleanup")
            for hook in self.cleanup_hooks:
                try:
                    hook(self)
                except Exception as e:
                    log.exception("cleanup hook %r failed: %s", hook, e)
            for stream in self.ctx.streams.values():
                try:
                    stream.stop()
                except Exception as e:
                    log.exception("stream stop failed: %s", e)
            for bridge in self.ctx.bridges.values():
                try:
                    bridge.stop()
                except Exception as e:
                    log.exception("bridge stop failed: %s", e)
            try:
                from myogestic.widgets.process_launcher import _cleanup_all
                _cleanup_all()
            except Exception as e:
                log.exception("process cleanup failed: %s", e)
            self._running = False

        try:
            for name, stream in self.ctx.streams.items():
                log.info("  start stream %r", name)
                stream.start()

            for hook in self.before_run_hooks:
                log.info("  before_run hook: %s", getattr(hook, "__qualname__", hook))
                hook(self)

            log.info("  enter %s loop", mode)
            if mode == "gui":
                self._gui_loop(window_size=window_size, fullscreen=fullscreen)
            elif mode == "headless":
                self._headless_loop()
        except BaseException:
            # Always tear down on error - half-started state must not
            # leak (orphan threads on desktop, orphan scheduler entries
            # in browser).
            _do_cleanup()
            raise

        if IS_BROWSER:
            # In Pyodide, immapp.run returns immediately and the
            # browser's requestAnimationFrame drives the GUI from here.
            # Skipping cleanup keeps the app alive after this function
            # returns; tab unload is the implicit teardown.
            return

        _do_cleanup()

    def _gui_loop(
        self,
        window_size: tuple[int, int] = (1280, 800),
        fullscreen: bool = False,
    ) -> None:
        """Main thread. Calls user's @app.ui function each frame."""
        from imgui_bundle import hello_imgui, imgui, immapp

        if self._ui_fn is None and not (self._docking and self._popout_specs):
            raise RuntimeError(
                "No UI function registered. Use @app.ui to define one:\n\n"
                "    @app.ui\n"
                "    def my_ui(ctx):\n"
                "        imgui.text('hello')\n"
            )

        gc.collect()
        gc.freeze()
        gc.set_threshold(50_000, 10, 10)

        ui_fn = self._ui_fn or (lambda _ctx: None)

        # In browser (Pyodide) mode the per-frame scheduler drives every
        # long-lived loop (Stream acquisition, Output sending, Pipeline
        # predict) - no threads, no asyncio. The desktop path uses real
        # daemon threads and the tick is a no-op.
        from myogestic._browser import IS_BROWSER, tick_all
        if IS_BROWSER:
            def gui_callback() -> None:
                tick_all()
                ui_fn(self.ctx)
        else:
            def gui_callback() -> None:
                ui_fn(self.ctx)

        runner_params = hello_imgui.RunnerParams()
        runner_params.fps_idling.enable_idling = False
        runner_params.callbacks.show_gui = gui_callback
        runner_params.app_window_params.window_title = self.name
        runner_params.app_window_params.window_geometry.size = window_size
        if fullscreen:
            # Maximise to the monitor work area (keeps menu bar / dock visible),
            # rather than exclusive fullscreen. This is what users typically
            # mean by "fullscreen" for screenshot captures of an example.
            runner_params.app_window_params.window_geometry.full_screen_mode = (
                hello_imgui.FullScreenMode.full_monitor_work_area
            )

        # Tell HelloImGui where to find our shipped assets - used by the
        # `app_logo` widget (myogestic_logo.png) and by HelloImGui's window
        # icon convention (app_settings/icon.png, picked up automatically on
        # Linux/Windows).
        _register_assets_folder(hello_imgui)
        # macOS dock icon must be set AFTER the backend (GLFW) creates the
        # NSApplication - otherwise GLFW resets it during init. post_init
        # runs at the right moment.
        if sys.platform == "darwin":
            runner_params.callbacks.post_init = _try_set_macos_dock_icon

        import os
        os.makedirs(".imgui_state", exist_ok=True)
        runner_params.ini_filename_use_app_window_title = False
        runner_params.ini_filename = f".imgui_state/{self.name.replace(' ', '_')}.ini"

        if self._theme_enabled:
            from myogestic.theme import apply_theme, load_fonts, set_ui_scale
            set_ui_scale(self._ui_scale)  # consumed by load_fonts / apply_theme below
            runner_params.callbacks.default_icon_font = hello_imgui.DefaultIconFont.font_awesome6
            runner_params.callbacks.load_additional_fonts = load_fonts
            runner_params.callbacks.setup_imgui_style = apply_theme

        # --- Experimental: docking + multi-viewport ---
        if self._docking:
            # Wrap the user's @app.ui inside a full-screen dock space so Grid
            # layouts keep working (rendered into the central node) AND any
            # popout_panel(...) windows dock around them.
            params = runner_params.imgui_window_params
            params.default_imgui_window_type = (
                hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
            )
            # Drain anything popout_panel() registered before run() (the
            # widget can also be called from inside @app.ui - that path
            # registers on the first frame, see widgets/popout.py).
            from myogestic.widgets.popout import _make_dockable_window

            dp = hello_imgui.DockingParams()
            dockable_windows = [
                _make_dockable_window(
                    title,
                    gui_fn,
                    default_open,
                    can_be_closed,
                    remember_is_visible,
                )
                for (
                    title,
                    gui_fn,
                    default_open,
                    can_be_closed,
                    remember_is_visible,
                ) in self._popout_specs
            ]
            dockable_windows.extend(_pending_popouts)
            dp.dockable_windows = dockable_windows
            runner_params.docking_params = dp

            # Enable the actual docking + tear-off-into-OS-window behavior.
            # `setup_imgui_style` runs after ImGui::CreateContext, which is
            # when ConfigFlags can be safely set.
            prev_setup = runner_params.callbacks.setup_imgui_style

            def _setup_with_docking() -> None:
                if prev_setup is not None:
                    prev_setup()
                io = imgui.get_io()
                io.config_flags |= imgui.ConfigFlags_.docking_enable.value
                io.config_flags |= imgui.ConfigFlags_.viewports_enable.value

            runner_params.callbacks.setup_imgui_style = _setup_with_docking

        global _active_app
        _active_app = self
        # Exposed so widgets/popout.py can patch the live dockable_windows
        # list when popout_panel() is called from inside @app.ui.
        self._runner_params = runner_params
        try:
            addons = immapp.AddOnsParams()
            addons.with_implot = True
            addons.with_implot3d = True

            immapp.run(runner_params=runner_params, add_ons_params=addons)
        finally:
            _active_app = None
            self._runner_params = None
            _pending_popouts.clear()
            # Drop the per-title registration cache so a subsequent App in
            # the same process (with overlapping panel titles) re-registers
            # cleanly. Without this, the second App's popout_panel calls
            # would short-circuit and never queue their DockableWindows.
            from myogestic.widgets.popout import _reset_registry
            _reset_registry()

    def _headless_loop(self) -> None:
        """No UI. Blocks until KeyboardInterrupt."""
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
