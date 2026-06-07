"""Pop-out panel wrapper — render a callable inside a dockable ImGui window.

Experimental. Requires ``App(docking=True)``. When that flag is off (the
default), `popout_panel(title, fn)` falls back to running ``fn()`` inline,
so the same example file works in both modes.

Once docking is enabled the ImGui IO config flags pick up
``docking_enable | viewports_enable``, so the user can drag any panel's tab
out of the main window and it becomes a real OS window. Layout state
persists in ``.imgui_state/<app>.ini`` (managed by hello_imgui).

macOS Metal/Retina caveats apply - see the README "Status" note.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from imgui_bundle.hello_imgui import DockableWindow

# Note: hello_imgui import is deferred to popout_panel() — importing it at
# module load time would force every consumer of myogestic.widgets to pay the
# cost of the GUI backend even in headless tests.

# Title → DockableWindow already registered. We don't re-register on every
# frame; hello_imgui owns the per-frame render of registered windows.
_registered: dict[str, object] = {}


def _make_dockable_window(
    title: str,
    gui_fn: Callable[[], None],
    default_open: bool = True,
    can_be_closed: bool = True,
    remember_is_visible: bool | None = None,
) -> DockableWindow:
    """Build the Hello ImGui DockableWindow object for a popout panel."""
    from imgui_bundle import hello_imgui

    if remember_is_visible is None:
        remember_is_visible = True
    win = hello_imgui.DockableWindow()
    win.label = title
    win.dock_space_name = "MainDockSpace"
    win.gui_function = gui_fn
    win.is_visible = default_open
    win.remember_is_visible = remember_is_visible
    win.can_be_closed = can_be_closed
    return win


def popout_panel(
    title: str,
    gui_fn: Callable[[], None],
    *,
    default_open: bool = True,
    can_be_closed: bool = True,
    remember_is_visible: bool | None = None,
) -> None:
    """Render `gui_fn` inside a dockable, tearable ImGui window.

    Parameters
    ----------
    title
        Window title — also used as the ImGui id and as the dedup
        key for repeated calls.
    gui_fn
        Zero-arg callable invoked by ImGui every frame. Treat it
        like the body of a `with imgui.begin(...):` — call ``imgui``/
        ``implot`` from inside.
    default_open
        Initial visibility of the window on first launch.
        Subsequent launches restore from ``.imgui_state``.
    can_be_closed
        Whether the user can close the window with the X
        button. Closed windows reappear via the "View" menu.
    remember_is_visible
        Whether visibility is persisted in the imgui
        ini file. Defaults to True for existing behavior.

    Notes
    -----
    When `App(docking=True)` is not active, this just runs `gui_fn()`
    inline so the call site stays the same.
    """
    from myogestic import core as _core  # late import → no circular

    app = _core._active_app
    if app is None or not getattr(app, "_docking", False):
        # Inline fallback — visually identical to calling gui_fn() directly.
        gui_fn()
        return

    if title in _registered:
        return  # already registered; hello_imgui pumps the gui_function.

    win = _make_dockable_window(
        title,
        gui_fn,
        default_open,
        can_be_closed,
        remember_is_visible,
    )

    # Append to the pending list. If the GUI loop hasn't started yet,
    # `_gui_loop` will drain this into runner_params before launch.
    # If we're already inside the loop (popout_panel called from
    # @app.ui's first frame), append directly to the live params so
    # hello_imgui picks it up on the next frame.
    _core._pending_popouts.append(win)

    rp = getattr(app, "_runner_params", None)
    if rp is not None and rp.docking_params is not None:
        current = list(rp.docking_params.dockable_windows)
        if not any(getattr(w, "label", None) == title for w in current):
            current.append(win)
        rp.docking_params.dockable_windows = current

    _registered[title] = win


def _reset_registry() -> None:
    """Drop the registered-window cache.

    Called by ``App._gui_loop``'s finally block so a subsequent App in
    the same process re-registers cleanly. Also used by tests.
    """
    _registered.clear()


__all__ = ["popout_panel"]
