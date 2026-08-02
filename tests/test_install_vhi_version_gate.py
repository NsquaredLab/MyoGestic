"""The v2-only gate: MyoGestic 2.x cannot drive a pre-2.0 target, so it says so early.

There is no bridge any more. A `RemoteTarget` asks the target which controls it exports
and refuses to guess, so a 1.x build is not degraded — it does not work. The failure that
matters is therefore not "it broke", it is *where* it breaks: installing or launching an
old binary succeeds, and the refusal then surfaces at bind time, three layers from the
command that caused it. These pin the two places that catch it first.
"""

from __future__ import annotations

from functools import partial

import pytest
import typer

from myogestic.remote import InterfaceSpec
from myogestic.tools import install_vhi
from myogestic.vhi import interfaces


def test_the_two_copies_of_the_minimum_agree():
    """`interfaces` duplicates the constant to avoid importing typer to launch."""
    assert interfaces.MIN_VHI_TAG == install_vhi.MIN_VHI_TAG
    assert interfaces._version_of("v9.9.9") == install_vhi._version_of("v9.9.9")


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v1.0.0", (1, 0, 0)),
        ("v2.0.0", (2, 0, 0)),
        ("2.1.3", (2, 1, 3)),
        ("v2.0.0-rc1", (2, 0, 0)),
        ("v10.0.0", (10, 0, 0)),
        ("main", None),
        ("latest", None),
        ("", None),
    ],
)
def test_a_tag_is_parsed_as_a_version_or_not_at_all(tag, expected):
    assert install_vhi._version_of(tag) == expected


def test_v10_is_newer_than_v2_not_older():
    """String comparison would read "10" < "2"; the whole reason for the tuple."""
    assert install_vhi._version_of("v10.0.0") > install_vhi._version_of("v2.0.0")


class TestTheInstallerRefusesAnOldRelease:
    def test_a_pinned_old_tag_is_refused_before_downloading(self, capsys, monkeypatch):
        """Refused *before* the download: 150 MB then unusable is the worse outcome."""
        monkeypatch.setattr(install_vhi, "_resolve_latest_tag", lambda: "v1.0.0")
        with pytest.raises(typer.Exit):
            install_vhi._check_supported("v1.0.0")
        err = capsys.readouterr().err
        assert "too old" in err
        assert install_vhi.MIN_VHI_TAG in err, "it must say which version to get"
        assert "VHI_PATH" in err, "and that source-mode needs no release at all"

    def test_latest_is_resolved_before_it_is_judged(self, monkeypatch):
        """`latest` is a pointer; judging the literal string would never refuse."""
        monkeypatch.setattr(install_vhi, "_resolve_latest_tag", lambda: "v1.0.0")
        with pytest.raises(typer.Exit):
            install_vhi._check_supported("latest")

    def test_a_new_enough_release_is_allowed_through(self, monkeypatch):
        monkeypatch.setattr(install_vhi, "_resolve_latest_tag", lambda: "v2.3.0")
        assert install_vhi._check_supported("latest") == "v2.3.0"

    def test_an_unresolvable_latest_warns_rather_than_blocking(self, capsys, monkeypatch):
        """Offline should not stop someone installing; it should tell them the risk."""
        monkeypatch.setattr(install_vhi, "_resolve_latest_tag", lambda: None)
        assert install_vhi._check_supported("latest") == "latest"
        assert "WARNING" in capsys.readouterr().err

    def test_a_non_version_tag_is_not_judged(self, monkeypatch):
        """A branch build is the caller's business, not a version to compare."""
        monkeypatch.setattr(install_vhi, "_resolve_latest_tag", lambda: "main")
        assert install_vhi._check_supported("main") == "main"


class TestTheLauncherRefusesAnOldInstall:
    @staticmethod
    def _spec(tmp_path, marker: str | None, process=("/does/not/matter",)):
        """A spec gated exactly as `virtual_hand` gates its own.

        The gate is VHI's, not `InterfaceSpec`'s: it reads a marker only VHI's installer
        leaves behind, so the generic spec only knows to *call* it.
        """
        if marker is not None:
            (tmp_path / "vhi-version.txt").write_text(marker)
        return InterfaceSpec(
            name="VHI Hand",
            n_output_channels=9,
            output_hz=32.0,
            install_root=tmp_path,
            process=process,
            version_gate=partial(interfaces._refuse_an_incompatible_install, tmp_path),
        )

    def test_an_old_marker_stops_the_launch(self, tmp_path):
        spec = self._spec(tmp_path, "installed_tag=v1.0.0\nasset=x.zip\n")
        with pytest.raises(FileNotFoundError, match="does not serve the v2 control"):
            spec.launcher()

    def test_the_refusal_says_how_to_fix_it(self, tmp_path):
        spec = self._spec(tmp_path, "installed_tag=v1.0.0\n")
        with pytest.raises(FileNotFoundError) as excinfo:
            spec.launcher()
        assert "--force" in str(excinfo.value), "upgrading over an install needs it"
        assert "VHI_PATH" in str(excinfo.value)

    def test_a_new_enough_marker_launches(self, tmp_path):
        spec = self._spec(tmp_path, "installed_tag=v2.0.0\n")
        assert spec.launcher() == [("VHI Hand", ["/does/not/matter"])]

    def test_no_marker_launches(self, tmp_path):
        """A source-mode checkout has none, and neither does a hand-placed build.

        Absence is not evidence of an old version, so refusing here would break the one
        path that works while no v2 release exists.
        """
        spec = self._spec(tmp_path, None)
        assert spec.launcher() == [("VHI Hand", ["/does/not/matter"])]

    def test_an_unreadable_marker_launches(self, tmp_path):
        """Never let a diagnostic become the thing that stops the app."""
        (tmp_path / "vhi-version.txt").mkdir()
        spec = self._spec(tmp_path, None, process=("/x",))
        assert spec.launcher() == [("VHI Hand", ["/x"])]
