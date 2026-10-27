"""The generic `InterfaceSpec` and the one VHI-shaped instance of it, `virtual_hand`."""

from __future__ import annotations

from pathlib import Path

import pytest

from myogestic.remote import InterfaceSpec
from myogestic.vhi import interfaces as vhi_interfaces
from myogestic.vhi import virtual_hand


@pytest.fixture
def install_roots(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    # A worktree has a .git file rather than a directory.
    (repo / ".git").write_text("gitdir: /unused/worktree")
    user_data = tmp_path / "user_data"
    monkeypatch.setattr(
        vhi_interfaces, "__file__", str(repo / "myogestic" / "vhi" / "interfaces.py")
    )
    monkeypatch.setattr(vhi_interfaces, "_user_data_root", lambda: user_data)
    monkeypatch.setattr(vhi_interfaces.platform, "system", lambda: "Darwin")
    monkeypatch.delenv("GODOT_BIN", raising=False)
    monkeypatch.delenv("VHI_PATH", raising=False)
    monkeypatch.delenv("VHI_LAUNCH_MODE", raising=False)
    return repo / "tools" / "MyoGestic-VHI", user_data / "vhi"


def _install_at(root, kind):
    marker = root / (
        "project.godot" if kind == "godot" else "VHI.app/Contents/MacOS/Virtual Hand Interface"
    )
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    return marker


def test_virtual_hand_default_paths(install_roots):
    """An empty checkout keeps its original install destination as the default."""
    checkout, _ = install_roots
    spec = virtual_hand()
    assert spec.install_root == checkout
    assert spec.launchable() == []


@pytest.mark.parametrize("git_kind", ["file", "directory"])
@pytest.mark.parametrize("kind", ["binary", "godot"])
@pytest.mark.parametrize("local_install", [False, True])
def test_virtual_hand_finds_existing_install(install_roots, git_kind, kind, local_install):
    checkout, user = install_roots
    if git_kind == "directory":
        git = checkout.parents[1] / ".git"
        git.unlink()
        git.mkdir()
    # An empty install directory alone must not hide the per-user installation.
    checkout.mkdir(parents=True)
    marker = _install_at(user, kind)
    expected = user
    if local_install:
        marker = _install_at(checkout, kind)
        expected = checkout
    spec = virtual_hand(godot_bin="/test/godot" if kind == "godot" else None)
    assert spec.install_root == expected
    argv = ["/test/godot", "--path", str(expected)] if kind == "godot" else [str(marker)]
    assert spec.launchable() == [(spec.name, argv)]


@pytest.mark.parametrize("outside_checkout", ["no_git", "read_only"])
def test_virtual_hand_outside_writable_checkout_uses_user_data(
    install_roots, monkeypatch, outside_checkout
):
    checkout, user = install_roots
    _install_at(checkout, "binary")
    if outside_checkout == "no_git":
        (checkout.parents[1] / ".git").unlink()
    else:
        monkeypatch.setattr(vhi_interfaces.os, "access", lambda *args: False)
    assert virtual_hand().install_root == user


@pytest.mark.parametrize("override", ["environment", "argument"])
def test_virtual_hand_path_override_wins_even_when_missing(
    install_roots, tmp_path, monkeypatch, override
):
    checkout, user = install_roots
    _install_at(checkout, "binary")
    _install_at(user, "binary")
    missing = tmp_path / "explicit_vhi"
    if override == "environment":
        monkeypatch.setenv("VHI_PATH", str(missing))
        spec = virtual_hand()
    else:
        monkeypatch.setenv("VHI_PATH", str(user))
        spec = virtual_hand(vhi_path=str(missing))
    assert spec.install_root == missing
    assert spec.launchable() == []


def test_installer_destination_stays_in_checkout_with_per_user_install(install_roots):
    from myogestic.tools.install_vhi import _default_dest

    checkout, user = install_roots
    _install_at(user, "binary")
    assert virtual_hand().install_root == user
    assert _default_dest() == checkout


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
    """Channel count and sample rate match MyoGestic VHI.

    No pose stream *name* is asserted because the spec no longer carries one: which
    streams the target has, and which controls each carries, is in the manifest a
    running VHI answers with. `VHI_Control` is a different thing — an inlet MyoGestic
    reads, not a stream it negotiates — so it stays configuration.
    """
    spec = virtual_hand()
    assert spec.n_output_channels == 9
    assert spec.output_hz == 32.0
    assert spec.control_stream_name == "VHI_Control"


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


def test_outlet_construction_takes_the_name_from_the_caller():
    """`stream_outlet()` publishes the name it is *given* — the manifest's, not a field.

    Width and rate still come off the dataclass. Asserted without binding a real LSL
    outlet (which requires the LSL C lib + a free port) beyond the one built here.
    """
    spec = InterfaceSpec(name="probe", process=[], n_output_channels=3, output_hz=10.0)
    pytest.importorskip("mne_lsl.lsl")
    outlet = spec.stream_outlet("probe_out")
    assert outlet._hz == 10.0
    outlet.stop()


def test_an_unnamed_stream_is_refused_rather_than_published():
    """An LSL stream with no name cannot be resolved, so it must not be built."""
    spec = InterfaceSpec(name="probe", process=[], n_output_channels=3, output_hz=10.0)
    with pytest.raises(ValueError, match="unnamed stream"):
        spec.stream_outlet("")
