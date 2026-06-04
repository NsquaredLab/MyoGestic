"""Tests for myogestic.interfaces — InterfaceSpec + virtual_hand registry."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from myogestic.interfaces import InterfaceSpec, virtual_hand


def test_virtual_hand_default_paths(monkeypatch):
    """With env unset, virtual_hand resolves install_root to the repo-relative
    tools/MyoGestic-VHI directory (in a git checkout)."""
    monkeypatch.delenv("GODOT_BIN", raising=False)
    monkeypatch.delenv("VHI_PATH", raising=False)
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    spec = virtual_hand()
    # The documented default: <repo>/tools/MyoGestic-VHI in a git checkout.
    assert spec.install_root is not None
    assert spec.install_root.parts[-1] == "MyoGestic-VHI"
    assert spec.install_root.parts[-2] == "tools"


def test_virtual_hand_env_overrides(tmp_path, monkeypatch):
    """$VHI_PATH and $GODOT_BIN override the defaults for source-mode launch."""
    project = tmp_path / "vhi_proj"
    project.mkdir()
    (project / "project.godot").write_text("")  # source-mode marker required
    godot_bin = "/opt/godot"
    monkeypatch.setenv("GODOT_BIN", godot_bin)
    monkeypatch.setenv("VHI_PATH", str(project))
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    spec = virtual_hand()
    assert spec.process == [godot_bin, "--path", str(project)]


def test_virtual_hand_explicit_args_win_over_env(tmp_path, monkeypatch):
    """Explicit godot_bin/vhi_path kwargs beat env vars."""
    # project pointed to by env (should be ignored)
    env_project = tmp_path / "env_vhi"
    env_project.mkdir()
    monkeypatch.setenv("GODOT_BIN", "/opt/godot")
    monkeypatch.setenv("VHI_PATH", str(env_project))
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    # explicit project — this one must win
    real_project = tmp_path / "real_vhi"
    real_project.mkdir()
    (real_project / "project.godot").write_text("")
    godot_explicit = "/usr/bin/godot4"
    spec = virtual_hand(godot_bin=godot_explicit, vhi_path=str(real_project))
    assert spec.process == [godot_explicit, "--path", str(real_project)]


def test_virtual_hand_output_spec():
    """Channel count, sample rate, and stream names match MyoGestic VHI."""
    spec = virtual_hand()
    assert spec.output_stream == "MyoGestic_Output"
    assert spec.output_channels == 9
    assert spec.output_hz == 32.0
    assert spec.control_stream == "VHI_Control"


def _real_paths(tmp_path: Path) -> tuple[str, str]:
    """Create a fake godot binary + project dir with project.godot under
    tmp_path for source-mode launcher() tests."""
    binary = tmp_path / "godot"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    project = tmp_path / "vhi_proj"
    project.mkdir()
    (project / "project.godot").write_text("")  # required for source-mode resolution
    return str(binary), str(project)


def test_launcher_returns_process_tuple_list(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    binary, project = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin=binary, vhi_path=project)
    pl = spec.launcher()
    assert isinstance(pl, list) and len(pl) == 1
    name, argv = pl[0]
    assert name == "VHI Hand"
    assert argv == [binary, "--path", project]


def test_launcher_returns_independent_copy(tmp_path: Path, monkeypatch):
    """Mutating the returned argv must not feed back into the spec."""
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    binary, project = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin=binary, vhi_path=project)
    pl = spec.launcher()
    pl[0][1].append("--extra")
    assert "--extra" not in spec.process


def test_launcher_raises_when_binary_missing(tmp_path: Path, monkeypatch):
    """When no binary or source project is found, launcher() raises FileNotFoundError."""
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    # Create a project dir WITHOUT project.godot (so source mode can't resolve)
    project = tmp_path / "vhi_proj"
    project.mkdir()
    spec = virtual_hand(godot_bin="/no/such/godot-bin", vhi_path=str(project))
    with pytest.raises(FileNotFoundError, match="GODOT_BIN"):
        spec.launcher()


def test_launcher_raises_when_path_missing(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    binary = tmp_path / "godot"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    spec = virtual_hand(godot_bin=str(binary), vhi_path="/no/such/vhi/path")
    with pytest.raises(FileNotFoundError, match="VHI_PATH"):
        spec.launcher()


def test_launcher_accepts_binary_on_path(tmp_path: Path, monkeypatch):
    """A binary name resolvable via $PATH (not an absolute path) should work."""
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    _, project = _real_paths(tmp_path)
    binary = tmp_path / "godot-on-path"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{tmp_path}")
    # Pass binary name only (not abs path); virtual_hand resolves it via
    # _resolve_godot_bin which returns the name as-is when explicitly passed.
    spec = virtual_hand(godot_bin="godot-on-path", vhi_path=project)
    assert spec.launcher()[0][1][0] == "godot-on-path"


def test_outlet_construction_uses_spec_fields():
    """`spec.outlet()` reads name/channels/hz from the dataclass — no
    hard-coding inside `outlet()`. We assert that without binding a real
    LSL outlet (which requires the LSL C lib + a free port).
    """
    spec = InterfaceSpec(
        name="probe",
        process=[],
        output_stream="probe_out",
        output_channels=3,
        output_hz=10.0,
    )
    pytest.importorskip("mne_lsl.lsl")
    outlet = spec.outlet()
    assert outlet._hz == 10.0
    outlet.stop()
