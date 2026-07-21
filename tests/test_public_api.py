"""Pin the public ``myogestic`` import surface.

A fresh user (or LLM) should be able to write working code with only
``import myogestic``. These tests fail loudly if a public name moves or
disappears so the breakage is obvious — not silent.
"""

from __future__ import annotations


def test_top_level_names_are_reachable():
    """Every name advertised in `__all__` of the top-level package imports cleanly."""
    import myogestic

    assert myogestic.__all__, "__all__ must not be empty"
    for name in myogestic.__all__:
        assert hasattr(myogestic, name), f"missing top-level {name!r}"


def test_widget_helpers_are_public():
    """The common widgets live in `myogestic.widgets` — every example imports
    them, so they must be reachable without diving into private modules."""
    from myogestic.widgets import (
        FilterControl,
        RecordingControls,
        SessionManager,
        SignalViewer,
        panel_header,
    )

    assert callable(FilterControl)
    assert callable(panel_header)
    # Widgets are classes constructed once, then rendered with `.ui(...)`.
    for widget_cls in (RecordingControls, SessionManager, SignalViewer):
        assert isinstance(widget_cls, type)
        assert hasattr(widget_cls, "ui")
