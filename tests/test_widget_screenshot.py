"""Screenshot fixtures render their advertised state without manual clicks."""

import runpy
from pathlib import Path

from myogestic import App
from myogestic.widgets import SessionManager


def test_session_manager_capture_loads_three_selected_mock_sessions(
    tmp_path, imgui_frame, monkeypatch
):
    script = Path(__file__).resolve().parents[1] / "tools" / "widget_screenshot.py"
    renderer = runpy.run_path(str(script))["render_session_manager"]
    monkeypatch.setitem(renderer.__globals__, "_self_capture_after", lambda *a, **k: None)
    monkeypatch.setattr("tempfile.mkdtemp", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(App, "run", lambda self, **kwargs: imgui_frame(lambda: self._ui_fn(self.ctx)))
    monkeypatch.setattr("myogestic.widgets.training._session_state._states", {})
    rendered = []
    original_ui = SessionManager.ui

    def remember(manager, *args, **kwargs):
        data = original_ui(manager, *args, **kwargs)
        rendered.append((manager.selection(), data))
        return data

    monkeypatch.setattr(SessionManager, "ui", remember)

    renderer(tmp_path / "session_manager.png")

    summary, data = rendered[-1]
    assert summary.n_total == summary.n_selected == 3
    assert len(data.paths) == 3
    assert data.classes == {0, 1}
    assert all(Path(path).is_dir() for path in data.paths)
