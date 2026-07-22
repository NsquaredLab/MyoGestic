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
    """The same session picked via a non-canonical path (symlink, /var vs
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
    st.sessions = scan_sessions(str(real))  # first-render scan, canonical path
    assert len(st.sessions) == 1
    # the dialog returns the same file via a non-canonical spelling
    load_session_files(st, [str(tmp_path / "real" / ".." / "real" / "s.session.zip")])
    assert len(st.sessions) == 1  # deduped, not doubled
