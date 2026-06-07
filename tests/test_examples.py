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

EXAMPLES = sorted((Path(__file__).resolve().parent.parent / "examples" / "synthetic").glob("*.py"))


@pytest.mark.parametrize("path", [pytest.param(p, id=p.name) for p in EXAMPLES])
def test_example_wires_up(path, monkeypatch):
    """Run an example with the GUI loop stubbed; any API-wiring error fails."""
    # The GUI (and headless) run loop blocks forever — replace it with a no-op so
    # the script completes right after building the app.
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    try:
        runpy.run_path(str(path), run_name="__main__")
    except (ImportError, ModuleNotFoundError) as e:
        pytest.skip(f"optional dependency missing for {path.name}: {e}")
