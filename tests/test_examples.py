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
# `panels/*.py` are single-widget demos; `panels/_fixtures.py` is a shared
# helper, not an example, so underscore-prefixed files are skipped.
#
# `reference_renderer.py` is not a MyoGestic App: it is a renderer, the thing an App
# drives. Its `__main__` serves forever (there is no `App.run` to stub), and
# `tests/test_reference_renderer.py` already runs it for real, driven by a live
# `ControlBus` — a stronger check than "does it wire up" ever gives the App examples.
EXAMPLES = sorted(
    p
    for sub in ("synthetic", "panels")
    for p in (_EXAMPLES_ROOT / sub).glob("*.py")
    if not p.name.startswith("_") and p.name != "reference_renderer.py"
)


@pytest.mark.parametrize(
    "path", [pytest.param(p, id=f"{p.parent.name}/{p.name}") for p in EXAMPLES]
)
def test_example_wires_up(path, monkeypatch):
    """Run an example with the GUI loop stubbed; any API-wiring error fails."""
    # The GUI (and headless) run loop blocks forever — replace it with a no-op so
    # the script completes right after building the app.
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    # Panel examples import a sibling `_fixtures` module; running via runpy
    # (unlike a real `python examples/panels/foo.py`) doesn't put the script's
    # own directory on sys.path, so add it.
    monkeypatch.syspath_prepend(str(path.parent))
    # Examples call `vhi.launcher()` at module level, which raises FileNotFoundError
    # unless the VHI binary is installed (an environment dep, not part of the API
    # surface). Stub the env check to []; a renamed/removed `launcher` method would
    # still raise AttributeError and fail the test.
    monkeypatch.setattr(myogestic.renderer.InterfaceSpec, "launcher", lambda self: [])
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
    monkeypatch.setattr(myogestic.renderer.InterfaceSpec, "launcher", lambda self: [])
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


def test_examples_survive_an_unlaunchable_renderer(monkeypatch):
    """An app must open even when VHI cannot be launched from inside it.

    This is deliberately *not* covered by the stub above. `test_example_wires_up`
    replaces `launcher` with a no-op so a machine without VHI installed can still run
    the suite — and that stub also hid a real crash: with a pre-2.0 release on disk,
    `launcher()` raises, and every example that splatted it into a `ProcessLauncher` died
    at import. Including when a perfectly good v2 renderer was already running and the
    app never needed the button.

    So here the refusal is what gets simulated, not what gets stubbed away.
    """
    import myogestic.vhi.interfaces  # noqa: PLC0415

    def refuse(self):
        raise FileNotFoundError(f"{self.name}: the installed release is v1.0.0")

    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    monkeypatch.setattr(myogestic.renderer.InterfaceSpec, "launcher", refuse)

    vhi_examples = [
        path
        for path in EXAMPLES
        if "vhi" in path.read_text() and path.parent.name == "synthetic"
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
