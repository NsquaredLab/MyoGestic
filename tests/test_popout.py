"""Tests for popout_panel — fallback path, registration, idempotency.

We never spin up an actual GUI window in tests; we just exercise the
register/no-op logic via myogestic.core's module-level state.
"""

from __future__ import annotations

import pytest

from myogestic import core
from myogestic.widgets.panels.popout import (
    _make_dockable_window,
    _reset_registry,
    popout_panel,
)


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Each test starts with a clean popout registry + no active App."""
    _reset_registry()
    core._pending_popouts.clear()
    saved = core._active_app
    core._active_app = None
    yield
    core._active_app = saved
    _reset_registry()
    core._pending_popouts.clear()


# --- Fallback when docking is off ------------------------------------------


def test_popout_panel_runs_inline_when_no_app():
    calls = []
    popout_panel("X", lambda: calls.append(1))
    assert calls == [1]


def test_popout_panel_runs_inline_when_docking_off():
    """An App with docking=False should behave like no-app: run inline,
    don't register anything."""
    from myogestic.core import App

    app = App("test", theme=False, docking=False)
    core._active_app = app

    calls = []
    popout_panel("Y", lambda: calls.append(1))
    assert calls == [1]
    assert core._pending_popouts == []


# --- Registration when docking is on ---------------------------------------


def test_popout_panel_registers_dockable_window():
    """When docking is on, popout_panel queues a DockableWindow and does
    NOT execute the gui_fn inline (hello_imgui drives that on render)."""
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    core._active_app = app

    calls = []
    popout_panel("Signal", lambda: calls.append(1))

    assert calls == []  # gui_fn deferred to hello_imgui's render loop
    assert len(core._pending_popouts) == 1
    assert core._pending_popouts[0].label == "Signal"
    assert core._pending_popouts[0].dock_space_name == "MainDockSpace"


def test_popout_panel_idempotent_per_title():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    core._active_app = app

    popout_panel("A", lambda: None)
    popout_panel("A", lambda: None)
    popout_panel("A", lambda: None)
    assert len(core._pending_popouts) == 1


def test_popout_panel_distinct_titles_register_separately():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    core._active_app = app

    popout_panel("A", lambda: None)
    popout_panel("B", lambda: None)
    titles = sorted(w.label for w in core._pending_popouts)
    assert titles == ["A", "B"]


def test_popout_panel_passes_through_visibility_flags():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    core._active_app = app

    popout_panel("Closeable", lambda: None, default_open=False, can_be_closed=False)
    win = core._pending_popouts[0]
    assert win.is_visible is False
    assert win.can_be_closed is False
    assert win.remember_is_visible is True


def test_popout_panel_can_disable_visibility_persistence():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    core._active_app = app

    popout_panel("Pinned", lambda: None, remember_is_visible=False)
    assert core._pending_popouts[0].remember_is_visible is False


def test_make_dockable_window_uses_main_dockspace():
    win = _make_dockable_window("Probe", lambda: None)
    assert win.dock_space_name == "MainDockSpace"


def test_app_popout_registers_pre_run_specs():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    app.popout("Signal", lambda: None)
    app.popout("Log", lambda: None, default_open=False, can_be_closed=False)

    assert [spec[0] for spec in app._popout_specs] == ["Signal", "Log"]
    assert app._popout_specs[1][2:] == (False, False, None)


def test_app_popout_can_disable_visibility_persistence():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)
    app.popout(
        "Signal",
        lambda: None,
        can_be_closed=False,
        remember_is_visible=False,
    )

    assert app._popout_specs[0][3:] == (False, False)


def test_app_popout_replaces_duplicate_title():
    from myogestic.core import App

    app = App("test", theme=False, docking=True)

    def first():
        return "first"

    def second():
        return "second"

    app.popout("Signal", first)
    app.popout("Signal", second)

    assert len(app._popout_specs) == 1
    assert app._popout_specs[0][1] is second


def test_registry_cleared_between_apps():
    """Regression: codex flagged that `_registered` persisted across App
    instances, silently skipping re-registration when titles overlapped.
    Simulating that here: register against App A, run the cleanup that
    `App._gui_loop` does in its `finally`, register against App B, and
    verify B got its own DockableWindow."""
    from myogestic.core import App

    app_a = App("A", theme=False, docking=True)
    core._active_app = app_a
    popout_panel("Signal", lambda: None)
    assert len(core._pending_popouts) == 1

    # Simulate App.run()'s finally cleanup.
    core._pending_popouts.clear()
    _reset_registry()
    core._active_app = None

    app_b = App("B", theme=False, docking=True)
    core._active_app = app_b
    popout_panel("Signal", lambda: None)
    assert len(core._pending_popouts) == 1, (
        "second App should re-register the same title — got skipped due to leaked _registered state"
    )
