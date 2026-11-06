"""Scripted GIFs for the README, recorded from the real app.

Usage:
    uv run --extra examples --extra grpc python tools/readme_gifs.py pong
    uv run python tools/readme_gifs.py signal_viewer   # or recording_controls, prediction_label, FollowRun
    uv run --extra examples --extra grpc python tools/readme_gifs.py --all
    uv run python tools/readme_gifs.py signal_viewer --probe   # print the button labels a scene draws

Each scene runs in its own process with the ImGui test engine on. The engine moves a drawn
cursor and clicks buttons by their label, ``screencapture -v`` records the window, and
ffmpeg turns the clip into a palette GIF in ``docs/images/gifs/``. Like
``widget_screenshot.py`` this is macOS-only and needs Screen Recording permission and an
unlocked screen.

Sessions, the participant key and ImGui state go to a temporary directory, never to
``sessions/`` or ``~/myogestic``. liblsl is pinned to this machine for the run.

In the Pong scene the synthetic wrist plays the subject. It follows the cursor while the
training block records, as the app's own dummy does, and follows the ball during play;
the paddle moves on what the trained model predicts from that synthetic EMG.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from collections.abc import Callable

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "images" / "gifs"
WORK = Path(tempfile.mkdtemp(prefix="myogestic-gifs-"))

# Loopback-only liblsl, set before myogestic imports and configures it.
_LSL_CFG = WORK / "lsl_api.cfg"
_LSL_CFG.write_text(
    "[ports]\nIPv6 = disable\n[multicast]\nResolveScope = machine\n"
    "[lab]\nKnownPeers = {127.0.0.1}\n[log]\nlevel = -2\n"
)
os.environ["LSLAPICFG"] = str(_LSL_CFG)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import Quartz  # type: ignore  # noqa: E402 - on the main thread; the test engine's thread hangs exit
from imgui_bundle import hello_imgui, imgui, immapp  # noqa: E402

te = imgui.test_engine

# ─────────────────────────────────────────────────────────────────────
# Clicking by label
# ─────────────────────────────────────────────────────────────────────

#: label -> (centre, frame it was last drawn on)
_seen: dict[str, tuple[imgui.ImVec2, int]] = {}
_probe = False


def _track(draw: Callable) -> Callable:
    def tracked(label, *args, **kwargs):
        result = draw(label, *args, **kwargs)
        lo, hi = imgui.get_item_rect_min(), imgui.get_item_rect_max()
        if _probe and label not in _seen:
            print(f"[probe] {label!r}")
        _seen[label] = (imgui.ImVec2((lo.x + hi.x) / 2, (lo.y + hi.y) / 2), imgui.get_frame_count())
        return result

    return tracked


for _name in ("button", "small_button", "invisible_button", "selectable"):
    setattr(imgui, _name, _track(getattr(imgui, _name)))


def find(ctx, part: str, timeout: float = 15.0) -> imgui.ImVec2:
    """Wait for a button labelled ``part``, or else containing it, and return its centre."""
    deadline = time.monotonic() + timeout
    while True:
        now = imgui.get_frame_count()
        fresh = {label: centre for label, (centre, frame) in _seen.items() if frame >= now - 1}
        if part in fresh:
            return fresh[part]
        for label, centre in fresh.items():
            if part in label:
                return centre
        if time.monotonic() > deadline:
            raise LookupError(f"no button labelled like {part!r} on screen")
        ctx.yield_()


def click(ctx, part: str, pause: float = 0.4) -> None:
    """Move the drawn cursor to a button and click it."""
    if _probe:
        print(f"[click] {part}", flush=True)
    ctx.mouse_move_to_pos(find(ctx, part))
    ctx.mouse_click(0)
    ctx.sleep_no_skip(pause, 1 / 60)


def wait(ctx, done: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not done():
        if time.monotonic() > deadline:
            raise TimeoutError(f"gave up waiting for {what}")
        ctx.yield_()


def hold(ctx, seconds: float, each_frame: Callable[[], None] | None = None) -> None:
    """Keep rendering for ``seconds`` of wall clock."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if each_frame is not None:
            each_frame()
        ctx.yield_()


# ─────────────────────────────────────────────────────────────────────
# Recording the window
# ─────────────────────────────────────────────────────────────────────


def _window_bounds() -> tuple[float, float, float, float]:
    for w in Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    ):
        if w.get("kCGWindowOwnerPID") == os.getpid() and w.get("kCGWindowLayer") == 0:
            b = w["kCGWindowBounds"]
            return b["X"], b["Y"], b["Width"], b["Height"]
    raise RuntimeError("this process has no window on screen")


#: Work for the main thread, drained once a frame. Quartz called from the test engine's
#: thread leaves the app unable to quit.
_main_jobs: list[Callable[[], None]] = []


def on_main(ctx, job: Callable):
    """Run ``job`` on the GUI thread at the next frame and return its result."""
    box: list = []
    _main_jobs.append(lambda: box.append(job()))
    while not box:
        ctx.yield_()
    return box[0]


class Clip:
    """Record the window's content area for ``seconds`` while the GUI keeps running.

    ``screencapture -v`` cannot follow one window, so this records the window's
    rectangle below the title bar. ``content`` is the size passed to ``app.run``.
    """

    @classmethod
    def start(cls, ctx, seconds: float, content: tuple[int, int], name: str) -> Clip:
        return on_main(ctx, lambda: cls(seconds, content, name))

    def __init__(self, seconds: float, content: tuple[int, int], name: str) -> None:
        x, y, w, h = _window_bounds()
        top = y + h - content[1]
        self.movie = WORK / f"{name}.mov"
        self.process = subprocess.Popen(
            ["screencapture", "-v", "-x", "-V", f"{seconds:g}",
             "-R", f"{x:g},{top:g},{w:g},{content[1]:g}", str(self.movie)],
        )

    def running(self) -> bool:
        return self.process.poll() is None


def encode(
    movie: Path, out: Path, *, width: int, fps: int, skip: float = 0.0, colors: int = 128
) -> None:
    """Palette GIF from a clip, its rounded bottom corners squared off in the window colour."""
    corner = 28  # px at 2x: the window's corner radius, which shows the desktop through
    probe = WORK / "corner.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", str(movie), "-frames:v", "1", str(probe)],
        check=True,
    )
    from PIL import Image

    frame = Image.open(probe).convert("RGB")
    bg = "0x{:02x}{:02x}{:02x}".format(*frame.getpixel((frame.width // 2, frame.height - 3)))
    square = (
        f"drawbox=x=0:y=ih-{corner}:w={corner}:h={corner}:color={bg}:t=fill,"
        f"drawbox=x=iw-{corner}:y=ih-{corner}:w={corner}:h={corner}:color={bg}:t=fill"
    )
    graph = (
        f"[0:v]{square},fps={fps},scale={width}:-1:flags=lanczos,split[a][b];"
        f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{skip:g}", "-i", str(movie),
         "-filter_complex", graph, "-loop", "0", str(out)],
        check=True,
    )
    print(f"[gif] {out.relative_to(REPO)} ({out.stat().st_size / 1e6:.1f} MB)")


# ─────────────────────────────────────────────────────────────────────
# Running an app under the test engine
# ─────────────────────────────────────────────────────────────────────


def scripted(start: Callable[[], None], script: Callable) -> None:
    """Run ``start()`` (which calls ``app.run``) with ``script(ctx)`` driving it."""
    failure: list[BaseException] = []
    real_run = immapp.run

    def run(*args, runner_params, **kwargs):
        runner_params.use_imgui_test_engine = True

        def register() -> None:
            engine = hello_imgui.get_imgui_test_engine()
            io = te.get_io(engine)
            io.config_run_speed = te.TestRunSpeed.normal
            io.config_watchdog_warning = 600.0
            io.config_watchdog_kill_test = 900.0
            io.config_watchdog_kill_app = 1200.0
            test = te.register_test(engine, "readme", "gif")

            def body(ctx) -> None:
                try:
                    imgui.get_io().mouse_draw_cursor = True
                    script(ctx)
                except BaseException as error:  # noqa: BLE001 - reported after exit
                    traceback.print_exc()
                    failure.append(error)
                finally:
                    runner_params.app_shall_exit = True

            test.test_func = body
            te.queue_test(engine, test)

        before = runner_params.callbacks.post_new_frame

        def drain() -> None:
            if before is not None:
                before()
            while _main_jobs:
                _main_jobs.pop(0)()

        runner_params.callbacks.register_tests = register
        runner_params.callbacks.post_new_frame = drain
        return real_run(*args, runner_params=runner_params, **kwargs)

    immapp.run = run
    os.chdir(WORK)
    try:
        start()
    finally:
        immapp.run = real_run
    if failure:
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────
# Scenes
# ─────────────────────────────────────────────────────────────────────

WIDGET_GIF = {"width": 800, "fps": 20}


def centred(draw: Callable[[], None]) -> Callable[[], None]:
    """Wrap ``draw`` to sit vertically centred in the window, using last frame's height."""
    last = {"height": 0.0}

    def drawn() -> None:
        free = imgui.get_content_region_avail().y - last["height"]
        imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + max(0.0, free / 2))
        start = imgui.get_cursor_pos_y()
        draw()
        last["height"] = imgui.get_cursor_pos_y() - start

    return drawn
#: One window for every widget, so the README's gallery cells match.
WIDGET_SIZE = (600, 400)
#: Session archives for the signal viewer to replay (``--replay``); synthetic bursts without.
_replay: list[Path] = []


class BurstSource:
    """Four channels of noise under a burst envelope: contractions, staggered per channel.

    `SyntheticSource` is a tone per channel, which suits testing; a README wants
    something that looks like EMG. Paced like an inlet, as `widget_screenshot.py`
    explains for its own fake source.
    """

    FS, N = 1000.0, 25

    def connect(self):
        import numpy as np
        from mne_lsl.lsl import local_clock
        from myogestic import StreamInfo

        self._next, self._t = local_clock(), 0
        return StreamInfo(n_channels=4, fs=self.FS, dtype=np.dtype("float32"))

    def read(self):
        import numpy as np
        from mne_lsl.lsl import local_clock

        due = self._next + self.N / self.FS
        if due > local_clock():
            time.sleep(due - local_clock())
        self._next = due
        t = (self._t + np.arange(self.N))[:, None] / self.FS
        self._t += self.N
        phase = np.array([0.0, 1.6, 3.2, 4.8])
        envelope = 0.06 + np.clip(np.sin(2 * np.pi * 0.45 * t - phase), 0, None) ** 2
        data = (np.random.randn(self.N, 4) * envelope).astype(np.float32)
        return data, due + (np.arange(self.N) - (self.N - 1)) / self.FS

    def disconnect(self):
        pass


class ReplaySource:
    """Saved takes replayed back to back, looping, paced like an inlet.

    Each take contributes ``seconds`` from its middle with its median removed. One gain
    for all of them keeps a rest and a fist comparable on the viewer's shared range.
    """

    N = 25

    def __init__(self, paths: list[Path], seconds: float = 2.5) -> None:
        import numpy as np
        from myogestic.session import open_session_store

        parts = []
        for path in paths:
            session = open_session_store(path)
            try:
                emg, _ = session.get_continuous("emg")
                self.FS = session.stream_info("emg").fs
            finally:
                session.close()
            emg = np.asarray(emg, dtype=np.float32)
            emg -= np.median(emg, axis=0)
            n, mid = int(seconds * self.FS), len(emg) // 2
            parts.append(emg[max(0, mid - n // 2) : max(0, mid - n // 2) + n])
        self._emg = np.concatenate(parts)
        self._emg /= np.percentile(np.abs(self._emg), 99.5)
        self._at = 0

    def connect(self):
        import numpy as np
        from mne_lsl.lsl import local_clock
        from myogestic import StreamInfo

        self._next = local_clock()
        return StreamInfo(n_channels=self._emg.shape[1], fs=self.FS, dtype=np.dtype("float32"))

    def read(self):
        import numpy as np
        from mne_lsl.lsl import local_clock

        due = self._next + self.N / self.FS
        if due > local_clock():
            time.sleep(due - local_clock())
        self._next = due
        rows = np.take(self._emg, range(self._at, self._at + self.N), axis=0, mode="wrap")
        self._at = (self._at + self.N) % len(self._emg)
        return rows, due + (np.arange(self.N) - (self.N - 1)) / self.FS

    def disconnect(self):
        pass


def gif_signal_viewer(out: Path) -> None:
    from myogestic import App, Stream
    from myogestic.widgets import SignalViewer

    size = WIDGET_SIZE
    app = App("signal_viewer")
    source = ReplaySource(_replay) if _replay else BurstSource()
    stream = Stream("emg", source=source, window_ms=2000, buffer_ms=10000)
    stream.reconnect()
    app.streams(stream)
    # One range for every lane: autoscaled, a resting channel and a contracting one look alike.
    viewer = SignalViewer("emg", scale_mode="manual", y_range=(-1.0, 1.0) if _replay else (-1.5, 1.5))

    @app.ui
    def ui(ctx):
        viewer.ui(ctx)

    clip: list[Clip] = []

    def script(ctx) -> None:
        hold(ctx, 5.5)  # fill the 5 s window edge to edge
        clip.append(Clip.start(ctx, 5.0, size, "signal_viewer"))
        wait(ctx, lambda: not clip[0].running(), 30, "the recording")

    scripted(lambda: app.run(window_size=size), script)
    encode(clip[0].movie, out, width=800, fps=15, colors=64, skip=0.3)


def gif_recording_controls(out: Path) -> None:
    from myogestic import App, Stream
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import RecordingControls

    size = WIDGET_SIZE
    app = App("recording_controls")
    stream = Stream("emg", source=SyntheticSource(), window_ms=1000)
    stream.reconnect()
    app.streams(stream)
    controls = RecordingControls(
        ["Rest", "Fist", "Open", "Pinch"],
        on_record=app.start_recording,
        on_stop=app.stop_recording,
        take_lengths=(3.0,),
        warmups=(0.0, 2.0),
        timed=True,
        warmup=2.0,
    )

    draw = centred(lambda: controls.ui(app.ctx))

    @app.ui
    def ui(ctx):
        draw()

    clip: list[Clip] = []

    def script(ctx) -> None:
        hold(ctx, 1.0)
        clip.append(Clip.start(ctx, 8.0, size, "recording_controls"))
        hold(ctx, 0.8)
        click(ctx, "##rec_gesture1")  # Fist
        click(ctx, "##rec_btn")
        wait(ctx, lambda: controls.take.phase in ("idle", "saved"), 15, "the take")
        wait(ctx, lambda: not clip[0].running(), 30, "the recording")

    scripted(lambda: app.run(window_size=size), script)
    encode(clip[0].movie, out, **WIDGET_GIF, skip=0.3)


def gif_prediction_label(out: Path) -> None:

    import numpy as np
    from myogestic import App
    from myogestic.widgets import PredictionLabel

    classes = ("Rest", "Fist", "Open", "Pinch", "Point")
    period = 6.0  # seconds to visit every class once; the clip is one period, so it loops

    class SwayingPipeline:
        """An intent that moves through the classes, read out as a softmax."""

        @property
        def predictions(self) -> dict:
            at = (time.monotonic() / period * len(classes)) % len(classes)
            steps = np.abs(np.arange(len(classes)) - at)
            steps = np.minimum(steps, len(classes) - steps)
            proba = np.exp(-3.0 * steps**2)
            proba /= proba.sum()
            return {"class": int(proba.argmax()), "proba": proba.astype(np.float32)}

    size = WIDGET_SIZE
    app = App("prediction_label")
    label = PredictionLabel(SwayingPipeline(), classes, show_probability=True)
    draw = centred(label.ui)

    @app.ui
    def ui(ctx):
        draw()

    clip: list[Clip] = []

    def script(ctx) -> None:
        hold(ctx, 1.0)
        clip.append(Clip.start(ctx, period + 0.3, size, "prediction_label"))
        wait(ctx, lambda: not clip[0].running(), 30, "the recording")

    scripted(lambda: app.run(window_size=size), script)
    encode(clip[0].movie, out, **WIDGET_GIF, skip=0.3)


def gif_follow_run(out: Path) -> None:
    from myogestic import App, Stream
    from myogestic.sources import SyntheticSource
    from myogestic.widgets import FollowRun

    size = WIDGET_SIZE
    app = App("FollowRun")
    stream = Stream("emg", source=SyntheticSource(), window_ms=1000)
    stream.reconnect()
    app.streams(stream)
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
    clip: list[Clip] = []

    def script(ctx) -> None:
        hold(ctx, 1.0)
        clip.append(Clip.start(ctx, 9.0, size, "FollowRun"))
        hold(ctx, 0.8)
        click(ctx, "Start")
        wait(ctx, lambda: not clip[0].running(), 30, "the recording")

    scripted(lambda: app.run(window_size=size), script)
    encode(clip[0].movie, out, **WIDGET_GIF, skip=0.3)


def gif_pong(out: Path) -> None:
    from myogestic.widgets.panels import participant

    participant.ParticipantPanel.__init__.__kwdefaults__["key_file"] = WORK / "participant-key.csv"
    spec = importlib.util.spec_from_file_location(
        "pong_app", REPO / "examples" / "start_here" / "pong.py"
    )
    pong = importlib.util.module_from_spec(spec)
    os.chdir(WORK)
    spec.loader.exec_module(pong)

    size = (1280, 800)
    real_update = pong._update_dummy
    autopilot = {"on": False}

    def follow_ball(dummy, dt: float) -> None:
        """During play the dummy subject steers toward the ball, in the dummy's 150 ms."""
        if not autopilot["on"]:
            return real_update(dummy, dt)
        game = pong.pong
        ball = game._ball
        aim = ball.y if ball is not None and ball.vx > 0 else 0.0
        goal = max(-1.0, min(1.0, 2.5 * (aim - game._paddle)))
        reach = max(0.0, dt) / 0.15
        dummy.drive += min(max(goal - dummy.drive, -reach), reach)

    pong._update_dummy = follow_ball
    clip: list[Clip] = []

    def script(ctx) -> None:
        try:
            play(ctx)
        except BaseException:
            app = pong.app.ctx
            print(f"[pong] state={app.state!r} status={app.status_message!r}", flush=True)
            print("\n".join(f"[pong log] {line}" for line in app.logs[-15:]), flush=True)
            raise

    def play(ctx) -> None:
        hold(ctx, 1.5)
        click(ctx, "###chip")
        click(ctx, "New participant")
        click(ctx, "Start session")
        # Connect: choose the synthetic wrist in the device dropdown, then connect it.
        labels = [d.label for d in pong.device._devices]
        wrist = next(i for i, label in enumerate(labels) if label.startswith("Synthetic wrist"))
        on_main(ctx, lambda: setattr(pong.device, "_selected", wrist))
        hold(ctx, 0.5)
        click(ctx, "##dp_connect")
        hold(ctx, 1.5)
        # Record: one pursuit block, the dummy following the cursor.
        click(ctx, "###step1")
        click(ctx, "Follow the cursor")
        wait(ctx, lambda: pong.target.running, 5, "the pursuit block to start")
        wait(ctx, lambda: not pong.target.running, 120, "the pursuit block")
        hold(ctx, 2.0)
        # Train, then play.
        click(ctx, "###step2")
        click(ctx, "##ml_train")
        wait(ctx, lambda: pong.pipeline.model is not None, 180, "training")
        click(ctx, "###step3")
        click(ctx, "  Predict")
        autopilot["on"] = True
        hold(ctx, 1.0)
        click(ctx, "##pong_serve")
        wait(ctx, lambda: pong.pong._ball is not None, 3, "the serve")
        # The rest is the subject's, not the mouse's: no cursor parked on the court.
        on_main(ctx, lambda: setattr(imgui.get_io(), "mouse_draw_cursor", False))
        clip.append(Clip.start(ctx, 12.0, size, "pong"))
        wait(ctx, lambda: not clip[0].running(), 60, "the recording")

    try:
        scripted(lambda: pong.app.run(window_size=size), script)
    finally:
        pong.link.stop()
        pong.vhi_control.stop()
    encode(clip[0].movie, out, width=1200, fps=15, skip=0.5)


SCENES: dict[str, Callable[[Path], None]] = {
    "pong": gif_pong,
    "signal_viewer": gif_signal_viewer,
    "recording_controls": gif_recording_controls,
    "prediction_label": gif_prediction_label,
    "FollowRun": gif_follow_run,
}


def main() -> None:
    global _probe
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", nargs="?", choices=sorted(SCENES))
    parser.add_argument("--all", action="store_true", help="Record every scene, one process each")
    parser.add_argument("--probe", action="store_true", help="Print each button label once")
    parser.add_argument(
        "--replay", nargs="+", type=Path, default=[], metavar="SESSION",
        help="signal_viewer: replay these .mg.zip takes, in order, instead of synthetic bursts",
    )
    args = parser.parse_args()
    if args.all:
        for name in SCENES:
            print(f"=== {name} ===")
            replay = ["--replay", *map(str, args.replay)] if args.replay and name == "signal_viewer" else []
            subprocess.run([sys.executable, __file__, name, *replay], check=False)
        return
    if not args.scene:
        parser.print_help()
        sys.exit(2)
    _probe = args.probe
    _replay[:] = args.replay
    try:
        SCENES[args.scene](OUT_DIR / f"{args.scene}.gif")
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
