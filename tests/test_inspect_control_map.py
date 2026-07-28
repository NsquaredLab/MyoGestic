"""The generic control-map validator, `tools/inspect_control_map.py`.

This is the tool behind the "Inspect a TOML control map" launch entry, so it runs against
files nobody here wrote. Two things matter: its exit status has to be trustworthy — it is
usable in a hook or in CI — and a verdict of "usable" has to mean the map really would
bind, not merely that every address exists.

That second point is the interesting one. `resolve` cannot see two aliases landing on one
physical control, because a target publishes the short and axis forms of a control as two
addresses sharing a channel; only something putting both on a wire finds out. The
validator reproduces that check from the manifest rather than declaring anything to a
live target, and these tests are what keep the two verdicts in agreement.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import inspect_control_map as tool  # noqa: E402

from myogestic.controls import Capability  # noqa: E402

#: A stand-in for VHI's manifest, with the aliasing that makes collisions possible:
#: `vhi.prediction.thumb` and `...thumb.flexion` are one channel under two names.
MANIFEST = [
    Capability(
        "vhi.prediction.thumb", "continuous", -1.0, 1.0, 0.0, channel=0,
        stream_name="MyoGestic_Output",
    ),
    Capability(
        "vhi.prediction.thumb.flexion", "continuous", -1.0, 1.0, 0.0, channel=0,
        stream_name="MyoGestic_Output",
    ),
    Capability(
        "vhi.prediction.index", "continuous", -1.0, 1.0, 0.0, channel=2,
        stream_name="MyoGestic_Output",
    ),
    Capability(
        "vhi.prediction.middle", "continuous", -1.0, 1.0, 0.0, channel=3,
        stream_name="MyoGestic_Output",
    ),
    # A different hand, numbering from 0 again — so a channel number means nothing
    # without its stream.
    Capability(
        "vhi.control.pose.thumb", "continuous", -1.0, 1.0, 0.0, channel=0,
        stream_name="MyoGestic_ControlPose",
    ),
    Capability(
        "vhi.control.gesture", "discrete", states=("Rest", "Fist"), rest_state="Rest",
    ),
]


class _Client:
    def stop(self) -> None: ...


@pytest.fixture
def target(monkeypatch):
    """Answer the manifest without a Virtual Hand."""
    monkeypatch.setattr(tool, "_manifest", lambda: (MANIFEST, _Client()))


@pytest.fixture
def no_target(monkeypatch):
    """Nothing running: only the file itself can be checked."""
    monkeypatch.setattr(tool, "_manifest", lambda: (None, None))


def _write(tmp_path: pathlib.Path, body: str) -> str:
    path = tmp_path / "controls.toml"
    path.write_text(body)
    return str(path)


GOOD = """
[dofs]
grip = [
  { target = "vhi.prediction.index", weight = 0.8 },
  { target = "vhi.prediction.middle" },
]
"""


class TestTheVerdictIsTrustworthy:
    """Exit status, since a hook or CI job will act on it."""

    def test_a_usable_map_passes(self, tmp_path, target):
        assert tool.main([_write(tmp_path, GOOD)]) == 0

    def test_an_unknown_address_fails(self, tmp_path, target):
        assert tool.main([_write(tmp_path, '[dofs]\na = "vhi.prediction.wrist"\n')]) == 1

    def test_a_map_that_would_not_bind_fails_even_though_resolve_accepts_it(
        self, tmp_path, target, capsys
    ):
        """The whole reason this check exists: two names, one channel."""
        from myogestic.controls import load_control_map, resolve  # noqa: PLC0415

        body = '[dofs]\na = "vhi.prediction.thumb"\nb = "vhi.prediction.thumb.flexion"\n'
        # resolve() is happy — both addresses are real.
        resolve(load_control_map({"dofs": {
            "a": "vhi.prediction.thumb", "b": "vhi.prediction.thumb.flexion",
        }}), MANIFEST)
        # The validator is not.
        assert tool.main([_write(tmp_path, body)]) == 1
        assert "same control" in capsys.readouterr().err

    def test_the_same_channel_on_two_different_streams_is_not_a_collision(
        self, tmp_path, target
    ):
        """Both hands number from 0; conflating them would refuse a valid map."""
        body = (
            '[dofs]\n'
            'predicted = "vhi.prediction.thumb"\n'
            'operator = "vhi.control.pose.thumb"\n'
        )
        assert tool.main([_write(tmp_path, body)]) == 0

    def test_a_discrete_alias_does_not_collide_with_a_channel(self, tmp_path, target):
        """A held state travels over gRPC, so it claims no channel."""
        body = (
            '[dofs]\n'
            'grip = "vhi.prediction.index"\n'
            'gesture = { target = "vhi.control.gesture", debounce_s = 0.1 }\n'
        )
        assert tool.main([_write(tmp_path, body)]) == 0

    @pytest.mark.parametrize(
        "body",
        [
            "[settings]\nfoo = 1\n",  # no [dofs]
            "[dofs\nbroken = \n",  # not TOML
            "[dofs]\n",  # nothing declared
            '[dofs]\nx = "wrist"\n',  # not an address
            '[dofs]\nmy.thumb = "vhi.prediction.thumb"\n',  # TOML's nested-key trap
        ],
        ids=["no-dofs", "malformed", "empty", "not-an-address", "nested-key"],
    )
    def test_an_unusable_file_fails_before_a_target_is_needed(
        self, tmp_path, no_target, body
    ):
        assert tool.main([_write(tmp_path, body)]) == 1

    def test_a_missing_file_fails(self, tmp_path, no_target):
        assert tool.main([str(tmp_path / "nope.toml")]) == 1

    def test_a_blank_path_says_so_rather_than_inspecting_the_cwd(self, capsys, no_target):
        """VS Code passes an empty prompt through; `Path("")` is `.`, a directory."""
        assert tool.main([""]) == 1
        assert "no path given" in capsys.readouterr().err

    def test_a_structurally_valid_map_passes_with_nothing_running(self, tmp_path, no_target):
        """Absence of a target is not a failure — it is a smaller check."""
        assert tool.main([_write(tmp_path, GOOD)]) == 0


class TestItReportsWhatTheUserAskedToSee:
    """Aliases, group members, weights, and the gates — the point of running it."""

    @pytest.fixture
    def report(self, tmp_path, target, capsys) -> str:
        body = GOOD + (
            'squeeze = { target = "vhi.prediction.thumb", threshold_fraction = 0.4 }\n'
            'gesture = { target = "vhi.control.gesture", debounce_s = 0.25 }\n'
        )
        assert tool.main([_write(tmp_path, body)]) == 0
        return capsys.readouterr().out

    def test_it_names_every_alias(self, report):
        for alias in ("grip", "squeeze", "gesture"):
            assert alias in report

    def test_it_lists_the_members_of_a_group(self, report):
        assert "vhi.prediction.index" in report
        assert "vhi.prediction.middle" in report
        assert "2 controls" in report, "a fan-out must be shown as one output to many"

    def test_it_shows_the_weight_on_each_member(self, report):
        assert "x0.8" in report
        assert "x1.0" in report, "the implicit weight is shown too, or 0.8 looks absolute"

    def test_it_shows_the_gates(self, report):
        assert "threshold_fraction=0.4" in report
        assert "debounce_s=0.25" in report

    def test_it_says_which_facts_came_from_the_target(self, report):
        """The one idea a reader has to leave with."""
        assert "came from the target" in report
        assert "HELD STATE" in report, "the kind is target-declared and must be visible"
