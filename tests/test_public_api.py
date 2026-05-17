"""Pin the public ``myogestic`` import surface.

A fresh user (or LLM) should be able to write working code with only
``import myogestic``. These tests fail loudly if a public name moves or
disappears so the breakage is obvious — not silent.
"""

from __future__ import annotations


def test_top_level_names_are_reachable():
    """Every name advertised in `__all__` of the top-level package imports cleanly."""
    import myogestic

    expected = {
        "App", "AppState", "COL_WIDTH", "Context", "Grid", "Pipeline",
        "ROW_HEIGHT", "Stream", "StreamInfo", "TrainingData",
    }
    assert expected.issubset(set(myogestic.__all__))
    for name in expected:
        assert hasattr(myogestic, name), f"missing top-level {name!r}"


def test_widget_helpers_are_public():
    """FilterControl + panel_header live in `myogestic.widgets` — every
    example imports them, so they must be reachable without diving into
    private modules."""
    from myogestic.widgets import (
        FilterControl,
        panel_header,
        recording_controls,
        session_manager,
        signal_viewer,
    )

    assert callable(FilterControl)
    assert callable(panel_header)
    assert callable(recording_controls)
    assert callable(session_manager)
    assert callable(signal_viewer)
