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
        before = editor.as_control_map().as_dict()
        assert editor.save() is True
        editor.load()
        assert editor.as_control_map().as_dict() == before

    def test_what_it_writes_is_what_load_control_map_reads(self, tmp_path):
        editor = _editor(tmp_path, GOOD)
        editor.save()
        with editor.path.open("rb") as handle:
            reparsed = load_control_map(tomllib.load(handle))
        assert reparsed.as_dict() == editor.as_control_map().as_dict()

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
    def test_a_new_control_gets_a_free_name(self, tmp_path):
        editor = _editor(tmp_path, None)
        editor.add_control()
        editor.add_control()
        editor.add_control()
        names = [e["alias"] for e in editor._draft]
        assert len(set(names)) == 3, names

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

    def test_connecting_to_nothing_says_so(self, tmp_path):
        class Silent:
            def capabilities(self):
                return None

        editor = ControlMapEditor(tmp_path / "c.toml", client=Silent())
        editor.load()
        editor._connect()
        assert editor.capabilities == ()
        assert "No target answered" in editor._message


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
        before = editor.as_control_map().as_dict()
        assert editor.apply_raw(editor.raw_text())
        assert editor.as_control_map().as_dict() == before

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

    def test_a_row_says_which_channel_it_lands_on(self, editor):
        cap = next(c for c in MANIFEST if c.address == "vhi.prediction.index")
        assert "ch2" in editor._describe(cap)

    def test_a_row_says_when_a_control_is_not_streamed(self, editor):
        off = Capability("vhi.grip.force", "continuous", 0.0, 1.0, 0.0, channel=-1)
        assert "not streamed" in editor._describe(off)

    def test_a_discrete_row_says_states_and_that_it_goes_over_grpc(self, editor):
        cap = next(c for c in MANIFEST if c.kind == "discrete")
        described = editor._describe(cap)
        assert "3 states" in described
        assert "gRPC" in described

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

    def test_a_row_carries_nothing_but_the_address_and_its_facts(self, editor):
        """Three fields, no fourth: the address, what it takes, where it lands."""
        for cap in MANIFEST:
            described = editor._describe(cap)
            assert described.count(cap.address) == 1, "the address, exactly once"
            assert ("ch" in described) or ("gRPC" in described) or (
                "not streamed" in described
            )


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
        assert described == "vhi.prediction.index   ch2"

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
