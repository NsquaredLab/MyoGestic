"""Smoke-test the example scripts against the real API.

Each ``examples/synthetic/*.py`` does its wiring at import / ``__main__`` time
(``App``, ``Stream``, ``Pipeline``, ``@pipeline.train``/``predict`` decorators,
widget hookup, ``iter_*_windows`` calls inside callbacks) and then ends in
``app.run()``, which blocks on the Dear ImGui event loop. We stub ``App.run`` so
the script returns right after wiring everything up — exercising the example
against the current public API (catching renamed kwargs / moved imports / wrong
attributes) without opening a window or needing hardware.

Examples that top-import an uninstalled optional dep (``torch`` / ``myoverse``
for the RaulNet / MyoVerse examples) are skipped, so this runs in lean CI for the
dependency-free examples and fully wherever the ``examples`` extra is installed.

Run locally: ``uv run pytest tests/test_examples.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

import myogestic.core
import myogestic.vhi.interfaces

_EXAMPLES_ROOT = Path(__file__).resolve().parent.parent / "examples"
# `panels/*.py` are single-widget demos; underscore-prefixed files are skipped
# as shared helpers rather than examples.
#
# `reference_target.py` is not a MyoGestic App: it is a target, the thing an App
# drives. Its `__main__` serves forever (there is no `App.run` to stub), and
# `tests/test_reference_target.py` already runs it for real, driven by a live
# `ControlBus` — a stronger check than "does it wire up" ever gives the App examples.
# `start_here/` is in the list, `examples/otb/` is not, and the line between them is
# **construct vs connect** — not which folder a file sits in. A `start_here/` app seeds
# its stream with `DEFAULT_DEVICES[0].factory()`, which is a Muovi: the same OTB class,
# merely not dialled. `MuoviSource.__init__` opens no socket, so importing it costs
# nothing. Every `otb/` script *connects* at import and would hang CI waiting for an
# amplifier. A default that connects in its constructor would break this list wherever
# it lived.
#
# `""` — the root of `examples/` — is kept although nothing lives there now, so a script
# dropped in beside the folders is covered rather than quietly untested. That is the
# failure this list has already had once: moving the flagship example down into
# `start_here/` took it out of the glob, and the only sign was two tests fewer.
EXAMPLES = sorted(
    p
    for sub in ("", "start_here", "synthetic", "panels")
    for p in (_EXAMPLES_ROOT / sub).glob("*.py")
    if not p.name.startswith("_") and p.name != "reference_target.py"
)


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=f"{p.parent.name}/{p.name}") for p in EXAMPLES]
)
def test_example_wires_up(path, monkeypatch):
    """Run an example with the GUI loop stubbed; any API-wiring error fails."""
    # The GUI (and headless) run loop blocks forever — replace it with a no-op so
    # the script completes right after building the app.
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    # An example may import a sibling module; running via runpy (unlike a real
    # `python examples/panels/foo.py`) doesn't put the script's own directory on
    # sys.path, so add it.
    monkeypatch.syspath_prepend(str(path.parent))
    # Examples call `vhi.launcher()` at module level, which raises FileNotFoundError
    # unless the VHI binary is installed (an environment dep, not part of the API
    # surface). Stub the env check to []; a renamed/removed `launcher` method would
    # still raise AttributeError and fail the test.
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    try:
        runpy.run_path(str(path), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"optional dependency missing for {path.name}: {e}")


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=f"{p.parent.name}/{p.name}") for p in EXAMPLES]
)
def test_example_draws_a_frame(path, monkeypatch, implot_frame):
    """Wiring up is not the same as drawing, and the crashes live in drawing.

    `test_example_wires_up` stubs `App.run`, so every `@app.ui` callback in every
    example is built and never called. That is most of an example: the widget calls
    with their keyword arguments, which is exactly the surface that moves under them.
    Two shipped examples were calling `render_log_buttons(autoscroll=...)` long after
    that argument was removed, and unpacking two values from a function returning one
    — a `TypeError` on the first frame, in a suite that was green, because the frame
    never happened.

    One layout pass is enough: it is the pass that resolves every call.
    """
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.syspath_prepend(str(path.parent))
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    try:
        namespace = runpy.run_path(str(path), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"optional dependency missing for {path.name}: {e}")

    app = next(
        (v for v in namespace.values() if isinstance(v, myogestic.core.App)), None
    )
    if app is None:
        pytest.skip(f"{path.name} builds no App")

    # Both registration routes, or this covers whichever half an example did not use.
    # The crash that prompted this test was in a `app.popout(...)` block, and a first
    # version of it drew only `@app.ui` — so it skipped that file and reported green.
    draws = [app._ui_fn] if app._ui_fn is not None else []
    draws += [gui_fn for _title, gui_fn, *_rest in app._popout_specs]
    if not draws:
        pytest.skip(f"{path.name} registers no UI callback")

    panel_demo = path.parent.name == "panels"
    if panel_demo:
        from imgui_bundle import imgui

        from myogestic import _scale, _theme

        monkeypatch.setattr(_scale, "_current", 2.0)
        monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
        _theme.apply_theme()
        imgui.get_style().scale_all_sizes(2.0)
        imgui.get_style().font_scale_main = 2.0
        imgui.get_io().display_size = imgui.ImVec2(360, 1800)

    def draw_all() -> None:
        if panel_demo:
            imgui.set_next_window_pos(imgui.ImVec2(0, 0))
            imgui.set_next_window_size(imgui.ImVec2(320, 1800))
            imgui.begin("narrow-panel-demo", flags=imgui.WindowFlags_.no_saved_settings)
        for fn in draws:
            fn(app.ctx) if fn is app._ui_fn else fn()
        if panel_demo:
            imgui.end()

    try:
        implot_frame(draw_all)
    except RuntimeError as exc:
        # A layout pass is not a runner. `ImageBox` asks HelloImGui for the params
        # only `HelloImGui::Run()` creates, so it cannot draw without a real window
        # — narrowly skipped, because every *other* RuntimeError is a finding.
        if "HelloImGui" not in str(exc):
            raise
        pytest.skip(f"{path.name} needs a real runner, not a layout pass: {exc}")


def test_examples_survive_an_unlaunchable_target(monkeypatch):
    """An app must open even when VHI cannot be launched from inside it.

    This is deliberately *not* covered by the stub above. `test_example_wires_up`
    replaces `launcher` with a no-op so a machine without VHI installed can still run
    the suite — and that stub also hid a real crash: with a pre-2.0 release on disk,
    `launcher()` raises, and every example that splatted it into a `ProcessLauncher` died
    at import. Including when a perfectly good v2 target was already running and the
    app never needed the button.

    So here the refusal is what gets simulated, not what gets stubbed away.
    """
    import myogestic.vhi.interfaces  # noqa: PLC0415

    def refuse(self):
        raise FileNotFoundError(f"{self.name}: the installed release is v1.0.0")

    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", refuse)

    vhi_examples = [
        path
        for path in EXAMPLES
        if "vhi" in path.read_text(encoding="utf-8")
        and path.parent.name in {"synthetic", "start_here"}
    ]
    assert vhi_examples, "no VHI examples found — has the layout moved?"
    for path in vhi_examples:
        monkeypatch.syspath_prepend(str(path.parent))
        try:
            runpy.run_path(str(path), run_name="__main__")
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.skip(f"optional dependency missing for {path.name}: {exc}")
        except FileNotFoundError as exc:  # pragma: no cover - the bug this pins
            pytest.fail(
                f"{path.name} does not open when VHI cannot be launched: {exc}. "
                f"Use `vhi.launchable()` rather than `vhi.launcher()` for a "
                f"ProcessLauncher row."
            )


def test_every_example_outside_otb_is_in_the_list():
    """A folder added under `examples/` is otherwise silently untested.

    `EXAMPLES` names its folders, so adding one and not naming it here costs nothing
    visible — the suite still passes, with fewer tests in it. That is precisely how the
    flagship example lost both of its checks when it moved into `start_here/`: green
    run, two tests gone, no failure to read.
    """
    covered = {p.resolve() for p in EXAMPLES}
    found = {
        p.resolve()
        for p in _EXAMPLES_ROOT.rglob("*.py")
        if "otb" not in p.relative_to(_EXAMPLES_ROOT).parts
        and "__pycache__" not in p.parts
        and not p.name.startswith("_")
        and p.name != "reference_target.py"
    }

    missing = sorted(str(p.relative_to(_EXAMPLES_ROOT)) for p in found - covered)

    assert not missing, (
        "Example(s) no test runs:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd the folder to EXAMPLES above, or exclude it deliberately the way "
        "`otb/` is — with the reason written down."
    )


@pytest.mark.parametrize("name", ["control_map_studio", "vhi_control_hand"])
@pytest.mark.parametrize("scale", [1.0, 2.0])
@pytest.mark.parametrize("connected", [False, True])
def test_control_example_cards_fit_and_explain_their_state(
    name, scale, connected, monkeypatch, imgui_frame,
):
    """Exercise the local cards at 320 px, including an unlaunchable hand."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets import common

    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / f"{name}.py"))
    draw_ui = namespace["app"]._ui_fn
    scope = draw_ui.__globals__
    monkeypatch.setattr(_scale, "_current", scale)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(scale)
    imgui.get_style().font_scale_main = scale
    monkeypatch.setattr(scope["header"], "ui", lambda ctx: None)
    monkeypatch.setattr(scope["processes"], "ui", lambda: None)
    bus = SimpleNamespace(push=lambda values: None) if connected else None
    if name == "control_map_studio":
        monkeypatch.setitem(scope, "bus", bus)
        monkeypatch.setitem(scope, "levels", {"close": 0.5} if connected else {})
        monkeypatch.setitem(scope, "states", {})
        monkeypatch.setitem(scope, "status", "Driving close." if connected else "Press Connect.")
        monkeypatch.setitem(scope, "keys", SimpleNamespace(claims=set(), armed=False, arm_refusal="Access required."))
        monkeypatch.setitem(scope, "_tabs_ui", lambda: None)
        monkeypatch.setitem(scope, "_rebuild_if_the_manifest_changed", lambda: None)
        monkeypatch.setitem(scope, "editor", lambda: SimpleNamespace(label="Untitled", ui=lambda: False))
    else:
        monkeypatch.setitem(scope, "link", SimpleNamespace(bus=bus))
    headers, rows, primary, texts, overhangs = [], [], [], [], []
    cell, bounds = {}, {}

    class Cells:
        @contextmanager
        def __getitem__(self, key):
            cell["key"] = str(key)
            imgui.set_cursor_pos(imgui.ImVec2(0, 0))
            imgui.begin_child(f"cell-{key}", imgui.ImVec2(320, 400))
            bounds["left"] = imgui.get_cursor_screen_pos().x
            bounds["right"] = bounds["left"] + imgui.get_content_region_avail().x
            yield
            imgui.end_child()

        area = __getitem__

    monkeypatch.setitem(scope, "layout" if name == "control_map_studio" else "grid", Cells())
    original_button, original_wrapped = imgui.button, imgui.text_wrapped

    def header(title, **kwargs):
        headers.append((cell["key"], title, kwargs.get("status")))
        common.panel_header(title, **kwargs)

    @contextmanager
    def row(tone=None, **kwargs):
        rows.append((cell["key"], tone))
        with common.tinted_row(tone, **kwargs) as width:
            yield width

    def forward(label, size=(0, 0)):
        result = common.primary_button(label, size)
        primary.append((cell["key"], label, imgui.get_item_rect_size().x,
                        bounds["right"] - bounds["left"]))
        return result

    def button(label, *args):
        result = original_button(label, *args)
        overhangs.append(imgui.get_item_rect_max().x - bounds["right"])
        return result

    def wrapped(text):
        texts.append(text)
        original_wrapped(text)

    monkeypatch.setitem(scope, "panel_header", header)
    monkeypatch.setitem(scope, "tinted_row", row)
    monkeypatch.setitem(scope, "primary_button", forward)
    monkeypatch.setattr(imgui, "button", button)
    monkeypatch.setattr(imgui, "text_wrapped", wrapped)
    imgui_frame(lambda: draw_ui(scope["app"].ctx))
    assert headers and len({key for key, _, _ in headers}) == len(headers), "one header per card"
    assert rows, "the connection state belongs in a tinted row"
    assert primary and all(width == pytest.approx(room, abs=1) for _, _, width, room in primary)
    assert max(overhangs) <= 1, "actions must stay reachable in a narrow cell"
    tone = common.SUCCESS if connected else common.IDLE
    assert headers[0][2] == tone and rows[0][1] == tone
    if name == "control_map_studio":
        assert next(tone for _, title, tone in headers if title == "KEYBOARD") == common.IDLE
    if not connected:
        assert any("Connect" in text or "Launch" in text for text in texts), "show the next step"

@pytest.mark.parametrize("name,label", [
    ("participant_panel", "Recording"),
    ("step_bar", "Complete"),
    ("pong", "Follow"),
])
def test_panel_demo_chips_toggle_without_leaking_selection(
    monkeypatch, implot_frame, name, label,
):
    """Demo toggles stay paired on the actual frames that switch on and off."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(360, 1800)
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "panels" / f"{name}.py"))
    app = namespace["app"]
    if name == "step_bar":
        namespace["steps"].active = 1
    button = imgui.small_button
    clicked = []

    def click_chip(text):
        result = button(text)
        if text.split("##")[0] == label:
            clicked.append((
                imgui.get_item_rect_max().x,
                imgui.get_window_pos().x + imgui.get_window_size().x,
            ))
            return True
        return result

    monkeypatch.setattr(imgui, "small_button", click_chip)

    def enabled():
        if name == "participant_panel":
            return app.ctx.state == "recording"
        if name == "step_bar":
            return namespace["done"][namespace["steps"].active]
        return app._ui_fn.__globals__["started"] is not None

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(320, 1800))
        imgui.begin("demo-chip", flags=imgui.WindowFlags_.no_saved_settings)
        app._ui_fn(app.ctx)
        imgui.end()

    for expected in (True, False):
        implot_frame(draw)
        assert enabled() is expected
    assert len(clicked) == 2
    assert all(right <= edge for right, edge in clicked), clicked


@pytest.mark.parametrize("name,captions", [
    ("pong", ["Command", "Opponent"]),
    ("tracking_task", ["Effort"]),
])
@pytest.mark.parametrize("width", [320, 1200])
def test_panel_demo_inputs_fit_with_captions_at_large_scale(
    monkeypatch, implot_frame, name, captions, width,
):
    """Demo sliders stack their captions and stay reachable in a narrow light card."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width + 40, 1800)
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "panels" / f"{name}.py"))
    app = namespace["app"]
    slider, text = imgui.slider_float, imgui.text_colored
    labels, controls, readouts = {}, {}, []
    mono = app._ui_fn.__globals__["mono_text"]

    def readout(value):
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        mono(value)
        readouts.append((value, imgui.get_item_rect_max().x, right))

    def caption(color, value):
        text(color, value)
        if value in captions:
            labels[value] = tuple(imgui.get_item_rect_min())

    def track_slider(label, *args, **kwargs):
        result = slider(label, *args, **kwargs)
        key = label.lstrip("#").capitalize()
        if key in captions:
            edge = imgui.get_window_pos().x + imgui.get_window_size().x
            controls[key] = (
                label, tuple(imgui.get_item_rect_min()), tuple(imgui.get_item_rect_max()), edge,
            )
        return result

    monkeypatch.setattr(imgui, "text_colored", caption)
    monkeypatch.setattr(imgui, "slider_float", track_slider)
    monkeypatch.setitem(app._ui_fn.__globals__, "mono_text", readout)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1800))
        imgui.begin("panel-demo", flags=imgui.WindowFlags_.no_saved_settings)
        app._ui_fn(app.ctx)
        imgui.end()

    try:
        for _ in range(3):
            implot_frame(draw)
        assert set(labels) == set(controls) == set(captions)
        assert all(right <= edge for _, right, edge in readouts), readouts
        for key, (label, lo, hi, edge) in controls.items():
            assert label.startswith("##"), "captions belong above controls, not beside them"
            assert labels[key][1] < lo[1]
            assert hi[0] <= edge
        if width == 320:
            assert len({round(lo[0]) for _, lo, _, _ in controls.values()}) == 1
    finally:
        for stream in app.ctx.streams.values():
            stream.stop()




@pytest.mark.parametrize("name", ["force_ramps", "pong"])
def test_start_here_picker_owns_device_streams(name, monkeypatch, implot_frame):
    """Adding an amplifier stays beside Source and cannot replace the target."""
    from imgui_bundle import imgui

    monkeypatch.setattr(myogestic.core.App, "run", lambda self: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "start_here" / f"{name}.py"))
    app, picker = namespace["app"], namespace["device"]
    assert picker._on_add is not None and picker._on_remove is not None
    assert "target" in picker._excluded
    target = app.ctx.streams["target"]
    picker._on_add("second")
    assert app.ctx.streams["second"]._window == namespace["WINDOW_MS"] / 1000
    picker._on_remove("second")
    assert "second" not in app.ctx.streams and app.ctx.streams["target"] is target
    tabs = []
    begin_tab = imgui.begin_tab_item

    def track_tab(label, *args, **kwargs):
        tabs.append(label)
        return begin_tab(label, *args, **kwargs)

    monkeypatch.setattr(imgui, "begin_tab_item", track_tab)
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert "Streams" not in tabs
    assert tabs == []


@pytest.mark.parametrize("name", ["force_ramps", "pong", "myocontrol"])
def test_start_here_source_card_fits_narrow_light_cell(name, monkeypatch, implot_frame):
    """The source card remains readable at scale two with no device attached."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "start_here" / f"{name}.py"))
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    overflow = []

    def draw():
        imgui.begin_child("source-probe", imgui.ImVec2(320, 1000),
                          window_flags=imgui.WindowFlags_.horizontal_scrollbar)
        namespace["device"].ui(namespace["app"].ctx)
        overflow.append(imgui.get_scroll_max_x())
        imgui.end_child()

    for _ in range(4):
        implot_frame(draw)
    assert overflow[-1] == 0, overflow


@pytest.mark.parametrize("name", ["force_ramps", "pong"])
@pytest.mark.parametrize("participant", ["", "P-014"])
def test_start_here_recording_fits_default_grid(name, participant, monkeypatch, implot_frame):
    """Recording's explanation and gesture buttons must fit the actual grid row."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "start_here" / f"{name}.py"))
    app = namespace["app"]
    app.ctx.participant = participant
    namespace["steps"].active = 1
    if name == "pong":
        namespace["record_protocol"]["index"] = 1
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(2560, 1656)
    recording = namespace["recording"]
    render = type(recording).ui
    measurements = []

    def measured(self, ctx, **kwargs):
        render(self, ctx, **kwargs)
        measurements.append((imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                             imgui.get_scroll_max_y()))

    monkeypatch.setattr(type(recording), "ui", measured)

    def draw():
        imgui.set_next_window_size(imgui.ImVec2(2560, 1656))
        imgui.begin("start-here-grid")
        app._ui_fn(app.ctx)
        imgui.end()

    for _ in range(4):
        implot_frame(draw)
    cursor, height, scroll = measurements[-1]
    assert cursor <= height and scroll == 0, measurements


@pytest.fixture
def classification_app(monkeypatch, tmp_path):
    """Wire the classification workflow without launching its external targets."""
    from types import SimpleNamespace

    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda x: None))
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / "emg_classification.py"))
    streams = tuple(namespace["app"].ctx.streams.values())
    try:
        yield namespace
    finally:
        namespace["link"].stop()
        namespace["vhi_control"].stop()
        for stream in streams:
            stream.stop()


def test_classification_uses_the_session_shell(classification_app):
    """One header and active step surround a persistent signal and sessions."""
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, SimulatorControls, StatusBar

    ns = classification_app
    layout, header, steps = (ns[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "EMG classification"
    assert header.steps is steps and header.participant is ns["participant"]
    assert steps.steps == ["Connect", "Record", "Train", "Predict"]
    assert steps._widget_id == "emg_classification_steps"
    assert isinstance(ns["status"], StatusBar) and ns["status"].pipeline is ns["pipeline"]
    assert isinstance(ns["simulator"], SimulatorControls)
    assert "ctrl_outlet" not in ns
    assert ns["app"].ctx.require_participant
    assert not ns["recording"]._show_header and not ns["features"]._show_header
    assert layout.panel_names == {"header", "signal", "simulator", "step", "sessions", "log", "status"}
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._wide._areas == {
        "header": (0, 1, 0, 2), "signal": (1, 3, 0, 1),
        "step": (1, 2, 1, 2), "sessions": (2, 5, 1, 2),
        "simulator": (3, 4, 0, 1), "log": (4, 5, 0, 1), "status": (5, 6, 0, 2),
    }
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        signal, simulator = grid._areas["signal"], grid._areas["simulator"]
        assert simulator[0] == signal[1] and simulator[2:] == signal[2:]
        assert grid._row_tracks[simulator[0]] == Px(76)


def test_classification_completion_tracks_the_participants_takes(classification_app, monkeypatch, tmp_path):
    from types import SimpleNamespace

    ns = classification_app
    ctx, done = ns["app"].ctx, ns["_step_done"]
    assert done(ctx) == [False] * 4
    ctx.participant = "P-014"
    monkeypatch.setitem(ctx.streams, "emg", SimpleNamespace(status="connected", info=object()))
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone-else_take.session.zip").touch()
    assert done(ctx) == [True, False, False, False]
    (folder / "P-014_take.session.zip").touch()
    ns["pipeline"].model = object()
    ctx.state = "predicting"
    assert done(ctx) == [True] * 4
    ctx.streams["emg"].info = None
    ctx.participant = "P-015"
    assert done(ctx) == [False, False, True, True]


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("width", [2560, 1800])
@pytest.mark.parametrize("participant", ["", "P-014"])
@pytest.mark.parametrize("trained", [False, True])
@pytest.mark.parametrize("recording_active", [False, True])
def test_classification_shell_fits_light_theme(
    classification_app, monkeypatch, implot_frame, step, width, participant, trained, recording_active,
):
    """Every active card fits the default window; narrow cards remain reachable."""
    import platform

    from imgui_bundle import hello_imgui, imgui

    from myogestic import _scale, _theme
    from myogestic.ml import widgets as ml_widgets
    from myogestic.widgets.panels import process_launcher, recording
    from myogestic.widgets.signals import simulator_controls
    from myogestic.widgets.training import feature_selector

    ns = classification_app
    app = ns["app"]
    app.ctx.participant = participant
    ns["steps"].active = step
    if trained:
        ns["pipeline"].model = object()
        ns["pipeline"].train_log.append("Trained on 100 windows from 2 sessions.")
        ns["pipeline"].predictions.update({"class": 1, "proba": [0.1, 0.9]})
        app.ctx.state = "predicting" if step == 3 else "idle"
    if recording_active:
        app.ctx.state = "recording"
    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    # The app uses a proportional body face. The fixture's monospace default
    # makes ordinary session guidance 45% wider than the real control surface.
    font_path = Path(_theme._SYS_FONTS.get(platform.system(), ""))
    if not font_path.is_file():
        font_path = Path(hello_imgui.asset_file_full_path("fonts/Roboto/Roboto-Regular.ttf"))
    imgui.get_io().font_default = imgui.get_io().fonts.add_font_from_file_ttf(str(font_path), 14)
    font_dir = _EXAMPLES_ROOT.parent / "myogestic" / "assets" / "fonts"
    for attr, filename, size in (("_MONO_FONT", "IBMPlexMono-Regular.ttf", 13),
                                 ("_DISPLAY_FONT", "InstrumentSerif-Regular.ttf", 28)):
        font = imgui.get_io().fonts.add_font_from_file_ttf(str(font_dir / filename), size)
        monkeypatch.setattr(_theme, attr, font)
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    headers, views, cells, buttons, heights = [], [], [], [], {}
    original_header = ns["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original_header(title, *args, **kwargs)

    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    for module in (ml_widgets, process_launcher, recording, feature_selector, simulator_controls):
        monkeypatch.setattr(module, "panel_header", header)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the shell has no tabs"))
    original_button = imgui.button

    def button(label, *args, **kwargs):
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = original_button(label, *args, **kwargs)
        buttons.append((label, imgui.get_item_rect_max().x - right))
        return result

    monkeypatch.setattr(imgui, "button", button)
    original_chip = imgui.small_button

    def chip(label):
        right = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = original_chip(label)
        buttons.append((label, imgui.get_item_rect_max().x - right))
        return result

    monkeypatch.setattr(imgui, "small_button", chip)
    render_connect = ns["connect_ui"]

    def connect(ctx):
        render_connect(ctx)
        cells.append(("connect", imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                      imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))

    monkeypatch.setitem(app._ui_fn.__globals__, "connect_ui", connect)
    for name in ("viewer", "simulator", "recording", "features", "train_button", "training_log",
                 "prediction", "predict_button", "output_filter", "sessions", "log", "status"):
        widget = ns[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append((name, kwargs))
            result = render(self, *args, **kwargs)
            if kwargs.get("visible", True) and name != "status":
                heights[name] = imgui.get_window_size().y
                cells.append((name, imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                              imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
            return result

        monkeypatch.setattr(type(widget), "ui", view)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("classification-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        assert imgui.get_scroll_max_x() == imgui.get_scroll_max_y() == 0
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        cells.clear()
        buttons.clear()
        implot_frame(draw)
    assert headers == [ns["steps"].steps[step], "Simulated EMG"]
    expected = {"viewer", "simulator", "recording", "sessions", "log", "status"}
    expected |= {2: {"features", "train_button", "training_log"},
                 3: {"prediction", "predict_button", "output_filter"}}.get(step, set())
    assert {name for name, _ in views} == expected
    record_calls = [kwargs for name, kwargs in views if name == "recording"]
    assert len(record_calls) == 1
    assert record_calls[0].get("visible", True) == (step == 1)
    assert next(kwargs for name, kwargs in views if name == "sessions") == {"participant": participant}
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(horizontal == 0 for _, _, _, horizontal, _ in cells), cells
    assert heights["viewer"] > heights["simulator"]
    assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
               for name, cursor, height, _, vertical in cells if name == "simulator"), cells
    if width == 2560:
        assert all(cursor - imgui.get_style().item_spacing.y <= height and vertical == 0
                   for _, cursor, height, _, vertical in cells), cells
    assert ns["layout"]._active is (ns["layout"]._wide if width == 2560 else ns["layout"]._narrow)


def test_classification_recording_callbacks_keep_the_generator_and_hand_wiring(classification_app, monkeypatch):
    """The new step only moves controls; the same callbacks label and capture."""
    import numpy as np

    from myogestic.tools import emg_generator

    ns = classification_app
    calls = []
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: calls.append("bind"))
    outlet = emg_generator.control_outlet()
    monkeypatch.setattr(outlet, "push_sample", lambda value: calls.append(value))
    monkeypatch.setattr(emg_generator, "control_outlet", lambda: outlet)
    monkeypatch.setattr(ns["app"], "start_recording", lambda: calls.append("record"))
    ns["_on_gesture"](1)
    assert calls[0] == "bind"
    np.testing.assert_array_equal(calls[1], np.array([1.0], dtype=np.float32))
    assert ns["simulator"].value == 1.0
    calls.clear()
    ns["_on_record"]()
    assert calls == ["bind", "record"]
    # Previewing another signal must not change the gesture of the next take.
    calls.clear()
    ns["app"].ctx.current_label = 0
    ns["_on_record"]()
    assert calls[0] == "bind" and calls[2] == "record"
    np.testing.assert_array_equal(calls[1], np.array([0.0], dtype=np.float32))
    assert ns["simulator"].value == 0.0


@pytest.mark.parametrize("step", range(4))
@pytest.mark.parametrize("state", ["idle", "recording", "predicting"])
def test_classification_simulator_steers_each_step_and_defers_to_recording(
    classification_app, monkeypatch, implot_frame, step, state,
):
    """The persistent chips drive only the signal, and recording can still set it."""
    from imgui_bundle import imgui

    ns = classification_app
    ns["steps"].active = step
    ns["app"].ctx.state = state
    # Establish the lazy outlet, then observe the samples without touching LSL.
    ns["simulator"].set(0.0)
    samples, chips = [], []
    monkeypatch.setattr(ns["simulator"]._outlet, "push_sample", lambda value: samples.append(value))
    button = imgui.small_button

    def click(label):
        result = button(label)
        if "##preset_" in label:
            disabled = bool(imgui.get_item_flags() & imgui.ItemFlags_.disabled)
            chips.append((label.split("##")[0], disabled))
            return label.startswith("Fist##") and not disabled
        return result

    monkeypatch.setattr(imgui, "small_button", click)
    implot_frame(lambda: ns["app"]._ui_fn(ns["app"].ctx))
    assert chips == [("Rest", state == "recording"), ("Fist", state == "recording")]
    assert ns["simulator"].value == (0.0 if state == "recording" else 1.0)
    assert len(samples) == (0 if state == "recording" else 1)
    assert ns["app"].ctx.current_label == -1
    monkeypatch.setattr(type(ns["link"]), "ensure", lambda self: None)
    ns["_on_gesture"](1)
    assert ns["simulator"].value == 1.0


@pytest.fixture
def force_app(monkeypatch, tmp_path):
    """Wire the force protocol without a runner, and release all its streams."""
    monkeypatch.chdir(tmp_path)
    namespace = runpy.run_path(str(_EXAMPLES_ROOT / "start_here" / "force_ramps.py"))
    streams = tuple(namespace["app"].ctx.streams.values())
    try:
        yield namespace
    finally:
        app = namespace["app"]
        if app.ctx.state == "recording":
            app.discard_recording()
        for stream in streams:
            stream.stop()


def test_force_ramps_uses_the_session_shell(force_app):
    """Navigation owns the participant; the target stays outside Source."""
    from myogestic import Fr, Px
    from myogestic.widgets import AppHeader, RecordButton, StatusBar

    layout, header, steps = (force_app[name] for name in ("layout", "header", "steps"))
    assert isinstance(header, AppHeader) and header.title == "Force ramps"
    assert header.steps is steps and header.participant is force_app["participant"]
    assert steps.steps == ["Connect", "Track"] and steps._widget_id == "force_ramps_steps"
    assert isinstance(force_app["status"], StatusBar) and force_app["status"].pipeline is None
    assert isinstance(force_app["recording"], RecordButton)
    assert not force_app["recording"]._show_header and not force_app["device"]._show_header
    assert force_app["device"]._selectable and force_app["device"]._excluded == {"target"}
    assert force_app["tracking"]._target is force_app["target"]
    assert force_app["tracking"]._stream_name == "force"
    assert force_app["target_stream"].info is not None
    assert force_app["emg"].info is None and force_app["force_stream"].info is None
    assert layout.panel_names == {"header", "signal", "step", "sessions", "log", "status"}
    assert layout._breakpoint == Px(1100)
    assert layout._wide._col_tracks == [Fr(1), Px(400)]
    assert layout._narrow._row_tracks[1] == Px(500)
    assert layout._wide._areas == {
        "header": (0, 1, 0, 2), "signal": (1, 3, 0, 1),
        "step": (1, 2, 1, 2), "sessions": (2, 4, 1, 2), "log": (3, 4, 0, 1),
        "status": (4, 5, 0, 2),
    }
    for grid in (layout._wide, layout._narrow):
        assert grid._bare == {"header", "status"}
        assert grid._row_tracks[0] == Px(52) and grid._row_tracks[-1] == Px(26)
        assert grid._areas["status"] == (grid.rows - 1, grid.rows, 0, grid.cols)


def test_force_completion_needs_both_devices_and_participant_takes(force_app, monkeypatch, tmp_path):
    from types import SimpleNamespace

    ctx, done = force_app["app"].ctx, force_app["_step_done"]
    assert done(ctx) == [False, False]
    ctx.participant = "P-014"
    for name in ("emg", "force"):
        monkeypatch.setitem(ctx.streams, name, SimpleNamespace(status="connected", info=object()))
        assert done(ctx) == [name == "force", False]
    folder = tmp_path / "sessions" / ctx.participant
    folder.mkdir(parents=True)
    (folder / "someone-else_take.session.zip").touch()
    assert done(ctx) == [True, False]
    (folder / "P-014_take.session.zip").touch()
    assert done(ctx) == [True, True]
    ctx.streams["force"].info = None
    assert done(ctx) == [False, True]
    ctx.participant = "another-participant"
    assert done(ctx) == [False, False]


@pytest.mark.parametrize("step", [0, 1])
@pytest.mark.parametrize("width", [2560, 1800])
@pytest.mark.parametrize("participant", ["", "P-014"])
@pytest.mark.parametrize("state", ["disconnected", "calibrated", "running"])
def test_force_shell_draws_the_active_cards_in_light_theme(
    force_app, monkeypatch, implot_frame, step, width, participant, state,
):
    """Exercise both views at scale two in the default and narrow shell."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme
    from myogestic.widgets import tracking
    from myogestic.widgets.panels import recording

    monkeypatch.setattr(_scale, "_current", 2.0)
    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0
    imgui.get_io().display_size = imgui.ImVec2(width, 1656)
    app = force_app["app"]
    app.ctx.participant = participant
    force_app["steps"].active = step
    if state != "disconnected":
        for name in ("emg", "force"):
            stream = app.ctx.streams[name]
            monkeypatch.setattr(stream, "_source", force_app["SyntheticForceSource"]())
            assert stream.reconnect()
            stream._acquire_step()
        force_app["tracking"]._zero, force_app["tracking"]._mvc = 0.3, 2.3
        if state == "running":
            force_app["tracking"]._start()
    headers, views, buttons, scroll, cells, record_bounds = [], [], [], [], [], []
    original = force_app["panel_header"]

    def header(title, *args, **kwargs):
        headers.append(title)
        return original(title, *args, **kwargs)

    button = imgui.button

    def measure_button(label, *args, **kwargs):
        edge = imgui.get_cursor_screen_pos().x + imgui.get_content_region_avail().x
        result = button(label, *args, **kwargs)
        buttons.append((label, imgui.get_item_rect_max().x - edge))
        if label.endswith("  Record") and width == 1800:
            draw = imgui.get_window_draw_list()
            record_bounds[:] = [imgui.get_item_rect_min().y, imgui.get_item_rect_max().y,
                                draw.get_clip_rect_min().y, draw.get_clip_rect_max().y]
            imgui.set_scroll_here_y(0.5)
        return result

    monkeypatch.setattr(imgui, "button", measure_button)
    monkeypatch.setattr(imgui, "begin_tab_bar", lambda *a: pytest.fail("the force shell has no tabs"))
    monkeypatch.setitem(app._ui_fn.__globals__, "panel_header", header)
    monkeypatch.setattr(tracking, "panel_header", header)
    monkeypatch.setattr(recording, "panel_header", header)
    for name in ("viewer", "tracking", "recording", "device", "status"):
        widget = force_app[name]
        render = type(widget).ui

        def view(self, *args, name=name, render=render, **kwargs):
            views.append(name)
            result = render(self, *args, **kwargs)
            cells.append((name, imgui.get_cursor_pos_y(), imgui.get_window_size().y,
                          imgui.get_scroll_max_y()))
            return result

        monkeypatch.setattr(type(widget), "ui", view)

    def draw():
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(width, 1656))
        imgui.begin("force-shell", flags=imgui.WindowFlags_.no_title_bar)
        app._ui_fn(app.ctx)
        scroll.append((imgui.get_scroll_max_x(), imgui.get_scroll_max_y()))
        imgui.end()

    for _ in range(4):
        headers.clear()
        views.clear()
        buttons.clear()
        cells.clear()
        implot_frame(draw)
    assert headers == (["Connect"] if step == 0 else ["Track", "Force tracking"])
    assert set(views) == ({"viewer", "device", "status"} if step == 0
                          else {"tracking", "recording", "status"})
    assert scroll[-1] == (0, 0)
    assert all(overhang <= 1 for _, overhang in buttons), buttons
    assert all(
        cursor - imgui.get_style().item_spacing.y <= height and overflow == 0
        for name, cursor, height, overflow in cells
        if name in {"tracking", "viewer"} or (width == 2560 and name != "status")
    ), cells
    if record_bounds:
        top, bottom, clip_top, clip_bottom = record_bounds
        assert top >= clip_top and bottom <= clip_bottom, record_bounds
    assert force_app["layout"]._active is (
        force_app["layout"]._wide if width == 2560 else force_app["layout"]._narrow
    )


def test_force_recording_keeps_acquiring_while_connect_is_open(force_app, monkeypatch, implot_frame):
    """Switching views must leave the same take and all acquisition attached."""
    from types import SimpleNamespace

    import numpy as np
    from imgui_bundle import imgui

    from myogestic.stream import StreamInfo

    app = force_app["app"]
    app.ctx.participant = "P-014"
    for name in ("emg", "force"):
        source = SimpleNamespace(
            connect=lambda: StreamInfo(n_channels=2, fs=100.0),
            read=lambda: (np.ones((10, 2), dtype=np.float32), np.arange(10) / 100.0),
            disconnect=lambda: None,
        )
        monkeypatch.setattr(app.ctx.streams[name], "_source", source)
        assert app.ctx.streams[name].reconnect()
    force_app["steps"].active = 1
    button = imgui.button
    clicks = {"record": True}

    def record(label, *args, **kwargs):
        result = button(label, *args, **kwargs)
        if label.endswith("  Record") and clicks["record"]:
            clicks["record"] = False
            return True
        return result

    monkeypatch.setattr(imgui, "button", record)
    implot_frame(lambda: app._ui_fn(app.ctx))
    session = app.ctx.session
    assert app.ctx.state == "recording" and session is not None
    assert set(session.stores) == {"emg", "force", "target"}
    started = force_app["recording"]._started
    force_app["steps"].active = 0
    for _ in range(3):
        implot_frame(lambda: app._ui_fn(app.ctx))
        for name in ("emg", "force"):
            app.ctx.streams[name]._acquire_step()
    assert app.ctx.state == "recording" and app.ctx.session is session
    assert all(stream._session is session for stream in app.ctx.streams.values())
    assert all(session.stores[name].shape[0] == 30 for name in ("emg", "force"))
    force_app["steps"].active = 1
    implot_frame(lambda: app._ui_fn(app.ctx))
    assert force_app["recording"]._started == started


@pytest.mark.parametrize("height,show_guidance", [(170, False), (500, True)])
def test_force_guidance_yields_to_the_recording_control(
    force_app, monkeypatch, imgui_frame, height, show_guidance,
):
    """The three optional setup hints appear together only when the card fits."""
    from imgui_bundle import imgui

    texts, scroll = [], []
    wrapped = imgui.text_wrapped

    def remember(text):
        texts.append(text)
        wrapped(text)

    monkeypatch.setattr(imgui, "text_wrapped", remember)

    def draw():
        imgui.begin_child("force-guidance", imgui.ImVec2(380, height))
        force_app["track_ui"](force_app["app"].ctx)
        scroll.append(imgui.get_scroll_max_y())
        imgui.end_child()

    for _ in range(4):
        texts.clear()
        imgui_frame(draw)
    hints = [f"{i}. {text}" for i, text in enumerate(force_app["SYNTHETIC_FORCE"].steps, start=1)]
    assert all((text in texts) == show_guidance for text in hints)
    assert scroll[-1] == 0




def _synthetic_example(name, monkeypatch):
    """Load an app without opening its runner or requiring an installed hand."""
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    try:
        return runpy.run_path(str(_EXAMPLES_ROOT / "synthetic" / f"{name}.py"), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"optional dependency missing for {name}: {exc}")


def _light_scaled_ui(monkeypatch):
    """Use the real light theme and double-sized fonts and geometry."""
    from imgui_bundle import imgui

    from myogestic import _scale, _theme

    monkeypatch.setattr(_theme, "_is_mac_dark", lambda: False)
    monkeypatch.setattr(_scale, "_current", 2.0)
    _theme.apply_theme()
    imgui.get_style().scale_all_sizes(2.0)
    imgui.get_style().font_scale_main = 2.0




@pytest.mark.parametrize("name", ["channel_grid_demo", "multi_panel_grids"])
def test_synthetic_array_traces_use_one_manual_range(name, monkeypatch, implot_frame):
    """A quiet electrode must not be inflated to the same height as a loud one."""
    from myogestic.widgets.signals import _state

    namespace = _synthetic_example(name, monkeypatch)
    app = namespace["app"]
    monkeypatch.setattr(_state, "_viewers", {})
    implot_frame(lambda: app._ui_fn(app.ctx))
    viewers = namespace.get("viewers", [namespace.get("viewer")])
    states = [_state._viewers[viewer._widget_id or "emg"] for viewer in viewers]
    assert all(state.scale_mode == "manual" for state in states)
    assert len({(state.y_min, state.y_max) for state in states}) == 1
    assert all(not state.per_channel_scale for state in states)


def test_electrode_overview_names_empty_cards_and_gives_a_next_step(monkeypatch, implot_frame):
    """Detached arrays still have a title and explain how to get their first samples."""
    from imgui_bundle import imgui

    namespace = _synthetic_example("electrode_overview", monkeypatch)
    _light_scaled_ui(monkeypatch)
    headings, text = [], []
    original_header = namespace["demo_ui"].__globals__.get("panel_header")
    if original_header is not None:
        def header(title, *args, **kwargs):
            headings.append(title)
            return original_header(title, *args, **kwargs)

        monkeypatch.setitem(namespace["demo_ui"].__globals__, "panel_header", header)
    for method in ("text", "text_disabled", "text_wrapped", "text_unformatted"):
        original = getattr(imgui, method)

        def capture(value, *args, _original=original, **kwargs):
            text.append(value)
            return _original(value, *args, **kwargs)

        monkeypatch.setattr(imgui, method, capture)
    implot_frame(lambda: namespace["demo_ui"](namespace["app"].ctx))
    assert headings == ["IN1", "IN2", "IN3", "IN4", "IN5"]
    assert sum("Not connected" in line for line in text) >= 5
    assert sum("Connect" in line and "signal" in line.lower() for line in text) >= 5




@pytest.mark.parametrize("path", [
    *(_EXAMPLES_ROOT / "synthetic" / f"{name}.py" for name in (
        "emg_32ch_multi_model", "emg_classification",
        "emg_classification_grpc", "emg_regression", "emg_regression_raulnet",
        "high_channel_viewer", "channel_grid_demo", "electrode_overview", "multi_panel_grids",
    )),
    _EXAMPLES_ROOT / "otb" / "sessantaquattro_app.py",
], ids=lambda path: path.stem)
def test_synthetic_and_otb_cards_draw_in_light_theme_at_double_scale(path, monkeypatch, implot_frame):
    """Draw every P2 app at 2x without a display, hardware, or logo texture upload."""
    from imgui_bundle import imgui

    from myogestic.widgets import AppLogo
    from myogestic.widgets.signals import _state

    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.remote.InterfaceSpec, "launcher", lambda self: [])
    # Only texture upload needs a live runner; keep every actual control in the pass.
    monkeypatch.setattr(AppLogo, "ui", lambda self: None)
    monkeypatch.setattr(_state, "_viewers", {})
    try:
        namespace = runpy.run_path(str(path), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"optional dependency missing for {path.name}: {exc}")
    _light_scaled_ui(monkeypatch)
    app = namespace["app"]
    imgui.get_io().display_size = imgui.ImVec2(1920, 1400)
    for _ in range(4):
        imgui.new_frame()
        imgui.set_next_window_pos(imgui.ImVec2(0, 0))
        imgui.set_next_window_size(imgui.ImVec2(1920, 1400))
        imgui.begin("scaled-app", None, imgui.WindowFlags_.no_saved_settings)
        if app._ui_fn is not None:
            app._ui_fn(app.ctx)
        for title, callback, *_ in app._popout_specs:
            imgui.begin_child(title, imgui.ImVec2(320, 1200))
            callback()
            imgui.end_child()
        imgui.end()
        imgui.end_frame()
        imgui.render()
