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
        ParticipantPanel,
        PostProcessor,
        RecordingControls,
        SessionManager,
        SignalViewer,
        StepBar,
        panel_header,
        primary_button,
        status_pill,
    )

    assert callable(panel_header)
    assert callable(primary_button)
    assert callable(status_pill)
    # Widgets are classes constructed once, then rendered with `.ui(...)`.
    for widget_cls in (
        ParticipantPanel,
        PostProcessor,
        RecordingControls,
        SessionManager,
        SignalViewer,
        StepBar,
    ):
        assert isinstance(widget_cls, type)
        assert hasattr(widget_cls, "ui")


def test_step_bar_panel_export():
    """StepBar is available beside the other panels and in the widget facade."""
    from myogestic.widgets import StepBar
    from myogestic.widgets.panels import StepBar as PanelStepBar

    assert StepBar is PanelStepBar


def test_status_pill_renders(imgui_frame):
    from myogestic.widgets import __all__, status_pill
    from myogestic.widgets.common import SUCCESS
    from myogestic.widgets.common import status_pill as common_status_pill

    assert "status_pill" in __all__
    assert status_pill is common_status_pill
    imgui_frame(lambda: status_pill("CONNECTED", SUCCESS))


def test_participant_panel_export():
    """ParticipantPanel is exported through both widget entry points."""
    from myogestic.widgets import ParticipantPanel
    from myogestic.widgets.panels import ParticipantPanel as PanelParticipantPanel

    assert ParticipantPanel is PanelParticipantPanel


def test_filter_chain_helper_is_public():
    """`chain` composes VectorFilters into one — reachable from `myogestic.outputs`."""
    from myogestic.outputs import chain

    assert callable(chain)


def test_labelled_path_is_public():
    """Sessions and model saves share the public participant path helper."""
    from myogestic.session import __all__, labelled_path

    assert "labelled_path" in __all__
    assert callable(labelled_path)


def test_recorded_time_is_public():
    """Recorded-time summaries are exposed beside the session API."""
    from myogestic.session import RecordedTime, __all__, recorded_time

    assert {"RecordedTime", "recorded_time"} <= set(__all__)
    assert callable(recorded_time)
    assert RecordedTime(0, 0.0, {}).takes == 0
