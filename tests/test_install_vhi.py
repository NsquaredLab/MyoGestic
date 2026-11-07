"""Installer transactions and explicit checksum opt-outs, without network access."""

from __future__ import annotations

import errno
import os
import zipfile
from pathlib import Path

import pytest

from myogestic.tools import install_vhi


@pytest.fixture
def local_release(tmp_path, monkeypatch):
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as release:
        release.writestr("VHI.x86_64", b"new executable")
        release.writestr("data/config", b"new configuration")

    monkeypatch.setattr(install_vhi, "_resolve_asset", lambda: "VHI-test.zip")
    monkeypatch.setattr(install_vhi.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        install_vhi, "_download", lambda _url, target: target.write_bytes(archive.read_bytes())
    )
    monkeypatch.setattr(
        install_vhi, "_fetch_release_digest", lambda _tag, _asset: install_vhi._sha256(archive)
    )
    dest = tmp_path / "installs" / "vhi"
    dest.mkdir(parents=True)
    (dest / "VHI.x86_64").write_bytes(b"old executable")
    (dest / "vhi-version.txt").write_text("installed_tag=v2.0.0\n")
    (dest / "old-only").write_bytes(b"preserve me on failure")
    return dest


def _files(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def fail_replacement(monkeypatch, local_release):
    """Fail the new-directory rename and the legacy cross-filesystem copy fallback."""
    rename = os.rename

    def fail_rename(source, target, *args, **kwargs):
        if Path(source).name == "staging" and Path(target) == local_release:
            raise OSError(errno.EIO, "injected replacement failure")
        return rename(source, target, *args, **kwargs)

    def fail_copytree(_source, target, *args, **kwargs):
        Path(target).mkdir()
        (Path(target) / "partial-copy").write_bytes(b"incomplete replacement")
        raise OSError(errno.EIO, "injected replacement failure")

    monkeypatch.setattr(os, "rename", fail_rename)
    monkeypatch.setattr(install_vhi.shutil, "copytree", fail_copytree)


def test_failed_replacement_restores_the_entire_previous_install(local_release, fail_replacement):
    before = _files(local_release)

    with pytest.raises(OSError, match="injected replacement failure"):
        install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    assert _files(local_release) == before


@pytest.mark.parametrize(
    "operation",
    [
        "_download",
        "_verify",
        "_unpack",
        "_validate",
        "_restore_exec_bits",
        "_write_marker",
        "_strip_quarantine",
    ],
)
def test_preparation_failure_preserves_previous_install(local_release, monkeypatch, operation):
    before = _files(local_release)

    def fail(*_args):
        raise OSError("injected preparation failure")

    monkeypatch.setattr(install_vhi, operation, fail)

    with pytest.raises(OSError, match="injected preparation failure"):
        install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    assert _files(local_release) == before


def test_install_stages_beside_destination_before_replacing(local_release, monkeypatch):
    before = _files(local_release)
    unpack = install_vhi._unpack

    def unpack_beside_destination(archive, staging):
        assert staging.parent.parent == local_release.parent
        assert staging.parent.stat().st_dev == local_release.parent.stat().st_dev
        assert _files(local_release) == before
        unpack(archive, staging)

    monkeypatch.setattr(install_vhi, "_unpack", unpack_beside_destination)

    install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    assert (local_release / "VHI.x86_64").read_bytes() == b"new executable"
    assert (local_release / "data/config").read_bytes() == b"new configuration"
    assert "installed_tag=v2.1.0" in (local_release / "vhi-version.txt").read_text()
    assert not (local_release / "old-only").exists()
    assert list(local_release.parent.iterdir()) == [local_release]


def test_failed_rollback_keeps_previous_install_and_reports_location(
    local_release, fail_replacement, monkeypatch, capsys
):
    before = _files(local_release)
    rename = os.rename

    def fail_restore(source, target, *args, **kwargs):
        if Path(source).name == "previous" and Path(target) == local_release:
            raise OSError("injected rollback failure")
        return rename(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_restore)

    with pytest.raises(OSError, match="injected rollback failure"):
        install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    backups = list(local_release.parent.glob("*/previous"))
    assert len(backups) == 1
    assert _files(backups[0]) == before
    assert str(backups[0]) in capsys.readouterr().err


def test_failed_replacement_restores_a_relative_symlink(local_release, fail_replacement):
    old_target = local_release.with_name("old-vhi")
    local_release.rename(old_target)
    local_release.symlink_to(old_target.name, target_is_directory=True)
    before = _files(old_target)

    with pytest.raises(OSError, match="injected replacement failure"):
        install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    assert local_release.is_symlink()
    assert local_release.readlink() == Path(old_target.name)
    assert _files(local_release) == before


def test_cleanup_failure_warns_and_leaves_completed_install(local_release, monkeypatch, capsys):
    def fail_cleanup(_path):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(install_vhi.shutil, "rmtree", fail_cleanup)

    install_vhi._install(tag="v2.1.0", dest=local_release, force=True)

    assert (local_release / "VHI.x86_64").read_bytes() == b"new executable"
    assert "installed_tag=v2.1.0" in (local_release / "vhi-version.txt").read_text()
    assert "injected cleanup failure" in capsys.readouterr().err


def test_no_verify_warns_before_downloading(local_release, monkeypatch, capsys):
    download = install_vhi._download

    def download_after_warning(url, target):
        warning = capsys.readouterr().err
        assert "WARNING" in warning
        assert "--no-verify" in warning
        assert "NOT be integrity-checked" in warning
        download(url, target)

    def unexpected_verification(*_args):
        pytest.fail("--no-verify must skip both digest lookup and archive hashing")

    monkeypatch.setattr(install_vhi, "_download", download_after_warning)
    monkeypatch.setattr(install_vhi, "_fetch_release_digest", unexpected_verification)
    monkeypatch.setattr(install_vhi, "_verify", unexpected_verification)

    install_vhi._install(tag="v2.1.0", dest=local_release, force=True, no_verify=True)

    assert (local_release / "VHI.x86_64").read_bytes() == b"new executable"
