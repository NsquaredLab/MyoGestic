"""Self-capturing widget screenshots for the docs site.

Usage:
    uv run python tools/widget_screenshot.py <widget_name> [--out PATH]
    uv run python tools/widget_screenshot.py --all

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
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "images" / "widgets"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# Self-capture helper
# ─────────────────────────────────────────────────────────────────────

def _self_capture_after(seconds: float, output_path: Path) -> None:
    """In a background thread, wait ``seconds``, find this process's
    main GUI window via Quartz, screencapture it, then SIGINT main to
    exit cleanly.
    """
    def _run() -> None:
        time.sleep(seconds)
        try:
            import Quartz  # type: ignore
        except Exception as e:
            print(f"[capture] Quartz import failed: {e}", file=sys.stderr)
            os.kill(os.getpid(), signal.SIGINT)
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
            os.kill(os.getpid(), signal.SIGINT)
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["screencapture", "-l", str(wid), "-t", "png", "-x", str(output_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"[capture] screencapture failed: {result.stderr}", file=sys.stderr)
        else:
            print(f"[capture] saved {output_path} ({output_path.stat().st_size} B)")
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=_run, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────
# Widget renderers
# Each function builds a minimal App+UI showing one widget, then runs.
# ─────────────────────────────────────────────────────────────────────

# Per-widget window sizes (logical pixels). Tuned so each widget fills
# the window at its natural rendered height with no empty padding.
SIZES: dict[str, tuple[int, int]] = {
    "signal_viewer": (700, 380),
    "recording_controls": (440, 200),
    "session_manager": (440, 240),
    "FilterControl": (480, 220),
    "process_launcher": (440, 240),
    "pipeline_panel": (440, 200),
    "FeatureSelector": (440, 240),
    "app_logo": (360, 260),
    "prediction_label": (440, 200),
    "VhiMovementPanel": (640, 360),
}


def render_signal_viewer(out: Path) -> None:
    import time
    import numpy as np
    from myogestic import App, Stream, StreamInfo
    from myogestic.widgets import signal_viewer

    FS = 256.0
    N = 32  # samples per read - 32 / 256 = 125 ms per chunk

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

        def connect(self):
            from mne_lsl.lsl import local_clock
            self._next_tick = local_clock()
            return StreamInfo(n_channels=4, fs=FS, dtype=np.dtype("float32"))

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
            data = np.column_stack([
                1.2 * np.sin(2 * np.pi * 5 * t) + 0.15 * np.random.randn(N),
                1.0 * np.cos(2 * np.pi * 7 * t) + 0.15 * np.random.randn(N),
                0.8 * np.sin(2 * np.pi * 3 * t) + 0.10 * np.random.randn(N),
                0.6 * np.cos(2 * np.pi * 11 * t) + 0.10 * np.random.randn(N),
            ]).astype(np.float32)
            # Timestamps end at the wall clock we just paced to, one chunk
            # spanning N samples ending at `target`.
            ts = (target + (np.arange(N) - (N - 1)) / FS).astype(np.float64)
            return data, ts

        def disconnect(self):
            pass

    app = App("signal_viewer")
    app.streams(Stream("emg", source=FakeSource(), window_ms=2000, buffer_ms=10000))

    @app.ui
    def ui(ctx):
        signal_viewer(ctx, "emg")

    # 7 s delay gives the paced source enough samples to fill the viewer's
    # persisted 5 s resolution window edge-to-edge before capture.
    _self_capture_after(7.0, out)
    app.run(window_size=SIZES["signal_viewer"])


def render_recording_controls(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import recording_controls

    app = App("recording_controls")

    @app.ui
    def ui(ctx):
        recording_controls(
            ctx, ["Rest", "Fist", "Open", "Pinch"],
            on_record=lambda: None,
            on_stop=lambda: None,
            on_gesture=lambda i: None,
        )

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["recording_controls"])


def render_session_manager(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import session_manager

    # Fake sessions folder with a couple of placeholder folders
    tmp = Path(tempfile.mkdtemp(prefix="widget_screenshot_sessions_"))
    for name in ("2026-05-01_10-00-00", "2026-05-01_10-15-00", "2026-05-02_09-30-00"):
        d = tmp / name
        d.mkdir()
        (d / "meta.json").write_text('{"class_names": ["Rest", "Fist"]}')
        # Mock a minimal zarr-like layout so it shows as a session
        (d / "emg.zarr").mkdir()
        (d / "emg_timestamps.zarr").mkdir()

    app = App("session_manager")

    @app.ui
    def ui(ctx):
        session_manager(str(tmp), class_names=["Rest", "Fist"])

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["session_manager"])


def render_filter_control(out: Path) -> None:
    from myogestic import App
    from myogestic.widgets import FilterControl

    app = App("FilterControl")
    fc = FilterControl(hz=20.0, default="one_euro")

    @app.ui
    def ui(ctx):
        fc.ui()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["FilterControl"])


def render_process_launcher(out: Path) -> None:
    import sys as _sys
    from myogestic import App
    from myogestic.widgets import process_launcher

    PROCESSES = [
        ("EMG Generator", [_sys.executable, "-c", "import time; time.sleep(60)"]),
        ("VHI Hand", [_sys.executable, "-c", "import time; time.sleep(60)"]),
    ]

    app = App("process_launcher")

    @app.ui
    def ui(ctx):
        process_launcher(PROCESSES)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["process_launcher"])


def render_pipeline_panel(out: Path) -> None:
    from myogestic import App
    from myogestic.ml import Pipeline
    from myogestic.ml.widgets import pipeline_panel

    app = App("pipeline_panel")
    pipeline = Pipeline(app)

    @app.ui
    def ui(ctx):
        pipeline_panel(pipeline)

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["pipeline_panel"])


def render_feature_selector(out: Path) -> None:
    import numpy as np
    from myogestic import App
    from myogestic.widgets import FeatureSelector

    selector = FeatureSelector(
        {
            "RMS": lambda x: np.sqrt(np.mean(x ** 2, axis=1)),
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
    from myogestic.widgets import app_logo

    app = App("app_logo")

    @app.ui
    def ui(ctx):
        app_logo()

    _self_capture_after(3.0, out)
    app.run(window_size=SIZES["app_logo"])


def render_prediction_label(out: Path) -> None:
    import numpy as np
    from myogestic import App
    from myogestic.widgets.training.prediction_label import prediction_label

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

    @app.ui
    def ui(ctx):
        prediction_label(pipeline, classes, show_probability=True)

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
        "Rest", "Fist", "Open", "Pinch", "ThumbsUp", "PointIndex",
        "ThreeFingerPinch", "WristFlex", "WristExtend", "WristPronate",
        "WristSupinate", "KeyGrip",
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


# ─────────────────────────────────────────────────────────────────────
# Registry + driver
# ─────────────────────────────────────────────────────────────────────

WIDGETS: dict[str, callable] = {
    "signal_viewer": render_signal_viewer,
    "recording_controls": render_recording_controls,
    "session_manager": render_session_manager,
    "FilterControl": render_filter_control,
    "process_launcher": render_process_launcher,
    "pipeline_panel": render_pipeline_panel,
    "FeatureSelector": render_feature_selector,
    "app_logo": render_app_logo,
    "prediction_label": render_prediction_label,
    "VhiMovementPanel": render_vhi_movement_panel,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("widget", nargs="?", help="Widget name to render")
    parser.add_argument("--all", action="store_true", help="Render every widget in the registry")
    parser.add_argument(
        "--out", type=Path, default=None, help="Output PNG path (default: docs/images/widgets/<name>.png)"
    )
    args = parser.parse_args()

    if args.all:
        # Spawn this script as subprocess for each widget so windows
        # don't pile up in the same process.
        for name in WIDGETS:
            print(f"=== {name} ===")
            subprocess.run(
                [sys.executable, __file__, name],
                check=False,
            )
        return

    if not args.widget:
        parser.print_help()
        sys.exit(2)

    if args.widget not in WIDGETS:
        print(f"Unknown widget: {args.widget!r}", file=sys.stderr)
        print(f"Available: {sorted(WIDGETS)}", file=sys.stderr)
        sys.exit(2)

    out = args.out or (OUT_DIR / f"{args.widget}.png")
    try:
        WIDGETS[args.widget](out)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
