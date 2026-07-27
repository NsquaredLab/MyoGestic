"""Tests for the canonical control standard (`myogestic.controls`).

These pin the parts a user meets first: that a one-line DOF really is signed and
bidirectional, that every configuration fault is reported together, that the three
TOML shapes TOML itself accepts-but-misreads are named errors, and that the
runtime transforms never raise on the predict thread.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from myogestic.controls import (
    STANDARD_VERSION,
    Continuous,
    ControlSet,
    Discrete,
    clip,
    decode,
    encode,
    load_dofs,
    substitute_rest,
)

# --- the default is signed ----------------------------------------------------


def test_one_line_dof_is_signed_and_bidirectional():
    """The whole point of the standard: no range boilerplate for a normal control."""
    controls = load_dofs({"dofs": {"index.flexion": "continuous"}})
    dof = controls.dofs["index.flexion"]
    assert (dof.lo, dof.hi, dof.rest) == (-1.0, 1.0, 0.0)
    assert controls.standard_version == STANDARD_VERSION


def test_array_value_declares_a_discrete_dof():
    controls = load_dofs({"dofs": {"hand.grasp": ["rest", "fist", "pinch"]}})
    dof = controls.dofs["hand.grasp"]
    assert isinstance(dof, Discrete)
    assert dof.states == ("rest", "fist", "pinch")
    assert dof.rest == "rest"


def test_inline_table_escalates_to_a_one_way_range():
    controls = load_dofs(
        {"dofs": {"grip.force": {"kind": "continuous", "range": [0.0, 1.0]}}}
    )
    dof = controls.dofs["grip.force"]
    assert (dof.lo, dof.hi, dof.rest) == (0.0, 1.0, 0.0)


def test_declaration_order_is_the_wire_order():
    controls = load_dofs(
        {
            "dofs": {
                "b.flexion": "continuous",
                "hand.grasp": ["rest", "fist"],
                "a.flexion": "continuous",
            }
        }
    )
    assert controls.channel_labels() == ("b.flexion", "a.flexion")
    assert [d.name for d in controls.discrete] == ["hand.grasp"]


def test_documented_toml_parses():
    """The shape in the module docstring must actually load."""
    controls = load_dofs(
        tomllib.loads(
            '[dofs]\n'
            '"index.flexion" = "continuous"\n'
            '"hand.grasp"    = ["rest", "fist", "pinch"]\n'
            '"grip.force"    = { kind = "continuous", range = [0.0, 1.0] }\n'
            "\n[simultaneous]\n"
            'proportional = ["index.flexion"]\n'
        )
    )
    assert controls.channel_labels() == ("index.flexion", "grip.force")
    assert controls.n_concurrent == 1


def test_as_dict_round_trips():
    original = load_dofs(
        {
            "dofs": {
                "a.flexion": "continuous",
                "g.force": {"kind": "continuous", "range": [0.0, 1.0], "rest": 0.0},
                "hand.grasp": {
                    "kind": "discrete",
                    "states": ["rest", "fist"],
                    "debounce_s": 0.12,
                },
            },
            "simultaneous": {"grip": ["hand.grasp"]},
        }
    )
    assert load_dofs(original.as_dict()) == original


# --- errors accumulate --------------------------------------------------------


def test_every_fault_is_reported_together():
    """Three typos must cost one edit round-trip, not three runs."""
    with pytest.raises(ValueError) as exc:
        load_dofs(
            {
                "dofs": {
                    "Bad Name": "continuous",
                    "a.flexion": "contnuous",
                    "b.flexion": {"kind": "continuous", "range": [1.0, 0.0]},
                }
            }
        )
    msg = str(exc.value)
    assert "Bad Name" in msg
    assert "contnuous" in msg
    assert "b.flexion" in msg
    assert len(msg.splitlines()) >= 3


def test_missing_dofs_table_names_the_block():
    with pytest.raises(ValueError, match=r"\[dofs\]"):
        load_dofs({"simultaneous": {}})


# --- the three TOML shapes TOML accepts but misreads --------------------------


def test_float_array_is_not_a_range():
    """`"g.force" = [0.0, 1.0]` parses as two float states; say so."""
    with pytest.raises(ValueError, match="arrays declare discrete states"):
        load_dofs({"dofs": {"g.force": [0.0, 1.0]}})


def test_unquoted_dotted_key_is_caught():
    """`hand.grip = "continuous"` nests a table and would silently lose a DOF."""
    with pytest.raises(ValueError, match="unquoted dotted key"):
        load_dofs({"dofs": {"hand": {"grip": "continuous"}}})


def test_rest_at_a_non_zero_index_is_caught():
    """The array form makes element 0 neutral, so a later 'rest' reads backwards."""
    with pytest.raises(ValueError, match="'rest' appears at index 1"):
        load_dofs({"dofs": {"hand.grasp": ["fist", "rest"]}})


# --- domain validation --------------------------------------------------------


@pytest.mark.parametrize("rng", [[-1.0, 1.0], [0.0, 1.0], [-1.0, 0.0], [-0.5, 0.5]])
def test_rest_expressible_ranges_are_accepted(rng):
    controls = load_dofs({"dofs": {"a.flexion": {"kind": "continuous", "range": rng}}})
    dof = controls.dofs["a.flexion"]
    assert dof.lo <= dof.rest <= dof.hi


def test_range_that_cannot_hold_a_neutral_value_is_rejected():
    """`[-0.6, 1.0]` would park rest off-centre — the value meaning 'no command'."""
    with pytest.raises(ValueError, match="cannot hold a neutral value"):
        load_dofs({"dofs": {"a.flexion": {"kind": "continuous", "range": [-0.6, 1.0]}}})


def test_inverted_range_is_rejected_with_the_fix():
    with pytest.raises(ValueError, match=r"range must be increasing"):
        load_dofs({"dofs": {"a.flexion": {"kind": "continuous", "range": [1.0, -1.0]}}})


def test_non_finite_range_is_rejected():
    with pytest.raises(ValueError, match="range must be finite"):
        load_dofs(
            {"dofs": {"a.flexion": {"kind": "continuous", "range": [0.0, math.inf]}}}
        )


def test_rest_outside_range_is_rejected():
    with pytest.raises(ValueError, match="outside range"):
        load_dofs(
            {"dofs": {"a.flexion": {"kind": "continuous", "range": [0.0, 1.0], "rest": 2.0}}}
        )


def test_states_on_a_continuous_dof_is_rejected():
    with pytest.raises(ValueError, match="states belong to a discrete DOF"):
        load_dofs({"dofs": {"a.flexion": {"kind": "continuous", "states": ["x", "y"]}}})


@pytest.mark.parametrize(
    ("states", "match"),
    [
        (["only"], "at least two states"),
        (["a", "a"], "duplicate states"),
    ],
)
def test_bad_state_lists_are_rejected(states, match):
    with pytest.raises(ValueError, match=match):
        load_dofs({"dofs": {"hand.grasp": states}})


def test_rest_not_in_states_is_rejected():
    with pytest.raises(ValueError, match="is not one of"):
        load_dofs(
            {"dofs": {"hand.grasp": {"kind": "discrete", "states": ["a", "b"], "rest": "c"}}}
        )


def test_negative_debounce_is_rejected():
    with pytest.raises(ValueError, match="debounce_s must be >= 0"):
        load_dofs(
            {"dofs": {"hand.grasp": {"kind": "discrete", "states": ["a", "b"],
                                     "debounce_s": -1.0}}}
        )


@pytest.mark.parametrize("name", ["Index.Flexion", "index flexion", "1index", "index..x"])
def test_non_canonical_names_are_rejected(name):
    with pytest.raises(ValueError, match="not a canonical control name"):
        load_dofs({"dofs": {name: "continuous"}})


# --- [simultaneous] -----------------------------------------------------------


def test_absent_simultaneous_means_zero_controls_not_everything():
    """Absent must never be read as 'every DOF is live'."""
    controls = load_dofs({"dofs": {"a.flexion": "continuous", "b.flexion": "continuous"}})
    assert controls.simultaneous == {}
    assert controls.n_concurrent == 0


def test_simultaneous_counts_controls_not_dofs():
    controls = load_dofs(
        {
            "dofs": {"a.flexion": "continuous", "b.flexion": "continuous",
                     "c.flexion": "continuous"},
            "simultaneous": {"hand": ["a.flexion", "b.flexion", "c.flexion"]},
        }
    )
    assert controls.n_concurrent == 1


def test_simultaneous_rejects_unknown_and_empty():
    with pytest.raises(ValueError, match="are not declared DOFs"):
        load_dofs({"dofs": {"a.flexion": "continuous"}, "simultaneous": {"g": ["nope"]}})
    with pytest.raises(ValueError, match="names no DOFs"):
        load_dofs({"dofs": {"a.flexion": "continuous"}, "simultaneous": {"g": []}})


def test_simultaneous_rejects_a_dof_named_twice():
    with pytest.raises(ValueError, match="names a DOF twice"):
        load_dofs(
            {
                "dofs": {"a.flexion": "continuous"},
                "simultaneous": {"g": ["a.flexion", "a.flexion"]},
            }
        )


# --- runtime transforms: never raise -----------------------------------------

_MIXED = load_dofs(
    {
        "dofs": {
            "a.flexion": "continuous",
            "g.force": {"kind": "continuous", "range": [0.0, 1.0]},
            "hand.grasp": ["rest", "fist"],
        }
    }
)


@pytest.mark.parametrize(
    "bad",
    [
        {},                                    # nothing supplied
        {"a.flexion": math.nan},               # NaN
        {"a.flexion": math.inf},               # inf
        {"a.flexion": "not a number"},         # wrong type
        {"a.flexion": None},                   # explicit None
        {"hand.grasp": "unknown_state"},       # state that does not exist
        {"hand.grasp": 3},                     # wrong type for discrete
    ],
)
def test_substitute_rest_never_raises_and_lands_on_rest(bad):
    out = substitute_rest(_MIXED, bad)
    assert out["a.flexion"] == 0.0
    assert out["g.force"] == 0.0
    assert out["hand.grasp"] == "rest"


def test_substitute_rest_drops_undeclared_keys():
    """A predict dict carries other things; they are not this function's business."""
    out = substitute_rest(_MIXED, {"a.flexion": 0.5, "class": "Fist", "debug": 3})
    assert set(out) == {"a.flexion", "g.force", "hand.grasp"}
    assert out["a.flexion"] == 0.5


def test_nan_does_not_become_full_scale_deflection():
    """`min(1, max(-1, nan))` is -1.0 in Python — rest substitution must come first."""
    assert min(1.0, max(-1.0, float("nan"))) == -1.0  # the trap, pinned
    out, _ = clip(_MIXED, substitute_rest(_MIXED, {"a.flexion": math.nan}))
    assert out["a.flexion"] == 0.0


def test_clip_uses_the_declared_range_not_a_global_rail():
    out, clipped = clip(_MIXED, {"a.flexion": 5.0, "g.force": -3.0, "hand.grasp": "fist"})
    assert out["a.flexion"] == 1.0
    assert out["g.force"] == 0.0        # NOT -1.0: this DOF declares [0, 1]
    assert out["hand.grasp"] == "fist"
    assert set(clipped) == {"a.flexion", "g.force"}


def test_clip_reports_nothing_when_inside_range():
    _, clipped = clip(_MIXED, {"a.flexion": -0.5, "g.force": 0.5, "hand.grasp": "rest"})
    assert clipped == ()


# --- encode / decode ----------------------------------------------------------


def test_encode_is_continuous_only_in_declaration_order():
    vec = encode(_MIXED, {"a.flexion": -0.5, "g.force": 0.25, "hand.grasp": "fist"})
    assert vec.dtype == np.float32
    assert vec.tolist() == [-0.5, 0.25]


def test_encode_decode_round_trip():
    values = {"a.flexion": -0.75, "g.force": 0.5}
    assert decode(_MIXED, encode(_MIXED, values)) == pytest.approx(values)


def test_encode_decode_round_trip_is_signed():
    """A signed DOF must survive both halves, which is what [-1,1] buys."""
    controls = load_dofs({"dofs": {"wrist.pronation": "continuous"}})
    for v in (-1.0, -0.25, 0.0, 0.25, 1.0):
        back = decode(controls, encode(controls, {"wrist.pronation": v}))
        assert back["wrist.pronation"] == pytest.approx(v)


def test_decode_rejects_a_short_frame():
    with pytest.raises(ValueError, match="continuous DOFs are declared"):
        decode(_MIXED, [0.0])


def test_rest_values_is_the_neutral_frame():
    assert _MIXED.rest_values() == {"a.flexion": 0.0, "g.force": 0.0, "hand.grasp": "rest"}


def test_empty_control_set_is_usable():
    empty = ControlSet()
    assert empty.channel_labels() == ()
    assert encode(empty, {}).shape == (0,)
    assert empty.n_concurrent == 0


# --- regressions found by adversarial review ---------------------------------


@pytest.mark.parametrize(
    "value",
    [
        np.float32(0.5),   # the library's own prediction dtype — NOT a subclass of float
        np.float64(0.5),
        np.float16(0.5),
        np.int32(1),
        np.array(0.5),     # 0-d array
        1,                 # plain int
        0.5,               # plain float
    ],
)
def test_every_numeric_type_survives_the_transforms(value):
    """`np.float32` is not a `float` subclass, and predictions arrive as float32.

    An `isinstance(v, float)` guard silently substituted rest for every real
    prediction — the whole trace would have gone flat with nothing logged.
    """
    controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    expected = float(value)
    assert substitute_rest(controls, {"a.flexion": value})["a.flexion"] == pytest.approx(
        expected, abs=1e-6
    )
    frame, clipped = clip(controls, {"a.flexion": value})
    assert frame["a.flexion"] == pytest.approx(expected, abs=1e-6)
    assert clipped == ()
    assert encode(controls, {"a.flexion": value})[0] == pytest.approx(expected, abs=1e-6)


class _ExplodingFloat:
    """A value whose ``__float__`` raises — must never reach the predict thread."""

    def __float__(self) -> float:
        raise RuntimeError("boom")


@pytest.mark.parametrize(
    "value",
    [10**400, _ExplodingFloat(), b"1.5", bytearray(b"1.5"), "1e5", [1.0], {"a": 1}],
)
def test_hostile_values_become_rest_without_raising(value):
    """Nothing on the predict thread may raise, and no string is parsed into motion."""
    controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    assert substitute_rest(controls, {"a.flexion": value})["a.flexion"] == 0.0
    frame, clipped = clip(controls, {"a.flexion": value})
    assert frame["a.flexion"] == 0.0
    assert clipped == ("a.flexion",)  # a substitution is reported, not silent
    assert encode(controls, {"a.flexion": value})[0] == 0.0


def test_bool_means_the_same_thing_everywhere():
    """`True` is an int in Python; the transforms must not disagree about it."""
    controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    assert substitute_rest(controls, {"a.flexion": True})["a.flexion"] == 1.0
    assert clip(controls, {"a.flexion": True})[0]["a.flexion"] == 1.0


def test_explicit_rest_may_order_states_freely():
    """The rest-position guard belongs to the array form only.

    The table form says which state is neutral, so it may list them in any order —
    rejecting it told the author to do exactly what they had already done.
    """
    controls = load_dofs(
        {"dofs": {"hand.grasp": {"kind": "discrete", "states": ["fist", "rest"],
                                 "rest": "rest"}}}
    )
    assert controls.dofs["hand.grasp"].rest == "rest"
    assert load_dofs(controls.as_dict()) == controls


@pytest.mark.parametrize("key", ["rest", "label", "debounce_s", "range", "states"])
def test_an_unquoted_dotted_key_cannot_insert_a_phantom_dof(key):
    """A phantom DOF would shift every wire channel after it."""
    with pytest.raises(ValueError):
        load_dofs({"dofs": {"a.flexion": "continuous", "hand": {key: 0.0}}})


@pytest.mark.parametrize("rng", [[-1e39, 1e39], [0.0, 100.0], [-2.0, 2.0]])
def test_ranges_outside_the_normalized_domain_are_rejected(rng):
    """Continuous DOFs are normalized; a target owns its own units and gain.

    A wide range also puts an unrepresentable magnitude on a float32 wire.
    """
    with pytest.raises(ValueError, match="leaves the normalized domain"):
        load_dofs({"dofs": {"j.torque": {"kind": "continuous", "range": rng}}})


def test_encode_cannot_overflow_a_float32_wire():
    controls = load_dofs({"dofs": {"j.torque": "continuous"}})
    old = np.seterr(all="raise")
    try:
        assert encode(controls, {"j.torque": 1.0}).tolist() == [1.0]
    finally:
        np.seterr(**old)


def test_a_trailing_newline_cannot_forge_a_second_dof():
    """With `match` instead of `fullmatch`, two identical-looking labels slipped in."""
    with pytest.raises(ValueError, match="not a canonical control name"):
        load_dofs({"dofs": {"index.flexion\n": "continuous", "index.flexion": "continuous"}})


@pytest.mark.parametrize(
    "config",
    [
        {"dofs": {1: "continuous"}},
        {"dofs": {"a.b": "continuous"}, "simultaneous": {"g": [["a.b"]]}},
        {"dofs": {"a.b": "continuous"}, "simultaneous": {1: ["a.b"]}},
    ],
)
def test_bad_key_types_raise_value_error_not_type_error(config):
    """Faults must flow through accumulate-once, not escape as a TypeError."""
    with pytest.raises(ValueError):
        load_dofs(config)


def test_declared_list_names_what_the_author_wrote():
    """A DOF that failed its own check must not also read as 'not declared'."""
    with pytest.raises(ValueError) as exc:
        load_dofs({"dofs": {"bad name": "continuous"}, "simultaneous": {"g": ["bad name"]}})
    assert "Declared: []" not in str(exc.value)


def test_decode_is_the_exact_inverse_of_encode():
    """A wider frame is a legacy/target concern, never a canonical one."""
    controls = load_dofs({"dofs": {"a.flexion": "continuous"}})
    with pytest.raises(ValueError, match="exact inverse"):
        decode(controls, [0.0, 0.0])


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"kind": "continuous", "label": ["x"]}, "label must be a string"),
        ({"kind": "continuous", "debounce_s": 0.1}, "debounce_s belongs to a discrete"),
    ],
)
def test_cross_kind_keys_are_refused_not_ignored(config, match):
    with pytest.raises(ValueError, match=match):
        load_dofs({"dofs": {"a.flexion": config}})


def test_range_on_a_discrete_dof_is_refused():
    with pytest.raises(ValueError, match="range belongs to a continuous"):
        load_dofs(
            {"dofs": {"h.grasp": {"kind": "discrete", "states": ["a", "b"],
                                  "range": [0.0, 1.0]}}}
        )


def test_continuous_and_discrete_are_frozen():
    with pytest.raises(FrozenInstanceError):
        Continuous("a.flexion").lo = 5.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        Discrete("h.grasp", ("rest", "fist"), "rest").rest = "fist"  # type: ignore[misc]
