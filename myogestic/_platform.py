"""Platform / asset-folder helpers for the App runtime.

Branding/asset plumbing extracted from ``core.py`` so ``App``/``Context`` stay
focused: locating the shipped assets dir, registering it with HelloImGui, and
setting the macOS Dock icon. Used only by ``myogestic.core``.
"""

import sys
from pathlib import Path


def _assets_folder() -> str:
    """Absolute path to the shipped assets dir inside the installed package."""
    import myogestic  # local import - `core` is imported during package init

    return str(Path(myogestic.__file__).resolve().parent / "assets")


def _register_assets_folder(hello_imgui_mod) -> None:
    """Point HelloImGui at our shipped assets so `image_from_asset(...)` works.

    `add_assets_search_path` is a no-op if the path is already registered, so
    calling this on every `run()` is harmless. Wraps any HelloImGui internal
    failure in a warning rather than crashing - a missing/broken asset folder
    shouldn't prevent the UI from coming up.
    """
    try:
        hello_imgui_mod.add_assets_search_path(_assets_folder())
    except Exception as e:
        print(f"[myogestic] could not register assets folder: {e}", file=sys.stderr)


def _try_set_macos_dock_icon() -> None:
    """Set the macOS Dock icon to our packaged PNG.

    No-op when not on macOS or when ``pyobjc-framework-Cocoa`` isn't installed.
    On Linux/Windows the equivalent (window icon) is handled by HelloImGui's
    `app_settings/icon.png` convention automatically once the assets folder
    is registered - see ``_register_assets_folder``.

    Why we need this at all: macOS bans changing the Dock icon at runtime
    without going through ``NSApplication.setApplicationIconImage_``; GLFW's
    `glfwSetWindowIcon` is a no-op on Cocoa, and Python's own process icon
    sticks unless we explicitly swap it.

    Two subtleties make this trickier than it looks:

    1. GLFW's macOS backend creates the ``NSApplication`` during init; if we
       call this before that, our icon gets overwritten. Caller wires this
       up as HelloImGui's ``post_init`` callback so we run after the
       NSApplication exists.
    2. ``setApplicationIconImage_`` updates the image but doesn't always
       force the Dock to redraw the tile. ``NSApp.dockTile().display()``
       (no-op-cheap when the tile is already current) makes the change
       actually appear without waiting for the next dock refresh tick.
    """
    if sys.platform != "darwin":
        return
    try:
        # pyobjc-framework-Cocoa ships incomplete stubs: ty can't see these
        # AppKit members. Bare ignores (ty doesn't honor bracketed codes).
        from AppKit import (
            NSApplication,  # type: ignore
            NSApplicationActivationPolicyRegular,  # type: ignore
            NSImage,  # type: ignore
        )
    except ImportError:
        print("[myogestic] dock icon: pyobjc-framework-Cocoa not installed", file=sys.stderr)
        return
    icon_path = Path(_assets_folder()) / "app_settings" / "icon.png"
    if not icon_path.exists():
        print(f"[myogestic] dock icon: file missing at {icon_path}", file=sys.stderr)
        return
    image = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
    if image is None:
        print(f"[myogestic] dock icon: NSImage failed to load {icon_path}", file=sys.stderr)
        return
    app = NSApplication.sharedApplication()
    # A python-launched process defaults to "Prohibited" activation policy;
    # `setApplicationIconImage_` is silently dropped on the floor until the
    # policy is Regular (= shows in the Dock + can have menu bar). GLFW
    # flips this on window creation but the timing isn't guaranteed by the
    # time post_init fires, so we set it explicitly.
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    app.setApplicationIconImage_(image)
    # Force the Dock to redraw the tile. Apple's API updates the underlying
    # image but the dock-tile cache may persist until something nudges it.
    app.dockTile().display()
