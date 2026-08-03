"""VHI movement-panel polling contracts."""

from __future__ import annotations

import myogestic.widgets.vhi.panel as panel_module
from myogestic.widgets.vhi.panel import VhiMovementPanel


class _Client:
    pass


def _capture_palette(monkeypatch):
    rendered: list[tuple[tuple, dict]] = []

    def capture(*args, **kwargs):
        rendered.append((args, kwargs))

    monkeypatch.setattr(panel_module, "vhi_movement_palette", capture)
    return rendered


def test_panel_can_render_cached_state_without_automatic_rpc(monkeypatch) -> None:
    client = _Client()
    refreshes: list[tuple[object, object, dict]] = []
    monkeypatch.setattr(
        panel_module,
        "request_vhi_state_refresh",
        lambda *args, **kwargs: refreshes.append((*args, kwargs)),
    )
    rendered = _capture_palette(monkeypatch)
    panel = VhiMovementPanel(client, lambda _state: None)

    panel.ui(auto_refresh=False)

    assert refreshes == []
    assert len(rendered) == 1
    rendered[0][1]["on_refresh"]()
    assert refreshes == [(client, panel._cache, {"force": True})]


def test_panel_automatic_refresh_remains_the_default(monkeypatch) -> None:
    client = _Client()
    refreshes: list[tuple[object, object, dict]] = []
    monkeypatch.setattr(
        panel_module,
        "request_vhi_state_refresh",
        lambda *args, **kwargs: refreshes.append((*args, kwargs)),
    )
    _capture_palette(monkeypatch)
    panel = VhiMovementPanel(client, lambda _state: None, min_interval_s=2.5)

    panel.ui()

    assert refreshes == [(client, panel._cache, {"min_interval_s": 2.5})]
