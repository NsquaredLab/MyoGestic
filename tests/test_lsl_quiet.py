"""The liblsl console-noise fallback, and the three things it must not shadow.

At liblsl's default level one outlet logs a line per network interface, and MyoGestic
publishes one outlet per control it drives. `myogestic._lsl_quiet` points `LSLAPICFG` at a
shipped config that only lowers verbosity.

The shadowing cases are the point of this file. liblsl looks in `$LSLAPICFG`, then
`./lsl_api.cfg`, then `~/lsl_api.cfg`; setting `LSLAPICFG` overrides all three. This repo's
own `lsl_api.cfg` disables IPv6 to avoid an Apple WLAN driver deadlock, so a fallback that
shadowed a working-directory config would quietly put that back.
"""

import os
from pathlib import Path

from myogestic._lsl_quiet import _FALLBACK, quiet_liblsl


def test_the_shipped_config_only_sets_the_log_level(tmp_path, monkeypatch):
    """Anything else in it would be MyoGestic changing a user's networking."""
    text = _FALLBACK.read_text(encoding="utf-8")
    sections = [line.strip() for line in text.splitlines() if line.strip().startswith("[")]
    assert sections == ["[log]"], f"the fallback config configures more than logging: {sections}"


def test_it_uses_semicolon_comments():
    """liblsl's parser ignores a `#`-commented file's settings without saying so."""
    commented = [
        line for line in _FALLBACK.read_text(encoding="utf-8").splitlines() if line.strip().startswith("#")
    ]
    assert not commented, f"liblsl does not parse `#` comments: {commented}"


def test_it_sets_lslapicfg_when_nothing_else_configures_liblsl(tmp_path, monkeypatch):
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    assert quiet_liblsl() is True
    assert os.environ["LSLAPICFG"] == str(_FALLBACK)


def test_it_backs_off_when_the_user_set_lslapicfg(tmp_path, monkeypatch):
    monkeypatch.setenv("LSLAPICFG", "/somewhere/mine.cfg")
    monkeypatch.chdir(tmp_path)

    assert quiet_liblsl() is False
    assert os.environ["LSLAPICFG"] == "/somewhere/mine.cfg"


def test_it_backs_off_for_a_config_in_the_working_directory(tmp_path, monkeypatch):
    """The case that matters: this repo's own config disables IPv6, and lives in cwd."""
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    (tmp_path / "lsl_api.cfg").write_text("[ports]\nIPv6 = disable\n")

    assert quiet_liblsl() is False
    assert "LSLAPICFG" not in os.environ, "shadowed a working-directory config"


def test_it_backs_off_for_a_config_in_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.chdir(tmp_path / "..")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "lsl_api.cfg").write_text("[log]\nlevel = 0\n")

    assert quiet_liblsl() is False
    assert "LSLAPICFG" not in os.environ, "shadowed a home-directory config"


def test_this_repo_keeps_its_own_config_quiet_too():
    """The repo config is used verbatim when running from here, so it needs the level itself."""
    repo_cfg = Path(__file__).resolve().parent.parent / "lsl_api.cfg"
    if not repo_cfg.is_file():
        return
    text = repo_cfg.read_text(encoding="utf-8")
    assert "[log]" in text and "level = -2" in text, (
        "running from the repo root uses this file instead of the shipped fallback, "
        "so it has to set the log level itself"
    )


def test_it_survives_a_home_directory_that_cannot_be_resolved(tmp_path, monkeypatch):
    """`Path.home()` raises `RuntimeError`, not `OSError`, when it cannot resolve `~`.

    This runs at `import myogestic`, so an unhandled raise here takes the whole package
    down — which is what would happen in a container with no `HOME` and no passwd entry.
    """
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.chdir(tmp_path)

    def _no_home():
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(Path, "home", staticmethod(_no_home))

    assert quiet_liblsl() is True, "an unresolvable home should not stop the fallback"
    assert os.environ["LSLAPICFG"] == str(_FALLBACK)


def test_it_does_nothing_in_the_browser(tmp_path, monkeypatch):
    """Pyodide has no liblsl, and probing a filesystem it does not have is pointless."""
    monkeypatch.delenv("LSLAPICFG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("myogestic._lsl_quiet._IS_BROWSER", True)

    assert quiet_liblsl() is False
    assert "LSLAPICFG" not in os.environ
