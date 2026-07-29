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
EXAMPLES = sorted(
    p
    for sub in ("synthetic", "panels")
    for p in (_EXAMPLES_ROOT / sub).glob("*.py")
    if not p.name.startswith("_")
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
    monkeypatch.setattr(myogestic.vhi.interfaces.InterfaceSpec, "launcher", lambda self: [])
    try:
        runpy.run_path(str(path), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"optional dependency missing for {path.name}: {e}")


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
    monkeypatch.setattr(myogestic.vhi.interfaces.InterfaceSpec, "launcher", refuse)

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
