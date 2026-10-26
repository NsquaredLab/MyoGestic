"""Platform-specific branding uses the appropriate packaged icon."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from myogestic import _platform


@pytest.mark.parametrize(
    "macos_icon_present, expected_name",
    [(True, "icon_macos.png"), (False, "icon.png")],
)
def test_macos_dock_icon_selection(monkeypatch, tmp_path, macos_icon_present, expected_name):
    app_settings = tmp_path / "app_settings"
    app_settings.mkdir()
    (app_settings / "icon.png").touch()
    if macos_icon_present:
        (app_settings / "icon_macos.png").touch()

    image = object()
    image_loader = Mock()
    image_loader.initWithContentsOfFile_.return_value = image
    app = Mock()
    appkit = SimpleNamespace(
        NSImage=SimpleNamespace(alloc=lambda: image_loader),
        NSApplication=SimpleNamespace(sharedApplication=lambda: app),
        NSApplicationActivationPolicyRegular=0,
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_platform, "_assets_folder", lambda: str(tmp_path))

    _platform._try_set_macos_dock_icon()

    image_loader.initWithContentsOfFile_.assert_called_once_with(str(app_settings / expected_name))
    app.setActivationPolicy_.assert_called_once_with(appkit.NSApplicationActivationPolicyRegular)
    app.setApplicationIconImage_.assert_called_once_with(image)
    app.dockTile.return_value.display.assert_called_once_with()
