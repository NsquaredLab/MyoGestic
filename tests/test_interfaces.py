"""Tests for myogestic.interfaces — InterfaceSpec + virtual_hand registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from myogestic.interfaces import InterfaceSpec, virtual_hand


def test_virtual_hand_default_paths(monkeypatch):
    """With env unset, virtual_hand falls back to the macOS Godot binary
    and the repo-relative VHI path."""
    monkeypatch.delenv("GODOT_BIN", raising=False)
    monkeypatch.delenv("VHI_PATH", raising=False)
    spec = virtual_hand()
    assert spec.process[0].endswith("Godot")
    assert "Virtual-Hand-Interface" in spec.process[-1]
    # Path is computed relative to myogestic/__init__'s parent.
    assert Path(spec.process[-1]).name == "Virtual-Hand-Interface"


def test_virtual_hand_env_overrides(monkeypatch):
    monkeypatch.setenv("GODOT_BIN", "/opt/godot")
    monkeypatch.setenv("VHI_PATH", "/tmp/vhi")
    spec = virtual_hand()
    assert spec.process == ["/opt/godot", "--path", "/tmp/vhi"]


def test_virtual_hand_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("GODOT_BIN", "/opt/godot")
    monkeypatch.setenv("VHI_PATH", "/tmp/vhi")
    spec = virtual_hand(godot_bin="/usr/bin/godot4", vhi_path="/proj/vhi")
    assert spec.process == ["/usr/bin/godot4", "--path", "/proj/vhi"]


def test_virtual_hand_output_spec():
    """Channel count, sample rate, and stream names match MyoGestic VHI."""
    spec = virtual_hand()
    assert spec.output_stream == "MyoGestic_Output"
    assert spec.output_channels == 9
    assert spec.output_hz == 32.0
    assert spec.control_stream == "VHI_Control"


def _real_paths(tmp_path: Path) -> tuple[str, str]:
    """Create a fake binary + project dir under tmp_path for launcher() to
    validate against."""
    binary = tmp_path / "godot"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    project = tmp_path / "vhi_proj"
    project.mkdir()
    return str(binary), str(project)


def test_launcher_returns_process_tuple_list(tmp_path: Path):
    binary, project = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin=binary, vhi_path=project)
    pl = spec.launcher()
    assert isinstance(pl, list) and len(pl) == 1
    name, argv = pl[0]
    assert name == "VHI Hand"
    assert argv == [binary, "--path", project]


def test_launcher_returns_independent_copy(tmp_path: Path):
    """Mutating the returned argv must not feed back into the spec."""
    binary, project = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin=binary, vhi_path=project)
    pl = spec.launcher()
    pl[0][1].append("--extra")
    assert "--extra" not in spec.process


def test_launcher_raises_when_binary_missing(tmp_path: Path):
    _, project = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin="/no/such/godot-bin", vhi_path=project)
    with pytest.raises(FileNotFoundError, match="GODOT_BIN"):
        spec.launcher()


def test_launcher_raises_when_path_missing(tmp_path: Path):
    binary, _ = _real_paths(tmp_path)
    spec = virtual_hand(godot_bin=binary, vhi_path="/no/such/vhi/path")
    with pytest.raises(FileNotFoundError, match="VHI_PATH"):
        spec.launcher()


def test_launcher_accepts_binary_on_path(tmp_path: Path, monkeypatch):
    """A binary name resolvable via $PATH (not an absolute path) should work."""
    _, project = _real_paths(tmp_path)
    binary = tmp_path / "godot-on-path"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{tmp_path}")
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
