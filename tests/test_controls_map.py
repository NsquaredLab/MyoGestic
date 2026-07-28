"""Aliases are the user's; addresses and their meaning are the target's.

That split is the whole design, so these pin both halves of it: that an arbitrary
left-side name is accepted and never interpreted, and that every semantic fact —
continuous or discrete, range, states — arrives from the target rather than from
anything hard-coded here.
"""

from __future__ import annotations

import tomllib

import pytest

from myogestic.controls import Capability, load_control_map, resolve

FINGERS = ("thumb", "index", "middle", "ring", "little")

#: A stand-in for what VHI's GetControlManifest declares.
VHI = [
    *(
        Capability(f"vhi.prediction.{d}", "continuous", lo=-1.0, hi=1.0, rest=0.0)
        for d in FINGERS
    ),
    Capability("vhi.prediction.thumb.abduction", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability("vhi.grip.force", "continuous", lo=0.0, hi=1.0, rest=0.0),
    Capability(
        "vhi.control.gesture",
        "discrete",
        states=("Rest", "Fist", "Pointing"),
        rest_state="Rest",
    ),
]


# --- the left side is the user's -------------------------------------------------


@pytest.mark.parametrize(
    "alias",
    ["wrist", "drive_x", "clicker", "fist", "My Wrist", "thumb-2", "x", "Ψ", "output 7"],
)
def test_any_usable_alias_is_accepted(alias):
    """The library must not prescribe the user's own vocabulary in any way."""
    cmap = load_control_map({"dofs": {alias: "vhi.prediction.index"}})
    assert alias in cmap.bindings


@pytest.mark.parametrize("alias", ["", "   ", 7, None])
def test_an_unusable_alias_is_refused(alias):
    """Arbitrary is not the same as absent — an alias still has to be nameable."""
    with pytest.raises(ValueError, match="non-empty string|must be"):
        load_control_map({"dofs": {alias: "vhi.prediction.index"}})


def test_the_alias_is_never_interpreted():
    """An alias that looks like an address must still be treated as just a name."""
    cmap = load_control_map({"dofs": {"vhi.prediction.index": "vhi.prediction.middle"}})
    binding = cmap.bindings["vhi.prediction.index"]
    assert binding.targets[0].address == "vhi.prediction.middle", "the value routes, not the key"


def test_the_same_alias_can_point_at_a_different_target():
    """The point of owning your own names: retarget without touching your model."""
    for address in ("vhi.prediction.index", "cursor.x_velocity"):
        cmap = load_control_map({"dofs": {"drive_x": address}})
        assert cmap.bindings["drive_x"].targets[0].address == address


# --- the right side is address-shaped --------------------------------------------


@pytest.mark.parametrize("bad", ["index", "Vhi.Prediction.Index", "", "vhi..index", 7])
def test_a_value_that_is_not_an_address_is_refused(bad):
    with pytest.raises(ValueError, match="not a target address|expected an address"):
        load_control_map({"dofs": {"my_index": bad}})


def test_an_unquoted_dotted_alias_is_diagnosed():
    """TOML nests it into a table, which used to surface as a mysterious unknown key.

    The old parser had the same trap and a phantom entry there shifted every wire index
    after it, so the error has to name what actually happened.
    """
    raw = tomllib.loads('[dofs]\nmy.thumb = "vhi.prediction.thumb"\n')
    with pytest.raises(ValueError, match="nested key"):
        load_control_map(raw)


# --- meaning comes from the target ----------------------------------------------


def test_kind_is_derived_from_the_capability_not_declared():
    """The user writes the same syntax for both; the target decides what it is."""
    cmap = load_control_map(
        {"dofs": {"a": "vhi.prediction.index", "b": "vhi.control.gesture"}}
    )
    resolved = resolve(cmap, VHI)
    assert hasattr(resolved.dofs["a"], "lo"), "should be continuous"
    assert hasattr(resolved.dofs["b"], "states"), "should be discrete"


def test_discrete_states_come_from_the_target(*, alias="g"):
    resolved = resolve(load_control_map({"dofs": {alias: "vhi.control.gesture"}}), VHI)
    dof = resolved.dofs[alias]
    assert dof.states == ("Rest", "Fist", "Pointing")
    assert dof.rest == "Rest"


def test_a_one_way_target_makes_the_alias_one_way():
    """Signedness is the target's fact: a [0,1] control has no negative direction."""
    resolved = resolve(load_control_map({"dofs": {"f": "vhi.grip.force"}}), VHI)
    assert resolved.dofs["f"].lo == 0.0


def test_an_unknown_address_is_refused_with_the_alternatives():
    """The manifest's whole purpose: a useful error, not a control that does nothing."""
    with pytest.raises(ValueError) as excinfo:
        resolve(load_control_map({"dofs": {"my_wrist": "vhi.prediction.wrist"}}), VHI)
    message = str(excinfo.value)
    assert "does not export" in message
    assert "vhi.prediction.wrist" in message
    assert "vhi.prediction.index" in message, "it must list what IS available"


def test_the_error_names_near_misses_first():
    with pytest.raises(ValueError, match="Did you mean"):
        resolve(load_control_map({"dofs": {"a": "vhi.prediction.pinky"}}), VHI)


def test_every_fault_is_reported_not_just_the_first():
    """A half-corrected config file is worse than an uncorrected one."""
    with pytest.raises(ValueError) as excinfo:
        resolve(
            load_control_map({"dofs": {"a": "vhi.nope.one", "b": "vhi.nope.two"}}), VHI
        )
    assert "vhi.nope.one" in str(excinfo.value)
    assert "vhi.nope.two" in str(excinfo.value)


# --- fan-out ---------------------------------------------------------------------


def test_a_list_fans_one_output_out_to_many_targets():
    """No whole-hand capability needed just to close the hand."""
    cmap = load_control_map(
        {"dofs": {"fist": [f"vhi.prediction.{d}" for d in FINGERS[1:]]}}
    )
    resolved = resolve(cmap, VHI)
    assert [r.address for r in resolved.routes["fist"]] == [
        f"vhi.prediction.{d}" for d in FINGERS[1:]
    ]
    assert all(r.weight == 1.0 for r in resolved.routes["fist"]), "broadcast is equal by default"


def test_a_weighted_fan_out_carries_its_gains():
    cmap = load_control_map(
        {
            "dofs": {
                "pinch": [
                    {"target": "vhi.prediction.thumb", "weight": 0.6},
                    {"target": "vhi.prediction.index"},
                ]
            }
        }
    )
    routes = resolve(cmap, VHI).routes["pinch"]
    assert [(r.address, r.weight) for r in routes] == [
        ("vhi.prediction.thumb", 0.6),
        ("vhi.prediction.index", 1.0),
    ]


def test_a_mixed_list_of_addresses_and_tables_is_accepted():
    cmap = load_control_map(
        {
            "dofs": {
                "fist": [
                    "vhi.prediction.index",
                    {"target": "vhi.prediction.thumb", "weight": 0.6},
                ]
            }
        }
    )
    assert [r.weight for r in cmap.bindings["fist"].targets] == [1.0, 0.6]


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_weight_is_refused(weight):
    """It becomes a full-scale deflection the moment it is multiplied in."""
    with pytest.raises(ValueError, match="finite"):
        load_control_map(
            {"dofs": {"a": [{"target": "vhi.prediction.index", "weight": weight}]}}
        )


def test_a_negative_weight_needs_a_target_that_can_render_it():
    """On a one-way control there is no opposite direction to send."""
    with pytest.raises(ValueError, match="negative"):
        resolve(
            load_control_map(
                {"dofs": {"f": [{"target": "vhi.grip.force", "weight": -1.0}]}}
            ),
            VHI,
        )


def test_a_negative_weight_is_allowed_on_a_signed_target():
    resolved = resolve(
        load_control_map(
            {"dofs": {"a": [{"target": "vhi.prediction.index", "weight": -1.0}]}}
        ),
        VHI,
    )
    assert resolved.routes["a"][0].weight == -1.0


def test_a_duplicate_address_in_one_binding_is_refused():
    """Two entries for one address would silently apply only the last weight."""
    with pytest.raises(ValueError, match="more than once"):
        load_control_map(
            {
                "dofs": {
                    "a": [
                        {"target": "vhi.prediction.index", "weight": 0.5},
                        "vhi.prediction.index",
                    ]
                }
            }
        )


def test_a_fan_out_across_kinds_is_refused():
    """One output cannot be both a number and a held state."""
    with pytest.raises(ValueError, match="disagree about what they take"):
        resolve(
            load_control_map(
                {"dofs": {"a": ["vhi.prediction.index", "vhi.control.gesture"]}}
            ),
            VHI,
        )


def test_a_fan_out_is_signed_only_if_every_member_is():
    """Otherwise a negative prediction is silently clamped away on one member."""
    cmap = load_control_map({"dofs": {"a": ["vhi.prediction.index", "vhi.grip.force"]}})
    assert resolve(cmap, VHI).dofs["a"].lo == 0.0


# --- structure -------------------------------------------------------------------


def test_debounce_is_declared_on_this_side():
    """It is a property of the control loop, not of the target."""
    cmap = load_control_map(
        {"dofs": {"g": {"target": "vhi.control.gesture", "debounce_s": 0.25}}}
    )
    assert resolve(cmap, VHI).dofs["g"].debounce_s == 0.25


def test_an_empty_binding_is_refused():
    with pytest.raises(ValueError, match="binds nothing"):
        load_control_map({"dofs": {"a": []}})


def test_a_missing_dofs_table_says_what_to_write():
    with pytest.raises(ValueError, match="vhi.prediction.index"):
        load_control_map({})


def test_the_map_round_trips_through_as_dict():
    original = {
        "dofs": {
            "my_index": "vhi.prediction.index",
            "fist": ["vhi.prediction.middle", "vhi.prediction.ring"],
            "pinch": {
                "targets": [
                    {"target": "vhi.prediction.thumb", "weight": 0.6},
                    {"target": "vhi.prediction.index", "weight": 1.0},
                ]
            },
        }
    }
    once = load_control_map(original)
    twice = load_control_map(once.as_dict())
    assert once.as_dict() == twice.as_dict()


def test_routes_are_kept_beside_the_dofs_not_baked_into_names():
    """A Dof describes what the alias accepts; routes say where it goes."""
    resolved = resolve(load_control_map({"dofs": {"a": "vhi.prediction.index"}}), VHI)
    assert resolved.dofs["a"].name == "a", "the Dof keeps the user's name"
    assert resolved.routes["a"][0].address == "vhi.prediction.index"
