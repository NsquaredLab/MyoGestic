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
    def draw_all() -> None:
        for fn in draws:
            fn(app.ctx) if fn is app._ui_fn else fn()

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
    monkeypatch.setattr(scope["logo"], "ui", lambda: None)
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
