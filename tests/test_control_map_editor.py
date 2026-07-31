"""`ControlMapEditor` — the authoring UI's logic, without a renderer or a window.

The drawing needs ImGui and the manifest needs a running VHI, but neither is where the
risk is. The risk is in the parts that decide whether a file is safe to write: the
validation, the collision rule, and the round trip through the TOML that stays the source
of truth. Those are ordinary methods, so they are tested as ordinary methods.

The property that matters most: **a save either produces a file `load_control_map` reads
back unchanged, or does not happen.** An editor that could write a file its own loader
rejects would be worse than no editor, because something else is reading that file.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from myogestic.controls import Capability, load_control_map
from myogestic.widgets import ControlMapEditor

#: A stand-in for VHI's manifest, including the aliasing that makes collisions possible:
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
    # The thumb's second axis: its own channel, so it is a different control rather than
    # another name for one. Without it here, the "not collapsed away" test had nothing to
    # assert against.
    Capability(
        "vhi.prediction.thumb.abduction", "continuous", -1.0, 1.0, 0.0, channel=1,
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
    # A second hand, numbering from 0 again — a channel means nothing without its stream.
    Capability(
        "vhi.control.pose.thumb", "continuous", -1.0, 1.0, 0.0, channel=0,
        stream_name="MyoGestic_ControlPose",
    ),
    Capability(
        "vhi.control.gesture", "discrete", states=("Rest", "Fist", "Pointing"),
        rest_state="Rest",
    ),
]


class _Client:
    def capabilities(self):
        return MANIFEST


def _editor(tmp_path, body: str | None = None, *, connected: bool = True):
    path = tmp_path / "controls.toml"
    if body is not None:
        path.write_text(body)
    editor = ControlMapEditor(path, client=_Client() if connected else None)
    editor.load()
    if connected:
        editor._connect()
    return editor


GOOD = """
[dofs]
grip = [
  { target = "vhi.prediction.index", weight = 0.8 },
  { target = "vhi.prediction.middle" },
]
"""


class TestTheFileStaysTheSourceOfTruth:
    def test_a_file_loads_into_editable_entries(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        assert [e["alias"] for e in editor._draft] == ["grip"]
        assert editor._draft[0]["targets"] == [
            ["vhi.prediction.index", 0.8],
            ["vhi.prediction.middle", 1.0],
        ]

    def test_saving_then_loading_changes_nothing(self, tmp_path):
        """The round trip that makes this an editor rather than a second store."""
        editor = _editor(tmp_path, GOOD)
        before = editor.as_control_map().as_control_space()
        assert editor.save() is True
        editor.load()
        assert editor.as_control_map().as_control_space() == before

    def test_what_it_writes_is_what_load_control_map_reads(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor.save()
        with editor.path.open("rb") as handle:
            reparsed = load_control_map(tomllib.load(handle))
        assert reparsed.as_control_space() == editor.as_control_map().as_control_space()

    def test_an_absent_file_starts_an_empty_map_rather_than_failing(self, tmp_path):
        """Creating a map is the same act as editing one."""
        editor = ControlMapEditor(tmp_path / "new.toml", client=_Client())
        editor.load()
        assert editor._draft == []
        assert "does not exist yet" in editor._message
        assert not editor.path.exists(), "loading must not create it"

    def test_saving_creates_the_file(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("my_index", "vhi.prediction.index")
        assert editor.save() is True
        assert editor.path.exists()
        with editor.path.open("rb") as handle:
            assert "my_index" in load_control_map(tomllib.load(handle)).bindings

    def test_a_broken_file_is_shown_rather_than_raised(self, tmp_path):
        """This is the tool you would use to fix a broken file, so it must open one."""
        editor = _editor(tmp_path, "[dofs\nbroken =\n")
        assert editor._error
        assert editor._draft == []

    def test_a_file_that_parses_but_is_not_a_map_is_shown_too(self, tmp_path):
        editor = _editor(tmp_path, '[dofs]\nx = "not-an-address"\n')
        assert editor._error
        assert "address" in editor._error

    def test_the_written_file_carries_a_header_for_whoever_opens_it_next(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor.save()
        text = editor.path.read_text()
        assert text.startswith("#")
        assert "source of truth" in text


class TestSaveIsBlockedWhileTheMapIsWrong:
    """A disabled Save with a reason beats a rejected write, and beats a bad file."""

    def test_a_valid_map_has_no_problems(self, tmp_path):
        assert _editor(tmp_path, GOOD).problems() == []

    def test_two_aliases_with_one_name_are_refused(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor.add_control("grip", "vhi.prediction.thumb")
        editor._draft[-1]["alias"] = "grip"
        assert any("used twice" in p for p in editor.problems())
        assert editor.as_control_map() is None
        assert editor.save() is False

    def test_an_unnamed_control_is_refused(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._draft[0]["alias"] = "  "
        assert any("no name" in p for p in editor.problems())

    def test_a_control_pointing_nowhere_is_refused(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("my_index")
        assert any("points at nothing" in p for p in editor.problems())

    def test_an_address_the_target_does_not_export_is_refused(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("my_wrist", "vhi.prediction.wrist")
        assert any("does not export" in p for p in editor.problems())

    def test_two_aliases_on_one_channel_are_refused_even_under_two_names(self, tmp_path):
        """The conflict `resolve` cannot see: one channel, two addresses naming it."""
        editor = _editor(tmp_path, None)
        editor.add_control("a", "vhi.prediction.thumb")
        editor.add_control("b", "vhi.prediction.thumb.flexion")
        problems = editor.problems()
        assert any("same control" in p for p in problems), problems
        assert editor.save() is False

    def test_the_same_channel_on_two_streams_is_not_a_collision(self, tmp_path):
        """Both hands number from 0, and conflating them would be the wrong diagnosis.

        Mixing the hands in one map *is* refused — see `TestOneMapDrivesOneHand` — but as
        "one map controls one hand", not as "these two reach the same control". The channel
        numbers matching is a coincidence of two hands both counting from zero.
        """
        editor = _editor(tmp_path, None)
        editor.add_control("predicted", "vhi.prediction.thumb")
        editor.add_control("operator", "vhi.control.pose.thumb")
        assert not any("same control" in p for p in editor.problems())

    def test_one_alias_fanning_out_to_several_controls_is_fine(self, tmp_path):
        """The distinction the collision rule must not blur: one output, many controls."""
        editor = _editor(tmp_path, None)
        editor.add_control("fist", "vhi.prediction.index")
        editor._draft[0]["targets"].append(["vhi.prediction.middle", 0.6])
        assert editor.problems() == []

    @pytest.mark.parametrize("weight", [0.0, 1.5, 2.0, -1.5])
    def test_a_weight_outside_the_usable_range_is_refused(self, tmp_path, weight):
        editor = _editor(tmp_path, None)
        editor.add_control("a", "vhi.prediction.index")
        editor._draft[0]["targets"][0][1] = weight
        assert any("weight" in p for p in editor.problems())

    def test_a_negative_weight_is_allowed_and_survives_a_save(self, tmp_path):
        """The library permits one on a signed target, so refusing here would make a
        valid hand-written file unsavable the moment it was opened."""
        editor = _editor(tmp_path, None)
        editor.add_control("wrist", "vhi.prediction.index")
        editor._draft[0]["targets"][0][1] = -0.5
        assert editor.problems() == []
        assert editor.save() is True
        editor.load()
        assert editor._draft[0]["targets"][0][1] == -0.5

    @pytest.mark.parametrize("fraction", [-0.1, 1.1])
    def test_a_cutoff_outside_zero_to_one_is_refused(self, tmp_path, fraction):
        editor = _editor(tmp_path, None)
        editor.add_control("a", "vhi.prediction.index")
        editor._draft[0]["threshold_fraction"] = fraction
        assert any("threshold_fraction" in p for p in editor.problems())

    def test_nothing_is_written_while_a_problem_stands(self, tmp_path):
        """The point of all of the above: the file on disk stays loadable."""
        editor = _editor(tmp_path, GOOD)
        original = editor.path.read_text()
        editor.add_control("a", "vhi.prediction.thumb")
        editor.add_control("b", "vhi.prediction.thumb.flexion")
        assert editor.save() is False
        assert editor.path.read_text() == original


class TestEditing:
    def test_a_new_control_gets_a_free_numbered_name(self, tmp_path):
        """Numbered from one, with no bare first entry: the sequence reads the same all
        the way down instead of `my_control`, `my_control_2`, `my_control_3`."""
        editor = _editor(tmp_path, None)
        for _ in range(3):
            editor.add_control()
        assert [e["alias"] for e in editor._draft] == [
            "my_control_1",
            "my_control_2",
            "my_control_3",
        ]

    def test_it_numbers_around_a_name_the_file_already_had(self, tmp_path):
        path = tmp_path / "controls.toml"
        path.write_text('[dofs]\nmy_control = "vhi.prediction.index"\n')
        editor = ControlMapEditor(path, client=_Client())
        editor.load()
        editor._connect()
        editor.add_control()
        editor.add_control()
        assert [e["alias"] for e in editor._draft] == [
            "my_control",
            "my_control_1",
            "my_control_2",
        ]

    def test_an_asked_for_name_is_kept_and_only_collisions_are_suffixed(self, tmp_path):
        """A caller that named it meant that name; the suffix is for the second one on."""
        editor = _editor(tmp_path, None)
        editor.add_control("wrist")
        editor.add_control("wrist")
        editor.add_control("wrist")
        assert [e["alias"] for e in editor._draft] == ["wrist", "wrist_1", "wrist_2"]

    def test_a_requested_name_is_kept_when_it_is_free(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("wrist", "vhi.prediction.index")
        assert editor._draft[0]["alias"] == "wrist"

    def test_reload_discards_unsaved_edits(self, tmp_path):
        """The working copy is not a store: nothing survives that the file does not."""
        editor = _editor(tmp_path, GOOD)
        editor.add_control("scratch", "vhi.prediction.thumb")
        editor.load()
        assert [e["alias"] for e in editor._draft] == ["grip"]

    def test_a_gate_survives_the_round_trip(self, tmp_path):
        """Each gate on the kind of control it belongs to.

        Both on one entry is what this used to assert, and it is a combination `resolve`
        refuses: a hold has nothing to hold on a number.
        """
        editor = _editor(tmp_path, None)
        editor.add_control("fist", "vhi.prediction.index")
        editor._draft[0]["threshold_fraction"] = 0.4
        editor.add_control("gesture", "vhi.control.gesture")
        editor._draft[1]["debounce_s"] = 0.25
        assert editor.save() is True, editor.problems()
        editor.load()
        assert editor._draft[0]["threshold_fraction"] == 0.4
        assert editor._draft[1]["debounce_s"] == 0.25


class TestItExplainsWhatTheTargetWouldMakeOfIt:
    def test_it_reports_each_route_with_its_weight(self, tmp_path):
        summary = _editor(tmp_path, GOOD).resolved_summary()
        assert "grip" in summary
        assert "index x0.8" in summary
        assert "middle x1.0" in summary

    def test_it_names_a_held_state_as_such(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("gesture", "vhi.control.gesture")
        assert "held state" in editor.resolved_summary()

    def test_it_shows_the_cutoff_for_a_classifier_input(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("fist", "vhi.prediction.index")
        editor._draft[0]["threshold_fraction"] = 0.5
        assert "on at >= 0.5" in editor.resolved_summary()

    def test_it_says_so_rather_than_guessing_when_offline(self, tmp_path):
        editor = _editor(tmp_path, GOOD, connected=False)
        assert "Not connected" in editor.resolved_summary()

    def test_it_points_at_the_problems_rather_than_resolving_a_bad_map(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control("a")           # no target
        assert "problems" in editor.resolved_summary()


class TestItWorksWithoutATarget:
    """Offline it is a plain text editor with validation — not a broken one."""

    def test_it_loads_and_saves_with_no_client(self, tmp_path):
        editor = _editor(tmp_path, GOOD, connected=False)
        assert [e["alias"] for e in editor._draft] == ["grip"]
        assert editor.save() is True

    def test_an_unknown_address_is_not_flagged_without_a_manifest(self, tmp_path):
        """It cannot know. Inventing a refusal from an empty list would block everything."""
        editor = _editor(tmp_path, None, connected=False)
        editor.add_control("a", "some.target.address")
        assert editor.problems() == []

    def test_pressing_connect_with_nothing_running_says_so(self, tmp_path):
        """A pressed button with no visible effect is worse than a line of noise.

        The *timer* stays silent — see `test_the_background_retry_says_nothing`. This is the
        press, which has to answer.
        """

        class Silent:
            def capabilities(self):
                return None

        editor = ControlMapEditor(tmp_path / "c.toml", client=Silent())
        editor.load()
        editor._asked = True          # what the button sets
        editor._connect()
        assert editor.capabilities == ()
        assert "did not answer" in editor._message

    def test_the_background_retry_says_nothing(self, tmp_path):
        """Connecting is on a timer, so a report per round is a report forever.

        This is the line the user actually saw: "1 target(s) did not answer", permanently, for
        a target they had not asked about and a retry they did not press.
        """

        class Silent:
            def capabilities(self):
                return None

        editor = ControlMapEditor(tmp_path / "c.toml", client=Silent())
        editor.load()
        editor._message = ""          # `load` says the file is new; that is not this
        editor._connect()             # no `_asked`: this is the timer
        assert editor._message == "", "the timer wrote a line nobody asked for"


class TestTheFileCanBeEditedAsText:
    """The other way in: type TOML directly, not just fill fields.

    Same contract as the fields, from the other direction — nothing invalid gets into the
    working copy, so `Save` still cannot write a file that would not load back. That is
    what makes a free-text box safe to point at a file something else is reading.
    """

    def test_the_text_is_the_file_verbatim_when_nothing_has_changed(self, tmp_path):
        """Comments included — opening the text view must not silently eat them."""
        path = tmp_path / "controls.toml"
        path.write_text("# my notes\n[dofs]\nclose = \"vhi.prediction.index\"\n")
        editor = ControlMapEditor(path, client=_Client())
        editor.load()
        assert editor.raw_text().startswith("# my notes")

    def test_it_renders_from_the_fields_once_they_have_diverged(self, tmp_path):
        """Stale text beside live fields is worse than losing the comments."""
        editor = _editor(tmp_path, GOOD)
        editor.add_control("extra", "vhi.prediction.thumb")
        assert "extra" in editor.raw_text()

    def test_valid_text_replaces_the_working_copy(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        assert editor.apply_raw(
            '[dofs]\ngrip = { target = "vhi.prediction.thumb", weight = 0.5 }\n'
        )
        assert [e["alias"] for e in editor._draft] == ["grip"]
        assert editor._draft[0]["targets"] == [["vhi.prediction.thumb", 0.5]]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("[dofs", "Not valid TOML"),
            ("[settings]\nx = 1\n", "No [dofs] table"),
            ('[dofs]\nx = "nope"\n', "is not a target address"),
            ('[dofs]\nx = { target = "vhi.prediction.index", threshold_fraction = 7 }\n',
             "threshold_fraction"),
        ],
        ids=["malformed", "no-dofs", "bad-address", "bad-fraction"],
    )
    def test_bad_text_is_refused_with_the_reason(self, tmp_path, text, expected):
        editor = _editor(tmp_path, GOOD)
        before = [dict(entry) for entry in editor._draft]
        assert editor.apply_raw(text) is False
        assert expected in editor._raw_error
        assert editor._draft == before, "a refused apply must change nothing"

    def test_text_that_parses_but_would_not_bind_still_blocks_the_save(self, tmp_path):
        """Two aliases on one channel: valid TOML, valid addresses, unusable map."""
        editor = _editor(tmp_path, GOOD)
        original = editor.path.read_text()
        assert editor.apply_raw(
            '[dofs]\na = "vhi.prediction.thumb"\nb = "vhi.prediction.thumb.flexion"\n'
        ), "the text itself is valid, so applying it succeeds"
        assert editor.problems(), "but the map is not usable"
        assert editor.save() is False
        assert editor.path.read_text() == original

    def test_a_round_trip_through_the_text_changes_nothing(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        before = editor.as_control_map().as_control_space()
        assert editor.apply_raw(editor.raw_text())
        assert editor.as_control_map().as_control_space() == before

    def test_unparseable_text_on_disk_is_shown_so_it_can_be_fixed(self, tmp_path):
        """The editor has to be usable *on* a broken file, not just a good one."""
        path = tmp_path / "controls.toml"
        path.write_text("[dofs\nbroken =\n")
        editor = ControlMapEditor(path, client=_Client())
        editor.load()
        assert "broken" in editor.raw_text()


class TestThePickerRowsAreReadable:
    """What a row says is the only thing standing between a user and the address syntax.

    The list has one genuine surprise in it: a renderer publishes the short and the
    explicit-axis form of a control as two addresses on **one** channel, so eleven rows
    can mean six controls. A row that hides that invites someone to map two of their
    outputs onto the same finger and only find out at the save.
    """

    @pytest.fixture
    def editor(self, tmp_path):
        return _editor(tmp_path, GOOD)

    @pytest.mark.parametrize(
        "address",
        [
            "vhi.prediction.thumb",
            "vhi.prediction.thumb.flexion",
            "vhi.control.pose.thumb",
            "vhi.control.gesture",
        ],
    )
    def test_a_row_shows_the_address_the_file_uses(self, editor, address):
        """No prettier short form. A shortened name is a second vocabulary for the same
        thing: you would read `thumb` in the picker and have to know it means
        `vhi.prediction.thumb` in the TOML."""
        cap = next(c for c in MANIFEST if c.address == address)
        assert editor._describe(cap).startswith(address)

    def test_a_row_carries_no_channel_number(self, editor):
        """A wire index is not something a reader should decode to pick a finger, and with
        one row per control there is nothing left for it to disambiguate."""
        cap = next(c for c in MANIFEST if c.address == "vhi.prediction.index")
        assert editor._describe(cap) == "vhi.prediction.index"

    def test_an_unstreamed_control_is_not_offered_at_all(self, editor):
        """It cannot be driven this way, so offering it only earns a refusal later."""
        off = Capability(
            "vhi.grip.force", "continuous", 0.0, 1.0, 0.0, channel=-1,
            stream_name="MyoGestic_Output",
        )
        editor._capabilities = (*editor._capabilities, off)
        assert "vhi.grip.force" not in [c.address for c in editor._offered()]

    def test_a_discrete_row_names_the_states_it_accepts(self, editor):
        """Named rather than counted, while they fit. "3 states" makes a reader go and look
        them up; the names are the answer they were going to look for."""
        cap = next(c for c in MANIFEST if c.kind == "discrete")
        described = editor._describe(cap)
        assert " / ".join(cap.states) in described

    def test_the_aliased_forms_of_one_control_are_reported_as_peers(self, editor):
        """`thumb` and `thumb.flexion` are one channel; a user has to be able to see it."""
        thumb = next(c for c in MANIFEST if c.address == "vhi.prediction.thumb")
        assert editor._peers(thumb) == ["vhi.prediction.thumb.flexion"]
        # Reported as addresses too, for the same reason the rows are.
        assert all(peer.startswith("vhi.") for peer in editor._peers(thumb))

    def test_a_control_with_its_own_channel_has_no_peers(self, editor):
        alone = next(c for c in MANIFEST if c.address == "vhi.prediction.index")
        assert editor._peers(alone) == []

    def test_the_same_channel_on_another_stream_is_not_a_peer(self, editor):
        """Both hands number from 0 — conflating them would claim two hands are one."""
        predicted = next(c for c in MANIFEST if c.address == "vhi.prediction.thumb")
        assert "vhi.control.pose.thumb" not in editor._peers(predicted)

    def test_a_row_carries_the_address_and_nothing_it_does_not_need(self, editor):
        for cap in MANIFEST:
            described = editor._describe(cap)
            assert described.count(cap.address) == 1, "the address, exactly once"
            assert "ch" not in described.replace(cap.address, ""), described


class TestTheRangeIsOnlyShownWhenItIsNews:
    """`[-1..+1]` on all twenty-two rows is not information, it is wallpaper.

    Signed and normalized is the standard, and every control a Virtual Hand declares uses
    it — so printing it on every line trains the eye to skip the column, which is exactly
    where a one-way `[0..1]` would then hide. It is stated when it differs and left unsaid
    when it does not; the selected control's full facts are on the picker's own tooltip.
    """

    @pytest.fixture
    def editor(self, tmp_path):
        return _editor(tmp_path, GOOD)

    def test_the_signed_default_is_left_unsaid(self, editor):
        cap = next(c for c in MANIFEST if c.address == "vhi.prediction.index")
        described = editor._describe(cap)
        assert "-1" not in described and "+1" not in described
        assert described == "vhi.prediction.index", "the address, and nothing else"

    def test_a_one_way_range_is_called_out(self, editor):
        one_way = Capability(
            "vhi.grip.force", "continuous", 0.0, 1.0, 0.0, channel=7,
            stream_name="MyoGestic_Output",
        )
        assert "[+0.0..+1.0]" in editor._describe(one_way)

    def test_an_asymmetric_range_is_called_out(self, editor):
        odd = Capability(
            "vhi.wrist.rotation", "continuous", -0.5, 1.0, 0.0, channel=8,
            stream_name="MyoGestic_Output",
        )
        assert "[-0.5..+1.0]" in editor._describe(odd)

    def test_the_full_facts_are_still_available_on_the_selected_control(self, editor):
        """Nothing is lost by leaving the usual case unsaid — `_summary` is the tooltip."""
        cap = next(c for c in MANIFEST if c.address == "vhi.prediction.index")
        summary = editor._summary(cap)
        assert "-1.0" in summary and "+1.0" in summary
        assert "channel 2" in summary


class TestOneMapDrivesOneHand:
    """The picker must not offer a control the map's own target cannot drive.

    A `VhiTarget` drives one hand, so a map mixing `vhi.prediction.*` with
    `vhi.control.pose.*` cannot bind. The editor knew each control's stream all along and
    ignored it: it offered all 23, validated a cross-hand pick as fine, enabled Save, wrote
    the file — and the refusal then arrived from the bus, three layers from the click. The
    two hands even share channel numbers, so this is not a cosmetic mix-up.
    """

    @pytest.mark.parametrize(
        ("stream", "offered", "withheld"),
        [
            ("output", "vhi.prediction.thumb", "vhi.control.pose.thumb"),
            ("control_pose", "vhi.control.pose.thumb", "vhi.prediction.thumb"),
        ],
    )
    def test_only_its_own_hand_is_offered(self, tmp_path, stream, offered, withheld):
        path = tmp_path / "controls.toml"
        path.write_text(GOOD)
        editor = ControlMapEditor(path, client=_Client(), stream=stream)
        editor.load()
        editor._connect()
        addresses = [cap.address for cap in editor._offered()]
        assert offered in addresses
        assert withheld not in addresses

    def test_a_held_state_is_offered_to_both(self, tmp_path):
        """Discrete controls travel over gRPC, so they belong to neither hand."""
        for stream in ("output", "control_pose"):
            path = tmp_path / f"{stream}.toml"
            path.write_text(GOOD)
            editor = ControlMapEditor(path, client=_Client(), stream=stream)
            editor.load()
            editor._connect()
            assert "vhi.control.gesture" in [c.address for c in editor._offered()]

    def test_an_address_from_the_other_hand_blocks_the_save(self, tmp_path):
        """The case from the screenshot: picked, saved, then refused by the bus."""
        path = tmp_path / "controls.toml"
        path.write_text('[dofs]\nmy_control = "vhi.control.pose.thumb"\n')
        editor = ControlMapEditor(path, client=_Client(), stream="output")
        editor.load()
        editor._connect()
        problems = editor.problems()
        assert any("one hand" in p for p in problems), problems
        assert editor.save() is False
        # And it says why a held state is *not* caught by the same rule.
        assert any("gRPC" in p for p in problems), problems

    def test_the_reason_names_both_hands_in_plain_words(self, tmp_path):
        """"not a streamed continuous control on 'MyoGestic_Output'" is not an answer."""
        path = tmp_path / "controls.toml"
        path.write_text('[dofs]\nmy_control = "vhi.control.pose.thumb"\n')
        editor = ControlMapEditor(path, client=_Client(), stream="output")
        editor.load()
        editor._connect()
        reason = next(p for p in editor.problems() if "one hand" in p)
        assert "operator's hand" in reason
        assert "model's hand" in reason

    def test_the_same_file_is_fine_as_a_control_hand_map(self, tmp_path):
        """Nothing is wrong with the address — only with which map it was put in."""
        path = tmp_path / "controls.toml"
        path.write_text('[dofs]\nmy_control = "vhi.control.pose.thumb"\n')
        editor = ControlMapEditor(path, client=_Client(), stream="control_pose")
        editor.load()
        editor._connect()
        assert editor.problems() == []

    @pytest.mark.parametrize("bad", ["", "prediction", "Output", "control-pose"])
    def test_an_unknown_stream_is_refused_at_construction(self, tmp_path, bad):
        with pytest.raises(ValueError, match="stream must be one of"):
            ControlMapEditor(tmp_path / "c.toml", stream=bad)


class TestAGateIsOnlyOfferedWhereItApplies:
    """The UI must not offer what the resolver will refuse.

    Three separate reports came from that one shape: a control from the other hand, a
    probability cutoff on a 17-state control, and a stability gate on a number. Each was
    offered, validated clean, saved — and then refused by the bus, layers from the click.
    `_gate_rules` is the single place that knows, so the checkbox that offers a gate and
    the check that refuses one cannot drift apart.
    """

    MANY_STATES = Capability(
        "vhi.control.many",
        "discrete",
        states=tuple(f"s{n}" for n in range(17)),
        rest_state="s0",
    )
    TWO_STATES = Capability(
        "vhi.control.grip", "discrete", states=("Rest", "Closed"), rest_state="Rest"
    )

    @pytest.fixture
    def client(self):
        caps = [*MANIFEST, self.MANY_STATES, self.TWO_STATES]

        class Client:
            def capabilities(self):
                return caps

        return Client()

    def _entry(self, tmp_path, client, address, **gates):
        path = tmp_path / "controls.toml"
        path.write_text(f'[dofs]\nmine = "{address}"\n')
        editor = ControlMapEditor(path, client=client, stream="output")
        editor.load()
        editor._connect()
        editor._draft[0].update(gates)
        return editor

    def test_a_number_takes_a_cutoff_but_not_a_hold(self, tmp_path, client):
        editor = self._entry(tmp_path, client, "vhi.prediction.index")
        no_threshold, no_debounce = editor._gate_rules(editor._draft[0])
        assert no_threshold == ""
        assert "no state transition to hold" in no_debounce

    def test_a_seventeen_state_control_takes_a_hold_but_not_a_cutoff(self, tmp_path, client):
        editor = self._entry(tmp_path, client, "vhi.control.many")
        no_threshold, no_debounce = editor._gate_rules(editor._draft[0])
        assert "17 states" in no_threshold
        assert "state name" in no_threshold, "it must say what to send instead"
        assert no_debounce == ""

    def test_a_two_state_control_takes_both(self, tmp_path, client):
        """The case a cutoff was designed for: rest, or the one other state."""
        editor = self._entry(tmp_path, client, "vhi.control.grip")
        assert editor._gate_rules(editor._draft[0]) == ("", "")

    def test_a_cutoff_on_a_many_state_control_blocks_the_save(self, tmp_path, client):
        editor = self._entry(tmp_path, client, "vhi.control.many", threshold_fraction=0.5)
        assert any("17 states" in p for p in editor.problems())
        assert editor.save() is False

    def test_a_hold_on_a_number_blocks_the_save(self, tmp_path, client):
        """Silently doing nothing is the worse outcome: the bus gates discrete DOFs only."""
        editor = self._entry(tmp_path, client, "vhi.prediction.index", debounce_s=0.2)
        assert any("hold" in p for p in editor.problems())
        assert editor.save() is False

    def test_an_unset_gate_is_never_a_problem(self, tmp_path, client):
        """Only a gate actually *set* where it cannot apply is wrong."""
        for address in ("vhi.prediction.index", "vhi.control.many"):
            editor = self._entry(tmp_path, client, address)
            assert editor.problems() == [], address

    def test_nothing_is_refused_on_a_guess(self, tmp_path, client):
        """Offline, or an address the target does not export, is unknowable — allow it."""
        path = tmp_path / "controls.toml"
        path.write_text('[dofs]\nmine = { target = "some.other.thing", debounce_s = 0.2 }\n')
        editor = ControlMapEditor(path, stream="output")   # no client at all
        editor.load()
        assert editor._gate_rules(editor._draft[0]) == ("", "")


class TestAHeldStateOccupiesNoChannel:
    """A discrete control shares no pose channel, whatever number it reports.

    A target that leaves `channel` unset for a held state reports proto3's default of **0**,
    which is indistinguishable from pose channel 0 — so two held states looked like one
    control, and a held state looked like the thumb. Keyed on `kind` now, so the client is
    right regardless of what the target omits. (VHI was also fixed to declare -1.)
    """

    UNSET = Capability(
        "vhi.control.a", "discrete", states=("Rest", "On"), rest_state="Rest", channel=0
    )
    ALSO_UNSET = Capability(
        "vhi.control.b", "discrete", states=("Rest", "On"), rest_state="Rest", channel=0
    )

    @pytest.fixture
    def client(self):
        caps = [*MANIFEST, self.UNSET, self.ALSO_UNSET]

        class Client:
            def capabilities(self):
                return caps

        return Client()

    def _editor_with(self, tmp_path, client, body):
        path = tmp_path / "controls.toml"
        path.write_text(body)
        editor = ControlMapEditor(path, client=client, stream="output")
        editor.load()
        editor._connect()
        return editor

    def test_two_held_states_reporting_channel_zero_do_not_collide(self, tmp_path, client):
        editor = self._editor_with(
            tmp_path,
            client,
            '[dofs]\na = "vhi.control.a"\nb = "vhi.control.b"\n',
        )
        assert not any("same control" in p for p in editor.problems()), editor.problems()

    def test_a_held_state_does_not_collide_with_pose_channel_zero(self, tmp_path, client):
        editor = self._editor_with(
            tmp_path,
            client,
            '[dofs]\nheld = "vhi.control.a"\nthumb = "vhi.prediction.thumb"\n',
        )
        assert editor.problems() == [], editor.problems()

    def test_a_held_state_has_no_peers(self, tmp_path, client):
        editor = self._editor_with(tmp_path, client, '[dofs]\na = "vhi.control.a"\n')
        assert editor._peers(self.UNSET) == []

    def test_two_numbers_on_one_channel_still_collide(self, tmp_path, client):
        """The rule that must survive the fix."""
        editor = self._editor_with(
            tmp_path,
            client,
            '[dofs]\na = "vhi.prediction.thumb"\nb = "vhi.prediction.thumb.flexion"\n',
        )
        assert any("same control" in p for p in editor.problems())


class TestAMapMayServeBothHands:
    """An app with a target per hand shares one map, so the editor can serve that too."""

    def test_both_offers_every_stream(self, tmp_path):
        path = tmp_path / "controls.toml"
        path.write_text(GOOD)
        editor = ControlMapEditor(path, client=_Client(), stream="both")
        editor.load()
        editor._connect()
        addresses = [cap.address for cap in editor._offered()]
        assert "vhi.prediction.thumb" in addresses
        assert "vhi.control.pose.thumb" in addresses

    def test_both_does_not_call_a_mixed_map_a_problem(self, tmp_path):
        path = tmp_path / "controls.toml"
        path.write_text(
            '[dofs]\nmodel = "vhi.prediction.thumb"\noperator = "vhi.control.pose.thumb"\n'
        )
        editor = ControlMapEditor(path, client=_Client(), stream="both")
        editor.load()
        editor._connect()
        assert editor.problems() == []
        assert editor.save() is True

    def test_a_single_stream_editor_still_refuses_the_mix(self, tmp_path):
        """The default stays strict: most apps have one target."""
        path = tmp_path / "controls.toml"
        path.write_text(
            '[dofs]\nmodel = "vhi.prediction.thumb"\noperator = "vhi.control.pose.thumb"\n'
        )
        editor = ControlMapEditor(path, client=_Client(), stream="output")
        editor.load()
        editor._connect()
        assert any("one hand" in p for p in editor.problems())


class TestOneWayToDriveTheControlHand:
    """The renderer's own exclusion, and it taught it to us by refusing a declaration.

    Streaming a pose to the operator's hand and commanding it a movement would both drive
    that hand, so VHI accepts one or the other:

        a discrete DOF and a control-pose stream would both drive the control hand —
        declare one or the other

    A `stream="both"` map is where this becomes reachable, so it is caught before the
    handshake rather than by it.
    """

    def _editor(self, tmp_path, body, stream="both"):
        path = tmp_path / "controls.toml"
        path.write_text(body)
        editor = ControlMapEditor(path, client=_Client(), stream=stream)
        editor.load()
        editor._connect()
        return editor

    def test_a_pose_and_a_movement_on_the_same_hand_are_refused(self, tmp_path):
        editor = self._editor(
            tmp_path,
            '[dofs]\nposed = "vhi.control.pose.thumb"\nheld = "vhi.control.gesture"\n',
        )
        problems = editor.problems()
        assert any("one or the other" in p for p in problems), problems
        assert editor.save() is False

    def test_the_reason_names_both_sides(self, tmp_path):
        editor = self._editor(
            tmp_path,
            '[dofs]\nposed = "vhi.control.pose.thumb"\nheld = "vhi.control.gesture"\n',
        )
        reason = next(p for p in editor.problems() if "one or the other" in p)
        assert "posed" in reason and "held" in reason

    def test_a_pose_on_the_model_hand_beside_a_movement_is_fine(self, tmp_path):
        """Different hands: the prediction stream and a control-hand movement coexist —
        which is exactly what emg_classification_grpc does."""
        editor = self._editor(
            tmp_path,
            '[dofs]\nmodel = "vhi.prediction.thumb"\nheld = "vhi.control.gesture"\n',
        )
        assert editor.problems() == [], editor.problems()

    def test_two_pose_streams_together_are_fine(self, tmp_path):
        """The case that works, and the one this whole change was about."""
        editor = self._editor(
            tmp_path,
            '[dofs]\nmodel = "vhi.prediction.thumb"\noperator = "vhi.control.pose.thumb"\n',
        )
        assert editor.problems() == [], editor.problems()


class TestOneRowPerControlNotPerName:
    """Eleven names for six controls made the list need a channel column to explain itself.

    A renderer publishes the short and the explicit-axis form of a control as two addresses
    on one channel, and picking either does the same thing. Collapsing them is what let the
    channel number — a wire detail — leave the UI.
    """

    @pytest.fixture
    def editor(self, tmp_path):
        return _editor(tmp_path, GOOD)

    def test_the_aliased_forms_collapse_to_one_row(self, editor):
        addresses = [cap.address for cap in editor._offered()]
        assert "vhi.prediction.thumb" in addresses
        assert "vhi.prediction.thumb.flexion" not in addresses

    def test_the_shortest_name_is_the_one_offered(self, editor):
        """`thumb` reads better than `thumb.flexion`, and means the same."""
        thumb = [a for a in (c.address for c in editor._offered()) if "thumb" in a]
        assert "vhi.prediction.thumb" in thumb

    def test_a_control_with_its_own_channel_is_not_collapsed_away(self, editor):
        """The thumb's second axis is a different control, not another name for one."""
        assert "vhi.prediction.thumb.abduction" in [c.address for c in editor._offered()]

    def test_the_value_a_file_already_uses_is_still_offered(self, editor):
        """Otherwise opening the picker would hide the current value, or silently swap it
        for the shortest name — a diff nobody asked for."""
        addresses = [
            cap.address
            for cap in editor._offered(current="vhi.prediction.thumb.flexion")
        ]
        assert "vhi.prediction.thumb.flexion" in addresses
        assert addresses.count("vhi.prediction.thumb") == 0, "and not both"

    def test_the_alternatives_are_still_reachable_on_hover(self, editor):
        thumb = next(
            c for c in editor._offered() if c.address == "vhi.prediction.thumb"
        )
        assert editor._peers(thumb) == ["vhi.prediction.thumb.flexion"]

    def test_held_states_survive_the_collapse(self, editor):
        assert "vhi.control.gesture" in [c.address for c in editor._offered()]


class TestTheFileIsWatched:
    """Hot reload: an external write reaches the panel without a button.

    The risk here is not detection, it is the *guard*. This editor's draft is the only copy
    of whatever has been typed into it, so a reload that fires at the wrong moment destroys
    work with no undo. Every test below is really about which of the two versions survives.
    """

    #: A second map, distinguishable from GOOD by its alias.
    OTHER = """
[dofs]
elsewhere = "vhi.prediction.ring"
"""

    def _touch(self, editor, body: str) -> None:
        """Write the file as another program would, past the mtime granularity."""
        import os
        import time

        editor.path.write_text(body)
        # Bump the stamp explicitly rather than sleeping: `st_mtime_ns` is fine-grained but
        # some filesystems round, and a test that depends on the clock advancing is a test
        # that fails on a fast machine.
        stamp = time.time() + 10
        os.utime(editor.path, (stamp, stamp))

    def test_an_external_change_is_picked_up_when_nothing_is_unsaved(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        self._touch(editor, self.OTHER)
        assert editor.poll_disk() is True
        assert [e["alias"] for e in editor._draft] == ["elsewhere"]

    def test_nothing_happens_when_the_file_has_not_changed(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        assert editor.poll_disk() is False
        assert editor.poll_disk() is False

    def test_our_own_save_is_not_mistaken_for_someone_elses_change(self, tmp_path):
        """Without re-stamping on save, every save would report a change on the next frame."""
        editor = _editor(tmp_path, GOOD)
        editor._draft[0]["alias"] = "renamed"
        assert editor.save() is True
        assert editor.poll_disk() is False

    def test_an_external_change_never_overwrites_unsaved_edits(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._draft[0]["alias"] = "mine"
        before = [dict(entry) for entry in editor._draft]
        self._touch(editor, self.OTHER)
        assert editor.poll_disk() is False
        assert editor._conflict is True
        assert editor._draft == before

    def test_reloading_from_disk_resolves_the_conflict(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._draft[0]["alias"] = "mine"
        self._touch(editor, self.OTHER)
        editor.poll_disk()
        assert editor.take_disk_version() is True
        assert [e["alias"] for e in editor._draft] == ["elsewhere"]
        assert editor._conflict is False

    def test_keeping_my_edits_resolves_it_and_does_not_ask_again(self, tmp_path):
        """Dismissing has to re-stamp, or the banner returns on the very next frame."""
        editor = _editor(tmp_path, GOOD)
        editor._draft[0]["alias"] = "mine"
        self._touch(editor, self.OTHER)
        editor.poll_disk()
        editor.keep_mine()
        assert editor._conflict is False
        assert editor.poll_disk() is False
        assert editor._conflict is False
        assert [e["alias"] for e in editor._draft] == ["mine"]

    def test_unapplied_text_in_the_raw_view_counts_as_unsaved(self, tmp_path):
        """The text view is not the draft until Apply, so a reload would eat it.

        `_matches_disk` alone says this editor is clean — the fields do match the file. What
        is unsaved is sitting in the text buffer, which is exactly the case a narrower dirty
        check misses.
        """
        editor = _editor(tmp_path, GOOD)
        editor._raw_open = True
        editor._raw = '[dofs]\nhalf_typed = "vhi.prediction.li'
        assert editor._matches_disk() is True
        assert editor._dirty() is True
        self._touch(editor, self.OTHER)
        assert editor.poll_disk() is False
        assert editor._conflict is True
        assert editor._raw.endswith("vhi.prediction.li")

    def test_a_file_that_stops_parsing_asks_rather_than_reloading(self, tmp_path):
        """Half-written TOML is what you catch an editor mid-save with."""
        editor = _editor(tmp_path, GOOD)
        self._touch(editor, "[dofs]\nbroken = ")
        assert editor.poll_disk() is False
        assert editor._conflict is True

    def test_a_missing_file_does_not_raise(self, tmp_path):
        """`poll_disk` runs inside a render frame; it may not throw."""
        editor = _editor(tmp_path, GOOD)
        editor.path.unlink()
        assert editor.poll_disk() is False
        assert editor._conflict is False


class TestSaveAs:
    def test_it_writes_the_new_path_and_follows_it(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        elsewhere = tmp_path / "nested" / "experiment.toml"
        assert editor.save_as(elsewhere) is True
        assert editor.path == elsewhere
        assert load_control_map(tomllib.loads(elsewhere.read_text())).bindings

    def test_the_original_is_left_alone(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        original = editor.path
        was = original.read_text()
        editor._draft[0]["alias"] = "changed"
        editor.save_as(tmp_path / "copy.toml")
        assert original.read_text() == was

    def test_a_later_save_goes_to_the_new_path(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        original = editor.path
        was = original.read_text()
        editor.save_as(tmp_path / "copy.toml")
        editor._draft[0]["alias"] = "after_save_as"
        assert editor.save() is True
        assert "after_save_as" in (tmp_path / "copy.toml").read_text()
        assert original.read_text() == was

    def test_the_watch_follows_the_new_path(self, tmp_path):
        """Otherwise the editor would keep reacting to the file it no longer edits."""
        editor = _editor(tmp_path, GOOD)
        editor.save_as(tmp_path / "copy.toml")
        assert editor.poll_disk() is False
        editor.path.write_text('[dofs]\nfrom_the_new_file = "vhi.prediction.ring"\n')
        import os
        import time

        stamp = time.time() + 10
        os.utime(editor.path, (stamp, stamp))
        assert editor.poll_disk() is True
        assert [e["alias"] for e in editor._draft] == ["from_the_new_file"]

    def test_an_invalid_draft_leaves_the_path_where_it_was(self, tmp_path):
        """Save As shares Save's rule: it must not write a file that will not load."""
        editor = _editor(tmp_path, GOOD)
        original = editor.path
        editor._draft[0]["alias"] = ""          # invalid: an alias is required
        assert editor.save_as(tmp_path / "never.toml") is False
        assert editor.path == original
        assert not (tmp_path / "never.toml").exists()


class TestTheAddressTree:
    """The picker's shape, derived from the addresses rather than declared anywhere.

    A flat list was fine for six controls. A keyboard exports two hundred, so the picker
    became a tree — and the only thing it knows is that addresses are dotted, which the
    control standard already guarantees. No target-specific code, which is why one
    implementation organises a renderer and a keyboard identically.
    """

    def _tree(self, *addresses):
        from myogestic.controls import Capability
        from myogestic.widgets.vhi.control_map_editor import address_tree

        return address_tree([Capability(a, "continuous") for a in addresses])

    def test_each_dot_is_a_level(self):
        tree = self._tree("vhi.prediction.index")
        assert sorted(tree) == ["vhi"]
        assert sorted(tree["vhi"]) == ["prediction"]
        assert sorted(tree["vhi"]["prediction"]) == ["index"]

    def test_siblings_share_a_branch(self):
        tree = self._tree("vhi.prediction.index", "vhi.prediction.middle")
        assert sorted(tree["vhi"]["prediction"]) == ["index", "middle"]

    def test_two_targets_are_two_roots(self):
        """The first segment namespaces the target, so the grouping is free."""
        tree = self._tree("vhi.prediction.index", "keyboard.hold.letter.a")
        assert sorted(tree) == ["keyboard", "vhi"]

    def test_a_node_can_be_both_a_control_and_a_parent(self):
        """`vhi.prediction.thumb` was exactly this before the rename, and another target
        may do it again — so a branch must be able to carry its own capability."""
        from myogestic.widgets.vhi.control_map_editor import _LEAF

        tree = self._tree("vhi.prediction.thumb", "vhi.prediction.thumb.abduction")
        thumb = tree["vhi"]["prediction"]["thumb"]
        assert thumb[_LEAF].address == "vhi.prediction.thumb"
        assert "abduction" in thumb

    def test_a_leaf_holds_the_capability_itself(self):
        from myogestic.widgets.vhi.control_map_editor import _LEAF

        tree = self._tree("vhi.prediction.index")
        assert tree["vhi"]["prediction"]["index"][_LEAF].address == "vhi.prediction.index"

    def test_it_scales_to_a_whole_keyboard(self):
        """214 addresses, four segments each — the case the tree exists for."""
        from myogestic.keyboard import keyboard_capabilities
        from myogestic.widgets.vhi.control_map_editor import address_tree

        tree = address_tree(keyboard_capabilities())
        assert sorted(tree) == ["keyboard"]
        assert sorted(tree["keyboard"]) == ["hold", "tap"]
        assert "letter" in tree["keyboard"]["hold"]
        assert "a" in tree["keyboard"]["hold"]["letter"]


class TestSeveralManifests:
    def test_clients_are_merged_into_one_offering(self):
        """One file may name controls on several targets; the picker must show them all."""
        from myogestic.keyboard import KeyboardTarget

        class Fake:
            def capabilities(self):
                return MANIFEST

        editor = ControlMapEditor(
            pathlib.Path("unused.toml"), clients=[Fake(), KeyboardTarget()]
        )
        editor._connect()
        roots = {c.address.split(".")[0] for c in editor.capabilities}
        assert roots == {"vhi", "keyboard"}

    def test_a_silent_target_does_not_hide_the_others(self):
        """Launching one target before the other is normal; the picker still works."""

        class Silent:
            def capabilities(self):
                return None

        class Fake:
            def capabilities(self):
                return MANIFEST

        editor = ControlMapEditor(pathlib.Path("unused.toml"), clients=[Silent(), Fake()])
        editor._connect()
        assert editor.capabilities
        # And says nothing about it. How many targets answered is plumbing; what matters is
        # whether *this map* names an address nothing can vouch for, which `unanswered` says
        # and only when it does.
        assert editor._message == ""

    def test_the_single_client_form_still_works(self):
        class Fake:
            def capabilities(self):
                return MANIFEST

        editor = ControlMapEditor(pathlib.Path("unused.toml"), client=Fake())
        editor._connect()
        assert editor.capabilities


class TestTypingAnAddressTheTargetHasNotAdvertised:
    """The picker must not lose free-text entry when a target answers.

    Offline the control is a plain text field, so anything can be typed. Connected it
    becomes a tree of what was advertised — and for a while that was *all* it was, so an
    address you knew but nothing had published became unreachable precisely when the app
    was working. The search box doubles as entry; this is the rule for when it offers.
    """

    def test_a_well_formed_unknown_address_is_offered(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._filter = "keyboard.hold.letter.w"
        assert editor._typed_offer() == "keyboard.hold.letter.w"

    def test_surrounding_space_is_ignored(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._filter = "  keyboard.tap.edit.space  "
        assert editor._typed_offer() == "keyboard.tap.edit.space"

    def test_an_advertised_address_is_not_offered(self, tmp_path):
        """It is in the tree, where its declared kind and range are visible too."""
        editor = _editor(tmp_path, GOOD)
        editor._filter = "vhi.prediction.index"
        assert editor._typed_offer() == ""

    @pytest.mark.parametrize(
        "text",
        ["", "my_index", "Vhi.Prediction.Index", "vhi prediction index", "vhi.", ".index"],
    )
    def test_anything_the_loader_would_refuse_is_not_offered(self, tmp_path, text):
        """Same rule as the loader's, not a second copy of it — see `is_address`."""
        editor = _editor(tmp_path, GOOD)
        editor._filter = text
        assert editor._typed_offer() == ""

    def test_a_partial_search_is_not_mistaken_for_an_address(self, tmp_path):
        """`wrist` is how you search; it is not something to offer as a control."""
        editor = _editor(tmp_path, GOOD)
        editor._filter = "wrist"
        assert editor._typed_offer() == ""


class TestIsAddressIsTheOneRule:
    def test_it_is_public(self):
        """The editor validates typed input with it, so it is contract, not an internal."""
        from myogestic.controls import is_address

        assert is_address("vhi.prediction.index")
        assert not is_address("my_index")

    def test_the_editor_and_the_loader_agree(self):
        """A second copy of the address rule is how the picker and the loader drift."""
        from myogestic.controls import is_address, load_control_map

        for text in ("vhi.prediction.index", "keyboard.tap.edit.space"):
            assert is_address(text)
            assert load_control_map({"dofs": {"a": text}}).bindings["a"].targets


class TestARowSaysWhatTheControlAccepts:
    """A count is never the useful fact. "2 states" tells a reader nothing about a key."""

    @staticmethod
    def _editor(tmp_path):
        return ControlMapEditor(tmp_path / "m.toml")

    def test_two_states_are_named(self, tmp_path):
        key = Capability(
            "keyboard.hold.letter.w", "discrete", states=("up", "down"),
            rest_state="up", channel=-1,
        )
        assert self._editor(tmp_path)._detail(key).strip() == "up / down"

    def test_many_states_are_counted(self, tmp_path):
        """Seventeen names would push the row off the edge, so the count is right there."""
        gesture = Capability(
            "vhi.control.gesture", "discrete",
            states=tuple(f"s{i}" for i in range(17)), rest_state="s0", channel=-1,
        )
        assert self._editor(tmp_path)._detail(gesture).strip() == "17 states"

    def test_the_tooltip_names_them_too(self, tmp_path):
        key = Capability(
            "keyboard.tap.edit.space", "discrete", states=("up", "down"),
            rest_state="up", channel=-1,
        )
        assert "up / down" in self._editor(tmp_path)._summary(key)

    def test_a_continuous_row_is_unchanged(self, tmp_path):
        """A signed control adds nothing; only an unusual range is worth a note."""
        editor = self._editor(tmp_path)
        signed = Capability("vhi.prediction.index", "continuous", -1.0, 1.0, 0.0, channel=2)
        one_way = Capability("vhi.grip.force", "continuous", 0.0, 1.0, 0.0, channel=4)
        assert editor._detail(signed) == ""
        assert "+0.0..+1.0" in editor._detail(one_way)


class TestSavingDoesNotDependOnWhatIsRunning:
    """A TOML naming a Virtual Hand control is a valid TOML with no renderer running.

    This regressed the moment a second target existed. `problems()` skipped its export check
    when the manifest was empty, which with one target meant "nothing has answered". With a
    keyboard target answering 214 addresses and VHI silent, the manifest was *not* empty, so
    every `vhi.*` address was reported as unexportable and Save went dead — for a file that
    was correct.
    """

    MIXED = """
[dofs]
close = [
  { target = "vhi.prediction.thumb.flexion", weight = 0.6 },
  { target = "vhi.prediction.index" },
]
walk = "keyboard.hold.letter.w"
"""

    @staticmethod
    def _keyboard_only(tmp_path, body):
        from myogestic.keyboard import KeyboardTarget

        path = tmp_path / "m.toml"
        path.write_text(body)
        editor = ControlMapEditor(path, clients=[KeyboardTarget()], stream="output")
        editor.load()
        editor._connect()
        return editor

    def test_a_silent_targets_address_does_not_block_saving(self, tmp_path):
        """The screenshot, as a test."""
        editor = self._keyboard_only(tmp_path, self.MIXED)
        assert editor._answered == frozenset({"keyboard"})
        assert editor.problems() == []
        assert editor.save() is True

    def test_it_is_reported_as_unverifiable_not_as_wrong(self, tmp_path):
        """One line per silent *namespace* — two `vhi.*` addresses are one fact, not two.

        It used to be one line per address, so the panel said "nothing from 'vhi' has
        answered" once for every address in the file: five identical sentences for a single
        piece of news. The addresses are still available, keyed by the namespace that owes
        them, for the tooltip to show on demand.
        """
        editor = self._keyboard_only(tmp_path, self.MIXED)
        assert editor.unanswered() == {
            "vhi": ["vhi.prediction.thumb.flexion", "vhi.prediction.index"]
        }
        assert editor.warnings() == [
            "vhi has not answered — 2 addresses cannot be checked. Saves either way."
        ]

    def test_one_address_is_not_pluralised(self, tmp_path):
        """The count is in the sentence, so it has to read for n = 1 too."""
        editor = self._keyboard_only(tmp_path, '[dofs]\na = "vhi.prediction.index"\n')
        assert editor.warnings() == [
            "vhi has not answered — 1 address cannot be checked. Saves either way."
        ]

    def test_the_answered_targets_controls_are_still_checked(self, tmp_path):
        """The keyboard *did* answer, so a bad keyboard address is still a problem."""
        editor = self._keyboard_only(
            tmp_path, '[dofs]\nwalk = "keyboard.hold.letter.nonesuch"\n'
        )
        assert any("does not export" in p for p in editor.problems())
        assert editor.warnings() == []

    def test_a_malformed_file_is_still_refused_with_nothing_connected(self, tmp_path):
        """The split must not have made Save permissive — these need no manifest at all."""
        path = tmp_path / "m.toml"
        path.write_text('[dofs]\na = "vhi.prediction.index"\n')
        editor = ControlMapEditor(path)
        editor.load()
        editor._draft.append(dict(editor._draft[0]))          # duplicate name
        editor._draft[1]["targets"] = [["vhi.prediction.middle", 0.0]]   # zero weight
        found = " ".join(editor.problems())
        assert "used twice" in found
        assert "outside [-1, 1] or zero" in found
        assert editor.warnings(), "and the unverifiable address is still reported"

    def test_an_unnamed_control_still_blocks(self, tmp_path):
        editor = self._keyboard_only(tmp_path, self.MIXED)
        editor._draft[0]["alias"] = ""
        assert any("no name" in p for p in editor.problems())

    def test_the_preview_says_why_rather_than_reporting_a_refusal(self, tmp_path):
        """`resolve` would refuse a silent target's address, which reads as "your file is
        wrong". The summary has to distinguish that from an actual refusal."""
        editor = self._keyboard_only(tmp_path, self.MIXED)
        summary = editor.resolved_summary()
        assert "has answered" in summary
        assert "still saveable" in summary

    def test_nothing_connected_at_all_is_unchanged(self, tmp_path):
        """Offline every address is unverifiable, and that was already the old behaviour.

        Three addresses across two namespaces, so two lines — sorted, because the panel draws
        them in order and an order that moves between frames is a flicker.
        """
        path = tmp_path / "m.toml"
        path.write_text(self.MIXED)
        editor = ControlMapEditor(path)
        editor.load()
        assert editor.problems() == []
        assert sorted(editor.unanswered()) == ["keyboard", "vhi"]
        assert editor.warnings() == [
            "keyboard has not answered — 1 address cannot be checked. Saves either way.",
            "vhi has not answered — 2 addresses cannot be checked. Saves either way.",
        ]
        assert editor.save() is True


class TestAnUntitledMapIsARealState:
    """You start on a blank map, so "no file yet" has to be ordinary rather than an error."""

    def test_it_has_no_path_and_a_readable_label(self):
        editor = ControlMapEditor()
        editor.load()
        assert editor.path is None
        assert editor.label == "Untitled"

    def test_saving_refuses_rather_than_inventing_a_location(self):
        """A file the user cannot find again is worse than a save that did not happen."""
        editor = ControlMapEditor()
        editor.load()
        editor.add_control()
        editor._draft[0]["targets"] = [["vhi.prediction.index", 1.0]]
        assert editor.save() is False
        assert "Save as" in editor._message

    def test_save_as_gives_it_a_name_and_writes(self, tmp_path):
        editor = ControlMapEditor()
        editor.load()
        editor.add_control()
        editor._draft[0]["targets"] = [["vhi.prediction.index", 1.0]]
        target = tmp_path / "nested" / "mine.toml"
        assert editor.save_as(target) is True
        assert editor.path == target
        assert editor.label == "mine.toml"
        assert load_control_map(tomllib.loads(target.read_text())).bindings

    def test_the_watch_does_not_fire_on_a_map_with_no_file(self):
        """`poll_disk` runs every frame; an untitled map must not look like a change."""
        editor = ControlMapEditor()
        editor.load()
        assert editor.poll_disk() is False
        assert editor.poll_disk() is False

    def test_it_reports_no_problems_when_empty(self):
        """A blank map is not a broken one — it is where you start."""
        editor = ControlMapEditor()
        editor.load()
        assert editor.problems() == []
        assert editor.warnings() == []


class TestTheHeaderDotReportsTheMapNotTheTarget:
    """`CIRCLE` means "the live state of whatever *this panel* controls".

    This panel controls a file. Wiring its one status channel to the renderer's
    reachability would spend it on another panel's subject — and would put a green dot above
    a red "changed on disk" banner. The target gets its own line beside Connect instead.

    Grey unless something needs doing: a dot that is green whenever nothing is wrong is a dot
    nobody looks at.
    """

    @staticmethod
    def _editor(tmp_path, body='[dofs]\na = "vhi.prediction.index"\n'):
        path = tmp_path / "m.toml"
        path.write_text(body)
        editor = ControlMapEditor(path)
        editor.load()
        return editor

    def test_a_saved_valid_map_is_idle(self, tmp_path):
        from myogestic.widgets.common import IDLE

        colour, detail = self._editor(tmp_path)._status()
        assert colour is IDLE
        assert "matches the file" in detail

    def test_being_disconnected_is_not_the_maps_problem(self, tmp_path):
        """The judges' point: no client at all, and the map is still perfectly fine."""
        from myogestic.widgets.common import IDLE

        editor = self._editor(tmp_path)
        assert editor._answered == frozenset()
        assert editor._status()[0] is IDLE

    def test_an_unsavable_map_warns(self, tmp_path):
        from myogestic.widgets.common import WARNING

        editor = self._editor(tmp_path)
        editor.add_control()                      # a control pointing at nothing yet
        colour, detail = editor._status()
        assert colour is WARNING
        assert "Cannot save yet" in detail

    def test_unsaved_edits_warn(self, tmp_path):
        from myogestic.widgets.common import WARNING

        editor = self._editor(tmp_path)
        editor._draft[0]["alias"] = "renamed"
        colour, detail = editor._status()
        assert colour is WARNING
        assert "Unsaved" in detail

    def test_a_conflict_outranks_an_unsavable_draft(self, tmp_path):
        """Loudest first. A file that moved under unsaved edits is the worse news."""
        from myogestic.widgets.common import DANGER

        editor = self._editor(tmp_path)
        editor.add_control()
        editor._conflict = True
        assert editor._status()[0] is DANGER

    def test_an_unloadable_file_is_the_loudest(self, tmp_path):
        from myogestic.widgets.common import DANGER

        editor = self._editor(tmp_path, "[dofs]\nbroken = ")
        assert editor._error
        assert editor._status()[0] is DANGER

    def test_the_path_is_never_lost_only_moved(self, tmp_path):
        """It used to have a whole row. It has to still be somewhere a reader can get it."""
        editor = self._editor(tmp_path)
        assert str(editor.path) in editor._status()[1]

    def test_an_untitled_map_says_so(self):
        editor = ControlMapEditor()
        editor.load()
        assert "Untitled" in editor._status()[1]


class TestConnectingHappensOnItsOwn:
    """It used to need a click, and the reason was real but too broad.

    Asking on the render thread was out, so the ask moved to a worker and the answer is
    adopted on the next frame — the shape `poll_disk` and the Save-as dialog already use.
    `KeyboardTarget.capabilities()` reads a local list and never needed a click at all.

    The *stated* reason was that `capabilities()` blocks for the client's two-second RPC
    timeout when nothing is listening, and that turns out to be false for the case it was
    written about: a renderer that is not running refuses the connection, and the call is
    back in about 7 ms. The two seconds need something holding the port without answering.
    The worker is still right — 7 ms of a 16 ms frame is not free — but the number is why
    this used to stop asking once everyone had answered, and that part was a bug.
    """

    class _Slow:
        """A client that answers, slowly, and counts how often it was asked."""

        def __init__(self, delay: float = 0.0, address: str = "vhi.prediction.index"):
            self.asked = 0
            self.delay = delay
            self.address = address

        def capabilities(self):
            import time as _t

            self.asked += 1
            _t.sleep(self.delay)
            return [
                Capability(
                    self.address, "continuous", -1.0, 1.0, 0.0,
                    channel=2, stream_name="MyoGestic_Output",
                )
            ]

    class _Silent:
        """A target that is not running yet: asked, and says nothing."""

        def __init__(self):
            self.asked = 0

        def capabilities(self):
            self.asked += 1
            return None

    class _Togglable:
        """A target that can be switched off, the way closing a renderer switches VHI off."""

        def __init__(self):
            self.asked = 0
            self.up = True

        def capabilities(self):
            self.asked += 1
            if not self.up:
                return None
            return [
                Capability(
                    "vhi.prediction.index", "continuous", -1.0, 1.0, 0.0,
                    channel=2, stream_name="MyoGestic_Output",
                )
            ]

    @staticmethod
    def _settle(editor, tries: int = 200):
        """Let the worker finish, then adopt on the (test's) render thread."""
        import time as _t

        for _ in range(tries):
            if not editor._fetching:
                break
            _t.sleep(0.01)
        editor.poll_connect()

    def _editor(self, tmp_path, *clients):
        path = tmp_path / "m.toml"
        path.write_text('[dofs]\na = "vhi.prediction.index"\n')
        editor = ControlMapEditor(path, clients=list(clients))
        editor.load()
        return editor

    def test_the_picker_fills_with_no_click(self, tmp_path):
        client = self._Slow()
        editor = self._editor(tmp_path, client)
        assert editor.capabilities == ()
        editor.poll_connect()          # starts the worker
        self._settle(editor)           # adopts its answer
        assert editor._answered == frozenset({"vhi"})
        assert len(editor.capabilities) == 1

    def test_it_does_not_ask_every_frame(self, tmp_path):
        """`_RETRY_EVERY_S` is the whole of the rate limit — five frames is not five asks.

        This was called "it stops asking once everything answered", which is not what it
        checks: five polls in a row all land inside the retry gap, so it passes either way.
        The real stop was an early return in `poll_connect`, and it is gone — see
        `test_it_keeps_asking_so_a_target_can_go_away`.
        """
        client = self._Slow()
        editor = self._editor(tmp_path, client)
        editor.poll_connect()
        self._settle(editor)
        for _ in range(5):
            editor.poll_connect()
        assert client.asked == 1

    def test_one_target_answering_does_not_stop_the_asking(self, tmp_path):
        """The bug: "VHI is running and I still cannot pick it".

        Every test here used a single client, where "something answered" and "everything
        answered" are the same sentence. The studio has two — a `KeyboardTarget`, which answers
        instantly off a local list, and VHI, which answers only once it is up. The keyboard
        filled `_answered` on the first frame, the retry read that as done, and VHI was never
        asked again however long it ran.
        """
        vhi = self._Silent()                                  # not up yet
        keys = self._Slow(address="keyboard.hold.letter.w")    # answers off a local list
        editor = self._editor(tmp_path, vhi, keys)
        editor.poll_connect()
        self._settle(editor)
        assert editor._answered == frozenset({"keyboard"}), "the fast one answered"
        assert not editor._all_answered, "one client is still silent"

        # Twenty frames inside the gap ask nobody; past it, the silent one is asked again.
        for _ in range(20):
            editor.poll_connect()
        assert vhi.asked == 1
        editor._last_attempt -= editor._RETRY_EVERY_S + 1
        editor.poll_connect()
        self._settle(editor)
        assert vhi.asked == 2, "a target launched later is never asked again"

    def test_it_keeps_asking_so_a_target_can_go_away(self, tmp_path):
        """A manifest is not a fact that only ever arrives — a renderer can be closed.

        It used to return early once every client had answered, on the reasoning that there
        was nothing left to ask. So closing VHI mid-session left the picker offering its
        controls and `unanswered` reporting nothing to check: not an empty panel, a wrong
        one. Pick one of those dead controls and the refusal arrived from the bus instead.
        """
        vhi = self._Togglable()
        keys = self._Slow(address="keyboard.hold.letter.w")
        editor = self._editor(tmp_path, vhi, keys)
        editor.poll_connect()
        self._settle(editor)
        assert editor._all_answered
        assert len(editor.capabilities) == 2

        vhi.up = False                                   # the renderer is closed
        editor._last_attempt -= editor._RETRY_EVERY_S + 1
        editor.poll_connect()
        self._settle(editor)

        assert vhi.asked == 2, "it never asked again, so it never noticed"
        assert not editor._all_answered
        assert [c.address for c in editor.capabilities] == ["keyboard.hold.letter.w"]
        assert editor.unanswered() == {"vhi": ["vhi.prediction.index"]}

    def test_a_press_that_reaches_no_renderer_says_so(self, tmp_path):
        """The message tested `not merged` — "*nothing* answered" — which a keyboard prevents.

        With two clients one of them always answers off a local list, so a Connect press
        with the renderer closed cleared the message and looked like it had worked.
        """
        vhi = self._Silent()
        keys = self._Slow(address="keyboard.hold.letter.w")
        editor = self._editor(tmp_path, vhi, keys)
        editor._refetch = True          # what pressing Connect sets
        editor.poll_connect()
        self._settle(editor)

        assert "did not answer" in editor._message, "a press that reached nothing said nothing"

    def test_one_raising_client_does_not_cost_the_others_their_answer(self, tmp_path):
        """`_fetch` wrapped the whole loop in one `try`, so the first raiser ended the round."""

        class _Angry:
            def __init__(self):
                self.asked = 0

            def capabilities(self):
                self.asked += 1
                raise RuntimeError("this target is having a bad day")

        angry = _Angry()
        keys = self._Slow(address="keyboard.hold.letter.w")
        editor = self._editor(tmp_path, angry, keys)     # the raiser is asked FIRST
        editor.poll_connect()
        self._settle(editor)

        assert angry.asked == 1
        assert [c.address for c in editor.capabilities] == ["keyboard.hold.letter.w"]
        assert not editor._all_answered

    def test_only_one_worker_is_ever_out(self, tmp_path):
        """Otherwise a silent target spawns a thread per frame."""
        client = self._Slow(delay=0.2)
        editor = self._editor(tmp_path, client)
        editor.poll_connect()
        for _ in range(10):
            editor.poll_connect()
        assert client.asked == 1
        self._settle(editor)

    def test_a_silent_target_is_retried_but_not_hammered(self, tmp_path):
        class Silent:
            def __init__(self):
                self.asked = 0

            def capabilities(self):
                self.asked += 1
                return None

        client = Silent()
        editor = self._editor(tmp_path, client)
        editor.poll_connect()
        self._settle(editor)
        for _ in range(20):
            editor.poll_connect()          # inside the retry gap
        assert client.asked == 1
        editor._last_attempt -= editor._RETRY_EVERY_S + 1     # gap elapsed
        editor.poll_connect()
        self._settle(editor)
        assert client.asked == 2

    def test_the_button_skips_the_gap(self, tmp_path):
        """Its whole use: you just launched the thing, do not make me wait five seconds."""
        class Silent:
            def __init__(self):
                self.asked = 0

            def capabilities(self):
                self.asked += 1
                return None

        client = Silent()
        editor = self._editor(tmp_path, client)
        editor.poll_connect()
        self._settle(editor)
        editor._refetch = True
        editor.poll_connect()
        self._settle(editor)
        assert client.asked == 2

    def test_a_client_that_raises_does_not_take_the_app_down(self, tmp_path):
        """It runs on a worker, so an exception there would be lost, not caught."""
        class Angry:
            def capabilities(self):
                raise RuntimeError("no")

        editor = self._editor(tmp_path, Angry())
        editor.poll_connect()
        self._settle(editor)
        assert editor.capabilities == ()
        assert editor._answered == frozenset()

    def test_the_blocking_path_still_works(self, tmp_path):
        """`_connect` is what the button used to do, and tests still drive it directly."""
        editor = self._editor(tmp_path, self._Slow())
        editor._connect()
        assert len(editor.capabilities) == 1



class TestTheSearchSurvivesTheOtherPickers:
    """Typing in a picker's search box has to keep what you typed.

    The bug, exactly: `_picker` recorded "was a popup open last frame" in **one bool for the
    whole panel**, and every picker wrote it once per frame. A map with five target rows draws
    five pickers, so the closed ones after the open one overwrote its `True`. Next frame the
    open picker read "it was closed", took that for a fresh open, and cleared the search — every
    frame, so the box stayed empty however fast you typed.

    Driven through `_note_open` rather than a rendered popup: a headless ImGui has no mouse, so
    `begin_combo` can never report open, and the failure needs a specific *order* of calls
    within a frame. This is that order.
    """

    @staticmethod
    def _frame(editor, open_index, count=5):
        """One frame of `count` pickers, of which `open_index` has its popup open."""
        return [editor._note_open(key=100 + i, opened=i == open_index) for i in range(count)]

    def _editor(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor._filter = ""
        return editor

    def test_a_search_typed_into_the_open_picker_is_not_cleared(self, tmp_path):
        editor = self._editor(tmp_path)
        self._frame(editor, open_index=2)          # the user opens the third row's picker
        editor._filter = "ind"                     # ...and types
        for _ in range(10):                        # ten more frames go by
            self._frame(editor, open_index=2)
        assert editor._filter == "ind", "the search was cleared while the popup stayed open"

    def test_only_the_opening_frame_reports_itself_as_new(self, tmp_path):
        """`just_opened` drives the keyboard focus, so it must be true exactly once."""
        editor = self._editor(tmp_path)
        first = self._frame(editor, open_index=2)
        assert first.count(True) == 1, "the opening frame should report one new popup"
        for _ in range(5):
            assert not any(self._frame(editor, open_index=2)), "reported new again"

    def test_opening_a_different_picker_does_clear_it(self, tmp_path):
        """The behaviour the shared flag was there for: a stale search must not hide the list."""
        editor = self._editor(tmp_path)
        self._frame(editor, open_index=2)
        editor._filter = "ind"
        opened = self._frame(editor, open_index=4)   # a different row's picker
        assert opened.count(True) == 1
        assert editor._filter == "", "a different picker inherited the last one's search"

    def test_closing_and_reopening_the_same_picker_clears_it(self, tmp_path):
        editor = self._editor(tmp_path)
        self._frame(editor, open_index=0)
        editor._filter = "ind"
        self._frame(editor, open_index=None)         # all closed
        assert self._frame(editor, open_index=0).count(True) == 1, "reopening is a fresh open"
        assert editor._filter == ""


class TestASilentTargetIsSaidOutLoud:
    """The panel has to say a target is missing even when the map names none of it.

    `warnings` is per *named* address by design — it answers "what does this map contain
    that cannot be checked". On a blank map, or one that only uses the keyboard, that is
    correctly nothing, and the panel therefore said nothing at all: the picker simply had
    no branch for the renderer. Which reads as "this is the whole list of what is
    possible", not "one target has not answered, and you can type its address anyway".
    """

    class _Answers:
        def __init__(self, address="vhi.prediction.index"):
            self.address = address

        def capabilities(self):
            return [
                Capability(
                    self.address, "continuous", -1.0, 1.0, 0.0,
                    channel=2, stream_name="MyoGestic_Output",
                )
            ]

    class _Silent:
        def capabilities(self):
            return None

    @staticmethod
    def _said(imgui_frame, monkeypatch, editor) -> list[str]:
        """Every line the panel wrapped this frame. No draw-capture helper exists yet."""
        from imgui_bundle import imgui

        lines: list[str] = []
        real = imgui.text_wrapped
        monkeypatch.setattr(
            imgui, "text_wrapped", lambda s, *a, **k: (lines.append(s), real(s, *a, **k))[1]
        )
        imgui_frame(editor.ui)
        return lines

    def _editor(self, tmp_path, *clients, body='[dofs]\n'):
        path = tmp_path / "m.toml"
        path.write_text(body)
        editor = ControlMapEditor(path, clients=list(clients))
        editor.load()
        editor._connect()
        return editor

    def test_a_blank_map_still_reports_the_silent_target(self, imgui_frame, monkeypatch, tmp_path):
        editor = self._editor(
            tmp_path, self._Silent(), self._Answers("keyboard.hold.letter.w")
        )
        assert editor.unanswered() == {}, "the map names nothing, so nothing is per-address"
        assert not editor._all_answered

        said = self._said(imgui_frame, monkeypatch, editor)
        assert any("has not answered" in line for line in said), said
        assert any("search box" in line for line in said), "it must say what to do about it"

    def test_it_is_not_said_twice_when_the_map_does_name_one(
        self, imgui_frame, monkeypatch, tmp_path
    ):
        """The per-address line already covers that case, and says more."""
        editor = self._editor(
            tmp_path,
            self._Silent(),
            self._Answers("keyboard.hold.letter.w"),
            body='[dofs]\nclose = "vhi.prediction.index"\n',
        )
        assert editor.unanswered() == {"vhi": ["vhi.prediction.index"]}

        said = self._said(imgui_frame, monkeypatch, editor)
        assert sum("has not answered" in line for line in said) == 1, said
        assert not any("search box" in line for line in said)

    def test_nothing_is_said_when_every_target_answered(
        self, imgui_frame, monkeypatch, tmp_path
    ):
        editor = self._editor(tmp_path, self._Answers(), self._Answers("keyboard.tap.edit.space"))
        assert editor._all_answered

        said = self._said(imgui_frame, monkeypatch, editor)
        assert not any("has not answered" in line for line in said), said


class TestTheConnectMessageExpires:
    """A press reports a press, and the retry now makes that report go stale.

    Connecting used to be click-only, so "a target did not answer" stayed true until the
    next click by construction. With the retry running, the target comes up on its own —
    and the line sat there insisting the renderer was absent while its controls were
    already in the picker. That is the reported bug inverted, which is worse than the bug.
    """

    class _Togglable:
        def __init__(self):
            self.up = False

        def capabilities(self):
            if not self.up:
                return None
            return [
                Capability(
                    "vhi.prediction.index", "continuous", -1.0, 1.0, 0.0,
                    channel=2, stream_name="MyoGestic_Output",
                )
            ]

    class _Answers:
        def capabilities(self):
            return [Capability("keyboard.hold.letter.w", "discrete", 0.0, 1.0, 0.0,
                               states=("up", "down"), channel=-1)]

    def _editor(self, tmp_path, *clients):
        path = tmp_path / "m.toml"
        path.write_text("[dofs]\n")
        editor = ControlMapEditor(path, clients=list(clients))
        editor.load()
        return editor

    def test_the_retry_retires_what_the_press_reported(self, tmp_path):
        vhi = self._Togglable()
        editor = self._editor(tmp_path, vhi, self._Answers())

        editor._asked = True                       # the press
        editor._connect()
        assert editor._message, "a press that reached nothing must say so"

        vhi.up = True                              # the renderer starts
        editor._connect()                          # what the timer's round does

        assert editor._all_answered
        assert not editor._message, "the panel still called a running renderer absent"

    def test_a_background_round_does_not_wipe_a_save_confirmation(self, tmp_path):
        """`_message` is shared, so the retry may only retire the line it is about."""
        editor = self._editor(tmp_path, self._Answers())
        editor._message = "Saved 3 control(s) to m.toml"
        editor._connect()                          # everything answers; no press
        assert editor._message == "Saved 3 control(s) to m.toml"


def test_the_search_box_offers_typing_only_while_a_target_is_silent():
    """It doubles as address entry, which is the way out of "the list has no vhi branch".

    Silent about that once everything has answered: the tree below is then the whole of
    what is possible, and telling someone to type an address is noise.
    """
    from myogestic.widgets.vhi.control_map_editor import _search_hint

    assert "type an address" in _search_hint(False)
    assert "type an address" not in _search_hint(True)
    assert "search" in _search_hint(True), "it is still a search box"
