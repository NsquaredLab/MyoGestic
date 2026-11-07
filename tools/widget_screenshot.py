"""Self-capturing widget screenshots for the docs site.

Usage:
    uv run python tools/widget_screenshot.py <widget_name> [--out PATH]
    uv run python tools/widget_screenshot.py --all
    uv run python tools/widget_screenshot.py --examples
    uv run python tools/widget_screenshot.py --example examples/start_here/myocontrol.py

For each widget in the registry below, this builds a minimal App with
ONLY that widget rendered, waits ~3 s for the window to settle, captures
the window via Quartz + screencapture, saves to ``docs/images/widgets/``
and exits cleanly.

Some widgets need fixture data (a synthetic Stream for signal_viewer, a
fake sessions/ folder for session_manager, etc.) - those fixtures are
created on the fly in ``WIDGETS`` below.

This script is independent from the docs build. Run it whenever the
widget look-and-feel changes; commit the resulting PNGs.
"""

from __future__ import annotations

import argparse
import os
import runpy
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import chdir
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "images" / "widgets"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# Self-capture helper
# ─────────────────────────────────────────────────────────────────────


def _self_capture_after(
    seconds: float, output_path: Path, *, window_only: bool = False
) -> None:
    """In a background thread, wait ``seconds``, find this process's
    main GUI window via Quartz, screencapture it, then close at the next
    frame boundary so a signal cannot interrupt an ImGui push/pop pair.
    """

    def _run() -> None:
        from imgui_bundle import hello_imgui

        def finish() -> None:
            hello_imgui.get_runner_params().app_shall_exit = True

        time.sleep(seconds)
        try:
            import Quartz  # type: ignore
        except Exception as e:
            print(f"[capture] Quartz import failed: {e}", file=sys.stderr)
            finish()
            return
        my_pid = os.getpid()
        wid = None
        for w in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        ):
            if w.get("kCGWindowOwnerPID") == my_pid and w.get("kCGWindowLayer") == 0:
                wid = w.get("kCGWindowNumber")
                break
        if wid is None:
            print(f"[capture] no window found for pid {my_pid}", file=sys.stderr)
            finish()
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "screencapture", *(["-o"] if window_only else []), "-l", str(wid),
                "-t", "png", "-x", str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[capture] screencapture failed: {result.stderr}", file=sys.stderr)
        else:
            print(f"[capture] saved {output_path} ({output_path.stat().st_size} B)")
        time.sleep(0.5)
        finish()

    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────
# Widget renderers
# Each function builds a minimal App+UI showing one widget, then runs.
# ─────────────────────────────────────────────────────────────────────

# Per-widget window sizes (logical pixels). Tuned so each widget fills
# the window at its natural rendered height with no empty padding.
SIZES: dict[str, tuple[int, int]] = {
    "hello_emg": (1000, 600),
    "signal_viewer": (700, 380),
    "recording_controls": (440, 200),
    "session_manager": (440, 240),
    "FilterControl": (480, 220),
    "process_launcher": (440, 240),
    "TargetPanel": (440, 200),
    "pipeline_panel": (440, 200),
    "FeatureSelector": (440, 240),
    "app_logo": (360, 260),
    "prediction_label": (440, 200),
    "VhiMovementPanel": (640, 360),
    "AppHeader": (1100, 76),
    "StatusBar": (700, 50),
    "SimulatorControls": (440, 120),
}


def render_signal_viewer(out: Path, *, hello_emg: bool = False) -> None:
    import time
    import numpy as np
    from myogestic import App, Fr, Grid, Px, Stream, StreamInfo
    from myogestic.widgets import RecordingControls, SignalViewer

    FS = 2048.0 if hello_emg else 256.0
    N = 64 if hello_emg else 32
    channels = 8 if hello_emg else 4

    class FakeSource:
        """Paced synthetic 4-channel signal.

        Two things that matter for a clean screenshot:
        - The read() loop must block at the configured sample rate. Without
          a sleep the acquire thread spins, hammering local_clock() and
          stamping thousands of chunks within a few microseconds -> the
          viewer renders them all squashed at one X position.
        - Timestamps come from local_clock() so the viewer's "now" matches
          the wall clock the chunks were stamped at; pacing keeps the
          per-chunk delta equal to N/FS, which is what the viewer expects.
        """

        def __init__(self):
            self._t = 0  # sample counter for waveform phase
            self._next_tick = None  # wall-clock target for next read
            if hello_emg:
                from scipy.signal import butter

                self._rng = np.random.default_rng(7)
                self._sos = butter(4, [20, 450], btype="bandpass", fs=FS, output="sos")
                self._zi = np.zeros((len(self._sos), 2, channels))

        def connect(self):
            from mne_lsl.lsl import local_clock

            self._next_tick = local_clock()
            return StreamInfo(n_channels=channels, fs=FS, dtype=np.dtype("float32"))

        def read(self):
            from mne_lsl.lsl import local_clock

            # Block until the next chunk's worth of wall-clock time has
            # elapsed. This emulates a real LSL inlet's pull_chunk blocking
            # for new samples and stops the acquire thread from spinning.
            target = self._next_tick + N / FS
            now = local_clock()
            if target > now:
                time.sleep(target - now)
            self._next_tick = target

            t = (self._t + np.arange(N)) / FS
            self._t += N
            if hello_emg:
                from scipy.signal import sosfilt

                noise, self._zi = sosfilt(
                    self._sos, self._rng.standard_normal((N, channels)),
                    axis=0, zi=self._zi,
                )
                # The captured five-second window contains Rest → Fist → Rest.
                # Smooth ramps avoid abrupt edges; filtering state spans chunks.
                ramp_up = 0.5 - 0.5 * np.cos(np.pi * np.clip((t - 3.0) / 0.4, 0, 1))
                ramp_down = 0.5 - 0.5 * np.cos(np.pi * np.clip((5.6 - t) / 0.4, 0, 1))
                envelope = 0.035 + 0.9 * ramp_up * ramp_down
                gain = np.array([1.0, 0.75, 0.55, 0.9, 0.65, 1.1, 0.8, 0.6])
                data = (noise * envelope[:, None] * gain).astype(np.float32)
            else:
                data = np.column_stack(
                    [
                        1.2 * np.sin(2 * np.pi * 5 * t) + 0.15 * np.random.randn(N),
                        1.0 * np.cos(2 * np.pi * 7 * t) + 0.15 * np.random.randn(N),
                        0.8 * np.sin(2 * np.pi * 3 * t) + 0.10 * np.random.randn(N),
                        0.6 * np.cos(2 * np.pi * 11 * t) + 0.10 * np.random.randn(N),
                    ]
                ).astype(np.float32)
            # Timestamps end at the wall clock we just paced to, one chunk
            # spanning N samples ending at `target`.
            ts = (target + (np.arange(N) - (N - 1)) / FS).astype(np.float64)
            return data, ts

        def disconnect(self):
            pass

    app = App("Hello EMG" if hello_emg else "signal_viewer")
    # Attached here, not by the acquire loop: a screenshot of a disconnected stream is
    # a screenshot of an empty plot.
    stream = Stream("emg", source=FakeSource(), window_ms=2000, buffer_ms=10000)
    stream.reconnect()
    app.streams(stream)

    viewer = SignalViewer("emg")
    recording = (
        RecordingControls(
            ["Rest", "Fist"], on_record=app.start_recording, on_stop=app.stop_recording
        )
        if hello_emg
        else None
    )
    # Give both captured widgets a cell: an unconstrained viewer consumes the
    # full window height and would leave the recording controls below the fold.
    grid = Grid(1, 2, col_width=[Px(260), Fr(1)]) if hello_emg else None

    @app.ui
    def ui(ctx):
        if grid is None:
            viewer.ui(ctx)
        else:
            with grid[0, 1]:
                viewer.ui(ctx)
            with grid[0, 0]:
                recording.ui(ctx)

    # 7 s delay gives the paced source enough samples to fill the viewer's
    # persisted 5 s resolution window edge-to-edge before capture.
    _self_capture_after(7.0, out, window_only=hello_emg)
    app.run(window_size=SIZES["hello_emg" if hello_emg else "signal_viewer"])


def render_hello_emg(out: Path) -> None:
    """Capture the Hello EMG widgets with a paced fake stream."""
    render_signal_viewer(out, hello_emg=True)


def render_recording_controls(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import RecordingControls

    app = App("recording_controls")

    controls = RecordingControls(
        ["Rest", "Fist", "Open", "Pinch"],
        on_record=lambda: None,
        on_stop=lambda: None,
        on_gesture=lambda i: None,
    )

    @app.ui
    def ui(ctx):
        controls.ui(ctx)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["recording_controls"])


def render_session_manager(out: Path) -> None:
    import json

    from myogestic import App
    from myogestic.widgets import SessionManager

    # Use the participant scan path, then select the fixtures before the first frame.
    tmp = Path(tempfile.mkdtemp(prefix="widget_screenshot_sessions_"))
    participant = "P-014"
    for minute in ("00", "15", "30"):
        d = tmp / participant / "recordings" / f"P-014_20260502-10{minute}_R+F"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({
            "participant": participant,
            "created": f"2026-05-02T10:{minute}:00",
            "class_names": ["Rest", "Fist"],
            "duration_s": 10.0,
            "class_seconds": {"Rest": 5.0, "Fist": 5.0},
            "streams": {"emg": {"n_channels": 8, "fs": 2048.0}},
        }))
        (d / "labels.json").write_text(json.dumps([
            {"class_index": 0, "timestamp": 0.0},
            {"class_index": 1, "timestamp": 5.0},
        ]))
        # Placeholder arrays: the picker reads only metadata and labels.
        (d / "emg.zarr").mkdir()
        (d / "emg_timestamps.zarr").mkdir()

    app = App("session_manager")

    manager = SessionManager(str(tmp), class_names=["Rest", "Fist"])
    manager.select_all(participant)

    @app.ui
    def ui(ctx):
        manager.ui(participant=participant)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["session_manager"])


def render_filter_control(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import PostProcessor

    app = App("FilterControl")
    fc = PostProcessor(hz=20.0)

    @app.ui
    def ui(ctx):
        fc.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["FilterControl"])


def render_process_launcher(out: Path) -> None:
    import sys as _sys
    from myogestic import App
    from myogestic.widgets import ProcessLauncher

    PROCESSES = [
        ("EMG Generator", [_sys.executable, "-c", "import time; time.sleep(60)"]),
        ("VHI Hand", [_sys.executable, "-c", "import time; time.sleep(60)"]),
    ]

    app = App("process_launcher")

    launcher = ProcessLauncher(PROCESSES)

    @app.ui
    def ui(ctx):
        launcher.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["process_launcher"])


def render_target_panel(out: Path) -> None:
    import sys as _sys
    import threading
    from types import SimpleNamespace

    from myogestic import App
    from myogestic.controls import Capability, ControlLink, ControlLinkConnector, load_control_map
    from myogestic.widgets import TargetPanel

    sleeper = [_sys.executable, "-c", "import time; time.sleep(60)"]

    def spec(name: str) -> SimpleNamespace:
        return SimpleNamespace(name=name, launcher=lambda: [(name, sleeper)])

    class Hand:
        """A control target that answers once the process launched for it is up."""

        up = False

        def capabilities(self):
            return [Capability("cursor.x", "continuous", lo=-1.0, hi=1.0)] if self.up else None

        def bind(self, controls):
            pass

        def send(self, values, changed):
            pass

        def stop(self):
            pass

    hand = Hand()
    link = ControlLink(load_control_map({"dofs": {"aim": "cursor.x"}}), [hand])
    connector = ControlLinkConnector(link, retry_s=0.0)
    panel = TargetPanel(
        [spec("VHI Hand"), spec("Kappa Hand"), spec("EMG Generator")],
        connectors={"VHI Hand": connector},
    )
    panel.start("VHI Hand")  # nothing answers, so it launches, then binds
    panel.start("Kappa Hand")
    threading.Timer(0.5, lambda: setattr(hand, "up", True)).start()

    app = App("TargetPanel")

    @app.ui
    def ui(ctx):
        panel.ui(details={"Kappa Hand": "board /dev/cu.usbmodem1101"})

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["TargetPanel"])


def render_pipeline_panel(out: Path) -> None:
    from myogestic import App
    from myogestic.ml import Pipeline
    from myogestic.ml.widgets import PipelinePanel

    app = App("pipeline_panel")
    pipeline = Pipeline(app)

    panel = PipelinePanel(pipeline)

    @app.ui
    def ui(ctx):
        panel.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["pipeline_panel"])


def render_feature_selector(out: Path) -> None:
    import numpy as np
    from myogestic import App
    from myogestic.widgets import FeatureSelector

    selector = FeatureSelector(
        {
            "RMS": lambda x: np.sqrt(np.mean(x**2, axis=1)),
            "MAV": lambda x: np.mean(np.abs(x), axis=1),
            "WL": lambda x: np.sum(np.abs(np.diff(x, axis=1)), axis=1),
            "VAR": lambda x: np.var(x, axis=1),
            "ZC": lambda x: np.sum(np.diff(np.signbit(x), axis=1), axis=1),
        },
        default=["RMS", "MAV"],
    )

    app = App("FeatureSelector")

    @app.ui
    def ui(ctx):
        selector.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["FeatureSelector"])


def render_app_logo(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import AppLogo

    app = App("app_logo")

    logo = AppLogo()

    @app.ui
    def ui(ctx):
        logo.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["app_logo"])


def render_app_header(out: Path) -> None:
    from myogestic import App, Grid, Px
    from myogestic.widgets import AppHeader, StepBar

    app = App("AppHeader")
    grid = Grid.areas("header", row_height=[Px(52)], bare=("header",))
    steps = StepBar(["Connect", "Record", "Train", "Predict"], widget_id="gallery_app_header_steps")
    steps.active = 1
    header = AppHeader("My session app", steps=steps)

    @app.ui
    def ui(ctx):
        with grid.area("header"):
            header.ui(ctx, [True, False, False, False])

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["AppHeader"])


def render_status_bar(out: Path) -> None:
    from myogestic import App, Grid, Px, Stream
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import StatusBar

    app = App("StatusBar")
    app.ctx.participant = "P-014"
    stream = Stream("emg", source=SyntheticSource(n_channels=8, fs=2048), window_ms=200)
    stream.reconnect()
    app.streams(stream)
    grid = Grid.areas("status", row_height=[Px(26)], bare=("status",))
    status = StatusBar("emg")

    @app.ui
    def ui(ctx):
        with grid.area("status"):
            status.ui(ctx)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["StatusBar"])


def render_simulator_controls(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import SimulatorControls

    app = App("SimulatorControls")
    simulator = SimulatorControls([("Rest", 0.0), ("Fist", 1.0)])

    @app.ui
    def ui(ctx):
        simulator.ui(ctx)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["SimulatorControls"])


def render_prediction_label(out: Path) -> None:
    import numpy as np
    from myogestic import App
    from myogestic.widgets import PredictionLabel

    # prediction_label only reads `.predictions`, so a tiny duck-typed stub is
    # enough - no need to spin up a full Pipeline + extract/train/predict chain.
    class FakePipeline:
        predictions = {
            "class": 1,
            "proba": np.array([0.18, 0.82], dtype=np.float32),
        }

    pipeline = FakePipeline()
    classes = ("Rest", "Fist")

    app = App("prediction_label")

    label = PredictionLabel(pipeline, classes, show_probability=True)

    @app.ui
    def ui(ctx):
        label.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["prediction_label"])


def render_vhi_movement_panel(out: Path) -> None:
    # VhiMovementPanel wraps a gRPC client. For a screenshot we don't want a
    # live VHI process - we render the lower-level pure-ImGui
    # `vhi_movement_palette` directly with a pre-populated movement list, which
    # is what `VhiMovementPanel.ui()` ultimately does under the hood.
    from myogestic import App
    from myogestic.widgets.vhi.palette import vhi_movement_palette

    MOVEMENTS = (
        "Rest",
        "Fist",
        "Open",
        "Pinch",
        "ThumbsUp",
        "PointIndex",
        "ThreeFingerPinch",
        "WristFlex",
        "WristExtend",
        "WristPronate",
        "WristSupinate",
        "KeyGrip",
    )

    app = App("VhiMovementPanel")

    @app.ui
    def ui(ctx):
        vhi_movement_palette(
            MOVEMENTS,
            on_movement=lambda _name: None,
            on_refresh=lambda: None,
            current_movement="Fist",
            connected=True,
            status="MOVEMENT mode · 12 movements",
        )

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["VhiMovementPanel"])


def render_follow_run(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import FollowRun

    app = App("FollowRun")
    card = FollowRun(
        ["Fist", "Pinch"],
        drive=lambda index, level: None,
        on_record=app.start_recording,
        on_stop=app.stop_recording,
    )

    @app.ui
    def ui(ctx):
        card.ui(ctx)

    app.cleanup_hooks.append(lambda _app: card.stop(app.ctx))
    _self_capture_after(3.0, out)
    app.run(window_size=(380, 530))


def render_gui_overview(out: Path) -> None:
    """Run the classification tutorial's real record/train/predict cycle on fake EMG."""
    from myogestic import Stream
    from myogestic.sources import SyntheticSource

    # Isolate recorded takes and window settings from the user's data.
    with tempfile.TemporaryDirectory(prefix="myogestic_overview_") as tmp, chdir(tmp):
        ns = runpy.run_path(str(REPO / "examples/synthetic/emg_classification.py"))
        app, pipeline = ns["app"], ns["pipeline"]
        source = SyntheticSource(n_channels=8, fs=2048, waveform="emg", hum=0.0)
        stream = Stream("emg", source=source, window_ms=200, buffer_ms=10000)
        stream.reconnect()
        app.streams(stream)
        app.ctx.participant = "P-014"
        app.ctx.class_names = ns["CLASSES"]

        def workflow():
            try:
                time.sleep(2)
                ns["steps"].active = 1
                for index, activation in enumerate((0.035, 1.0)):
                    source.activation = activation
                    app.ctx.current_label = index
                    ns["simulator"].set(float(index))
                    app.start_recording()
                    assert app.ctx.recording, app.ctx.status_message
                    app.ctx.session.add_label(index)
                    time.sleep(3)
                    app.stop_recording(wait=True)
                ns["sessions"].select_all("P-014")
                ns["steps"].active = 2
                time.sleep(0.5)  # let the UI publish the selected TrainingData
                pipeline.start_training()
                deadline = time.monotonic() + 20
                while app.ctx.state == "training" and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert pipeline.model is not None, pipeline.train_log
                pipeline.start_predicting()
                ns["steps"].active = 3
                time.sleep(7)  # fill the viewer and let the success toast expire
                assert "class" in pipeline.predictions, app.ctx.status_message
                print(f"[overview] trained and predicting: {pipeline.predictions}", flush=True)
                _self_capture_after(0.1, out, window_only=True)
            except Exception:
                import traceback

                traceback.print_exc()
                from imgui_bundle import hello_imgui

                hello_imgui.get_runner_params().app_shall_exit = True

        threading.Thread(target=workflow, daemon=True).start()
        app.run(window_size=(1280, 750))


# ─────────────────────────────────────────────────────────────────────
# Registry + driver
# ─────────────────────────────────────────────────────────────────────

WIDGETS: dict[str, callable] = {
    "hello_emg": render_hello_emg,
    "FollowRun": render_follow_run,
    "signal_viewer": render_signal_viewer,
    "recording_controls": render_recording_controls,
    "session_manager": render_session_manager,
    "FilterControl": render_filter_control,
    "process_launcher": render_process_launcher,
    "TargetPanel": render_target_panel,
    "pipeline_panel": render_pipeline_panel,
    "FeatureSelector": render_feature_selector,
    "app_logo": render_app_logo,
    "prediction_label": render_prediction_label,
    "VhiMovementPanel": render_vhi_movement_panel,
    "AppHeader": render_app_header,
    "StatusBar": render_status_bar,
    "SimulatorControls": render_simulator_controls,
}


def render_example(path: Path, out: Path) -> None:
    """Capture an unchanged example using the same timed window capture as widgets."""
    from myogestic import App

    original_run = App.run

    def capture_run(self, *args, **kwargs):
        # Enough time for synthetic sources and background setup to settle.
        _self_capture_after(7.0, out, window_only=True)
        return original_run(self, *args, **kwargs)

    App.run = capture_run
    sys.argv = [str(path)]
    try:
        runpy.run_path(str(path), run_name="__main__")
    finally:
        App.run = original_run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("widget", nargs="?", help="Widget name to render")
    parser.add_argument("--all", action="store_true", help="Render every widget in the registry")
    parser.add_argument("--example", type=Path, help="Capture one unmodified example app")
    parser.add_argument("--overview", action="store_true", help="Record/train/predict the tutorial")
    parser.add_argument(
        "--examples", action="store_true", help="Capture all panels and the three start_here apps"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output PNG path (default: docs/images/widgets/<name>.png)",
    )
    args = parser.parse_args()

    if args.examples:
        for path in sorted((REPO / "examples/panels").glob("*.py")) + sorted(
            (REPO / "examples/start_here").glob("*.py")
        ):
            out = REPO / ".superpowers/screens" / f"app-font-{path.parent.name}-{path.stem}.png"
            print(f"=== {path.relative_to(REPO)} ===", flush=True)
            subprocess.run(
                [sys.executable, __file__, "--example", str(path), "--out", str(out)],
                check=True,
                timeout=60,
            )
        return

    if args.all:
        # Spawn this script as subprocess for each widget so windows
        # don't pile up in the same process.
        for name in WIDGETS:
            print(f"=== {name} ===")
            subprocess.run(
                [sys.executable, __file__, name],
                check=True,
                timeout=60,
            )
        return

    if not args.widget and not args.example and not args.overview:
        parser.print_help()
        sys.exit(2)

    if not args.example and not args.overview and args.widget not in WIDGETS:
        print(f"Unknown widget: {args.widget!r}", file=sys.stderr)
        print(f"Available: {sorted(WIDGETS)}", file=sys.stderr)
        sys.exit(2)

    default_out = (
        REPO / "docs/images/gui-overview.png" if args.overview
        else OUT_DIR / f"{args.widget or args.example.stem}.png"
    )
    out = (args.out or default_out).resolve()
    out.unlink(missing_ok=True)
    try:
        if args.overview:
            render_gui_overview(out)
        elif args.example:
            render_example(args.example.resolve(), out)
        else:
            WIDGETS[args.widget](out)
    except KeyboardInterrupt:
        pass
    if not out.is_file():
        raise SystemExit(f"Capture failed: {out}")


if __name__ == "__main__":
    main()
