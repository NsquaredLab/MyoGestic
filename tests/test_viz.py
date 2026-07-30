"""Test widget classes are importable and render-ready (no GUI)."""

import numpy as np

from myogestic.widgets.common import PALETTE
from myogestic.widgets.panels.log_panel import LogPanel
from myogestic.widgets.panels.popout import popout_panel
from myogestic.widgets.panels.process_launcher import ProcessLauncher
from myogestic.widgets.plots.heatmap import Heatmap
from myogestic.widgets.plots.line_plot import LinePlot
from myogestic.widgets.plots.scatter import Scatter2D, Scatter3D
from myogestic.widgets.signals.raw import RawSignalViewer
from myogestic.widgets.signals.stream_panel import StreamPanel
from myogestic.widgets.signals.viewer import SignalViewer


def test_palette_shape():
    assert PALETTE.shape == (10, 3)
    assert PALETTE.dtype == np.float32


def test_widget_classes_have_ui():
    """Every widget is a class exposing a `.ui()` render method."""
    for widget_cls in (
        Scatter2D,
        Scatter3D,
        Heatmap,
        LinePlot,
        SignalViewer,
        RawSignalViewer,
        ProcessLauncher,
        StreamPanel,
        LogPanel,
    ):
        assert isinstance(widget_cls, type)
        assert callable(getattr(widget_cls, "ui", None))


def test_popout_panel_is_callable():
    assert callable(popout_panel)


def test_imports_from_widgets_init():
    from myogestic.widgets import (
        LogPanel,
        ProcessLauncher,
        SignalViewer,
        StreamPanel,
        popout_panel,
    )

    for widget_cls in (SignalViewer, ProcessLauncher, StreamPanel, LogPanel):
        assert hasattr(widget_cls, "ui")
    assert callable(popout_panel)


def test_heatmap_renders_with_per_cell_ticks(implot_frame):
    """The heatmap renders one tick per cell — default index labels, custom
    labels, and a non-square grid — without error."""
    cm = np.array([[0.9, 0.1], [0.2, 0.8]])
    hm = Heatmap("Confusion")
    implot_frame(lambda: hm.ui(cm))
    implot_frame(lambda: hm.ui(cm, x_tick_labels=["A", "B"], y_tick_labels=["A", "B"]))
    implot_frame(lambda: hm.ui(np.arange(6.0).reshape(2, 3)))


def test_heatmap_shared_vrange_renders(implot_frame):
    """A shared `vrange` renders for grids whose own ranges differ wildly.

    Without it every instance maps its own min/max, so a quiet electrode array
    and a loud one render identically — the failure mode when several arrays
    are meant to be compared side by side. Also covers degenerate ranges.
    """
    quiet = np.full((2, 2), 0.01)
    loud = np.array([[5.0, 9.0], [1.0, 7.0]])
    shared = (0.0, 9.0)
    hm = Heatmap("Array")
    implot_frame(lambda: hm.ui(quiet, vrange=shared))
    implot_frame(lambda: hm.ui(loud, vrange=shared))
    implot_frame(lambda: hm.ui(quiet, vrange=(0.0, 0.0)))  # degenerate: lo == hi
    implot_frame(lambda: hm.ui(np.zeros((2, 2))))  # flat data, no vrange


def test_widget_id_gives_each_viewer_its_own_state():
    """Several viewers on ONE stream must not share state.

    Without a distinct `widget_id` every `SignalViewer("emg")` resolves to the
    same ViewerState, so a per-electrode-grid panel layout would render five
    identical tiles. Default (no widget_id) still keys by stream name.
    """
    from types import SimpleNamespace

    from myogestic.widgets.signals._state import get_viewer_state

    ctx = SimpleNamespace(streams={})
    kw = dict(
        n_pixels=None,
        scale_mode="auto",
        y_range=(-1.0, 1.0),
        show_markers=False,
        window_s=1.0,
        stream_name="emg",
    )
    a = get_viewer_state(ctx, "tviz_IN1", **kw)
    b = get_viewer_state(ctx, "tviz_IN2", **kw)
    assert a is not b  # distinct ids -> independent state
    assert a is get_viewer_state(ctx, "tviz_IN1", **kw)  # same id -> same state

    a.channels = {1, 2}
    b.channels = {7}
    a.paused = True
    assert b.channels == {7} and not b.paused  # no cross-talk

    # Defaulting widget_id to the stream name keeps the single-viewer behaviour.
    solo = get_viewer_state(ctx, "tviz_emg", **{**kw, "stream_name": None})
    assert solo is get_viewer_state(ctx, "tviz_emg", **kw)


def test_show_controls_seeds_from_constructor_arg():
    """`show_controls=False` opens a tiled panel with the menu collapsed."""
    from types import SimpleNamespace

    from myogestic.widgets.signals._state import get_viewer_state

    ctx = SimpleNamespace(streams={})
    kw = dict(
        n_pixels=None,
        scale_mode="auto",
        y_range=(-1.0, 1.0),
        show_markers=False,
        window_s=1.0,
        stream_name="emg",
    )
    assert get_viewer_state(ctx, "tviz_hidden", show_controls=False, **kw).show_controls is False
    assert get_viewer_state(ctx, "tviz_shown", **kw).show_controls is True


def test_log_panel_renders_with_horizontal_scroll(imgui_frame):
    """The log panel renders long (non-wrapping) lines, the empty state, the
    narrow header (Clear button drops below), and the header-less variant."""
    from types import SimpleNamespace

    from imgui_bundle import imgui

    ctx = SimpleNamespace(logs=["[12:00:00] started", "x" * 200])
    lp = LogPanel()
    imgui_frame(lambda: lp.ui(ctx))
    imgui_frame(lambda: lp.ui(SimpleNamespace(logs=[])))  # empty state

    def narrow():  # too tight for icon + Clear inline -> Clear drops to its own line
        imgui.begin_child("narrow", imgui.ImVec2(40.0, 200.0))
        lp.ui(ctx)
        imgui.end_child()

    imgui_frame(narrow)
    imgui_frame(lambda: LogPanel(show_header=False).ui(ctx))


def test_pipeline_panel_log_controls_gated_on_log(imgui_frame, monkeypatch):
    """The log's autoscroll/popout icons render only when there's a log to
    control — not orphaned on the Train/Predict row over an empty log."""
    from types import SimpleNamespace

    from myogestic.ml import widgets

    seen: list[str] = []
    real = widgets.render_log_buttons
    monkeypatch.setattr(
        widgets, "render_log_buttons", lambda wid, **k: (seen.append(wid), real(wid, **k))[1]
    )

    def pipe(log):
        ctx = SimpleNamespace(state="idle")
        return SimpleNamespace(
            app=SimpleNamespace(ctx=ctx),
            model=None,
            on_extract=None,
            on_predict=None,
            train_log=log,
        )

    imgui_frame(widgets.PipelinePanel(pipe([]), widget_id="a").ui)
    assert seen == []  # empty log -> no floating controls
    imgui_frame(widgets.PipelinePanel(pipe(["start", "done"]), widget_id="b").ui)
    assert seen == ["b"]  # controls appear once the log has content


def test_process_launcher_renders_wide_and_narrow(imgui_frame):
    """Wide = one row; narrow = the dropdown drops to its own row so Launch and
    the log toggles stay on-panel instead of pushed off the right edge."""
    from imgui_bundle import imgui

    from myogestic.widgets import ProcessLauncher

    pl = ProcessLauncher([("echo", ["echo", "hi"])], widget_id="test_pl")
    imgui_frame(pl.ui)  # wide: one row

    def narrow():
        imgui.begin_child("c", imgui.ImVec2(140.0, 240.0))
        pl.ui()
        imgui.end_child()

    imgui_frame(narrow)  # narrow: dropdown full-width, buttons below


def test_recording_controls_label_buttons_wrap(imgui_frame, monkeypatch):
    """Per-class label buttons wrap onto new rows when they don't fit instead of
    running off the right edge — one row when wide, several when narrow."""
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic.core import AppState
    from myogestic.widgets import RecordingControls

    rows: list[float] = []
    real = imgui.button

    def spy(label, *a, **k):
        if "rec_gesture" in label:
            rows.append(round(imgui.get_cursor_screen_pos().y))
        return real(label, *a, **k)

    monkeypatch.setattr(imgui, "button", spy)
    classes = ["Rest", "Fist", "Open", "Pinch"]

    def draw(w):
        ctx = SimpleNamespace(
            current_label=0, class_names=[], state=AppState.IDLE, session=None, status_message=""
        )
        imgui.begin_child("c", imgui.ImVec2(float(w), 300))
        RecordingControls(classes, on_record=lambda: None, on_stop=lambda: None).ui(ctx)
        imgui.end_child()

    rows.clear()
    imgui_frame(lambda: draw(700))
    assert len(set(rows)) == 1  # all on one row when wide

    rows.clear()
    imgui_frame(lambda: draw(150))
    assert len(set(rows)) > 1  # wrapped onto multiple rows when narrow


def test_session_manager_lists_base_path_sessions(imgui_frame, tmp_path):
    """A SessionManager lists the sessions already in its base_path on first
    render (folder-format sessions with a meta.json), not just after a manual
    file-pick — one-shot, no duplication across frames."""
    import json

    from myogestic.widgets import SessionManager
    from myogestic.widgets.training._session_state import get_state

    for name in ("s1", "s2", "s3"):
        d = tmp_path / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"class_names": ["Rest", "Fist"]}))

    sm = SessionManager(str(tmp_path), class_names=["Rest", "Fist"])
    imgui_frame(sm.ui)
    imgui_frame(sm.ui)  # scan is one-shot -> still 3, not 6
    assert len(get_state(f"Sessions_{tmp_path}").sessions) == 3


def test_session_manager_dedups_same_session_across_path_spellings(tmp_path):
    """The same session picked via a differently-spelled path (symlink, /var vs
    /private/var, ..) dedups against the scanned row instead of doubling."""
    import json
    import zipfile

    from myogestic.widgets.training._session_state import (
        SessionWidgetState,
        load_session_files,
        scan_sessions,
    )

    real = tmp_path / "real"
    real.mkdir()
    with zipfile.ZipFile(real / "s.session.zip", "w") as zf:
        zf.writestr("meta.json", json.dumps({"class_names": ["A"]}))

    st = SessionWidgetState()
    st.sessions = scan_sessions(str(real))  # first-render scan, resolved path
    assert len(st.sessions) == 1
    # the dialog returns the same file via a differently-spelled path
    load_session_files(st, [str(tmp_path / "real" / ".." / "real" / "s.session.zip")])
    assert len(st.sessions) == 1  # deduped, not doubled


def test_channel_scope_is_frozen_at_construction():
    """`Iterable[int]` admits a generator, and the scope is re-read every frame
    — a lazy one would be exhausted after the first, silently emptying the
    panel. It must be snapshotted (and keep its order, which the default
    selection takes a prefix of)."""
    gen = (c for c in [5, 1, 5, 3])
    viewer = SignalViewer("emg", channel_scope=gen)

    assert viewer._channel_scope == (5, 1, 5, 3)  # materialised, order kept
    assert viewer._channel_scope == (5, 1, 5, 3)  # still there on the next frame
    assert SignalViewer("emg")._channel_scope is None  # unrestricted default


class TestTheProcessDotSaysTheState:
    """The header's coloured circle replaced a whole row that said "Stopped".

    The choice is a pure function of the process, which is the point: `_ProcState.stop` sets
    ``process = None``, so a process you killed looks like one never started and therefore
    cannot be reported as a crash — `kill()` leaves a non-zero code behind, and without that
    distinction pressing Stop would turn the dot red.
    """

    @staticmethod
    def _state(process):
        from myogestic.widgets.panels.process_launcher import _ProcState

        state = _ProcState("x", ["true"])
        state.process = process
        return state

    class _Exited:
        def __init__(self, code: int, pid: int = 4242):
            self._code = code
            self.pid = pid

        def poll(self):
            return self._code

    class _Running:
        pid = 1234

        def poll(self):
            return None

    def test_a_process_that_survives_the_kill_is_still_held(self):
        """`stop` must not forget a child SIGKILL failed to take down.

        A process blocked in an uninterruptible kernel wait — which a wedged network
        driver is enough to cause, and VHI's LSL resolver thread is a candidate — ignores
        SIGKILL. Forgetting the handle here made `alive` False and the dot say "Not
        running", so the next Launch stacked a second renderer on a live one.
        """
        import subprocess

        from myogestic.widgets.common import SUCCESS
        from myogestic.widgets.panels.process_launcher import _status_of

        class _Unkillable(self._Running):
            killed = 0

            def kill(self):
                type(self).killed += 1

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("vhi", timeout)

        from myogestic.widgets.common import WARNING

        state = self._state(_Unkillable())
        state.stop()

        assert state.process is not None, "the handle was dropped on a live process"
        assert state.alive, "a process that ignored SIGKILL must still read as alive"

        colour, detail = _status_of(state)
        assert colour is WARNING, "a Stop that did not land must not read as healthy"
        assert colour is not SUCCESS
        assert "has not died" in detail

        state.start()  # the next Launch must refuse rather than spawn a second one
        assert isinstance(state.process, _Unkillable)

        state.stop()  # and Stop stays usable, so the kill can be retried
        assert _Unkillable.killed == 2

    def test_a_kill_that_lands_late_is_stopped_not_a_crash(self):
        """SIGKILL leaves a non-zero code; that must not be reported as a crash.

        `stop` only waits 200 ms, so a process that dies just after it gives up is still
        held — with the -9 of the signal that killed it. Without `_kill_wanted` the dot
        would go red and say the renderer had crashed on its own.
        """
        import subprocess

        from myogestic.widgets.common import DANGER, IDLE
        from myogestic.widgets.panels.process_launcher import _status_of

        class _DiesLate(self._Running):
            def kill(self):
                pass

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("vhi", timeout)

        state = self._state(_DiesLate())
        state.stop()
        state.process.poll = lambda: -9  # it died, just not while stop was waiting

        colour, detail = _status_of(state)
        assert colour is IDLE, "a deliberate kill is not a crash"
        assert colour is not DANGER
        assert detail == "Stopped."

    def test_never_started_is_idle(self):
        from myogestic.widgets.common import IDLE
        from myogestic.widgets.panels.process_launcher import _status_of

        colour, detail = _status_of(self._state(None))
        assert colour is IDLE
        assert "Not running" in detail

    def test_running_is_success_and_says_the_pid(self):
        from myogestic.widgets.common import SUCCESS
        from myogestic.widgets.panels.process_launcher import _status_of

        colour, detail = _status_of(self._state(self._Running()))
        assert colour is SUCCESS
        assert "1234" in detail

    def test_a_bad_exit_is_danger_and_says_the_code(self):
        from myogestic.widgets.common import DANGER
        from myogestic.widgets.panels.process_launcher import _status_of

        colour, detail = _status_of(self._state(self._Exited(1)))
        assert colour is DANGER
        assert "code 1" in detail

    def test_a_clean_exit_is_not_an_error(self):
        from myogestic.widgets.common import IDLE
        from myogestic.widgets.panels.process_launcher import _status_of

        colour, _ = _status_of(self._state(self._Exited(0)))
        assert colour is IDLE

    def test_pressing_stop_does_not_look_like_a_crash(self):
        """The case the three states exist for. `kill()` leaves a non-zero code, so this
        would be red if `stop` did not null the process."""
        from myogestic.widgets.common import IDLE
        from myogestic.widgets.panels.process_launcher import _ProcState, _status_of

        state = _ProcState("x", ["true"])
        state.process = self._Exited(-9)          # SIGKILL, as `stop` leaves it
        state.process = None                      # ...which `stop` then clears
        assert _status_of(state)[0] is IDLE


def test_the_launcher_draws_no_inline_log_by_default():
    """Its whole appeal is being two rows. The log is in the popout."""
    import inspect

    from myogestic.widgets.panels import process_launcher

    source = inspect.getsource(process_launcher._render_process_launcher)
    assert "if log_height > 0" in source, "an inline log must be opt-in"
    # The removed *call*, not the word: the docstring explains what the dot replaced and
    # would match a naive search for it.
    assert "imgui.text_colored(IDLE" not in source
    assert "status=dot" in source, "the header carries the state now"
