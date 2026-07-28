"""The runtime transforms: sanitising, clipping, and the wire vector.

These are what run on the predict thread every tick, so what they must never do is as
important as what they do: never raise, never let a NaN become a full-scale deflection,
never let a value leave the range its control declared.

They are also deliberately **alias-agnostic** — a DOF's name is the user's own label and
these functions treat it as an opaque key. That is why the alias/address migration left
them untouched. `ControlSet` is built directly here rather than parsed, because the
resolved form is what these operate on; parsing is `tests/test_controls_map.py`.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from myogestic.controls import (
    Continuous,
    ControlSet,
    Discrete,
    clip,
    decode,
    encode,
    substitute_rest,
)

#: Two continuous aliases with different domains, plus a held state — the shapes that
#: exercise every branch. `force` is one-way on purpose: a global rail would be wrong.
MIXED = ControlSet(
    dofs={
        "wrist": Continuous("wrist"),                          # signed [-1, 1]
        "force": Continuous("force", lo=0.0, hi=1.0),           # one-way
        "grasp": Discrete("grasp", ("rest", "fist"), "rest"),
    }
)


# --- substitute_rest: the predict thread must survive anything --------------------


@pytest.mark.parametrize(
    "bad",
    [
        {},                                # nothing supplied
        {"wrist": math.nan},               # NaN
        {"wrist": math.inf},               # inf
        {"wrist": "not a number"},         # wrong type
        {"wrist": None},                   # explicit None
        {"grasp": "unknown_state"},        # a state that does not exist
        {"grasp": 3},                      # wrong type for a discrete control
        {"wrist": np.float32("nan")},      # the library's own prediction dtype
    ],
)
def test_substitute_rest_never_raises_and_lands_on_rest(bad):
    out = substitute_rest(MIXED, bad)
    assert out["wrist"] == 0.0
    assert out["force"] == 0.0
    assert out["grasp"] == "rest"


def test_substitute_rest_drops_undeclared_keys():
    """A predict dict carries other things; they are not this function's business."""
    out = substitute_rest(MIXED, {"wrist": 0.5, "class": "Fist", "debug": 3})
    assert set(out) == {"wrist", "force", "grasp"}
    assert out["wrist"] == 0.5


def test_nan_does_not_become_full_scale_deflection():
    """`min(1, max(-1, nan))` is -1.0 in Python — rest substitution must come first."""
    assert min(1.0, max(-1.0, float("nan"))) == -1.0  # the trap, pinned
    out, _ = clip(MIXED, substitute_rest(MIXED, {"wrist": math.nan}))
    assert out["wrist"] == 0.0


def test_a_numpy_float32_is_not_a_float_subclass():
    """It is this library's prediction dtype, so treating it as unusable flattens every
    prediction to rest. Pinned because `isinstance(np.float32(1), float)` is False."""
    assert not isinstance(np.float32(1.0), float)
    assert substitute_rest(MIXED, {"wrist": np.float32(0.5)})["wrist"] == pytest.approx(0.5)


# --- clip: each control's own declared range -------------------------------------


def test_clip_uses_the_declared_range_not_a_global_rail():
    out, clipped = clip(MIXED, {"wrist": 5.0, "force": -3.0, "grasp": "fist"})
    assert out["wrist"] == 1.0
    assert out["force"] == 0.0, "NOT -1.0: this control declares [0, 1]"
    assert out["grasp"] == "fist"
    assert set(clipped) == {"wrist", "force"}


def test_clip_reports_nothing_when_inside_range():
    _, clipped = clip(MIXED, {"wrist": -0.5, "force": 0.5, "grasp": "rest"})
    assert clipped == ()


# --- encode / decode -------------------------------------------------------------


def test_encode_is_continuous_only_in_declaration_order():
    vec = encode(MIXED, {"wrist": -0.5, "force": 0.25, "grasp": "fist"})
    assert vec.dtype == np.float32
    assert vec.tolist() == [-0.5, 0.25], "the discrete control is not on the vector"


def test_encode_decode_round_trip():
    values = {"wrist": -0.75, "force": 0.5}
    assert decode(MIXED, encode(MIXED, values)) == pytest.approx(values)


def test_encode_decode_round_trip_is_signed():
    """A signed control must survive both halves, which is what [-1, 1] buys."""
    controls = ControlSet(dofs={"wrist": Continuous("wrist")})
    for v in (-1.0, -0.25, 0.0, 0.25, 1.0):
        assert decode(controls, encode(controls, {"wrist": v}))["wrist"] == pytest.approx(v)


def test_decode_rejects_a_short_frame():
    with pytest.raises(ValueError, match="continuous DOFs are declared"):
        decode(MIXED, [0.0])


def test_decode_is_the_exact_inverse_of_encode():
    """A wider frame is a target's concern, never this vector's."""
    controls = ControlSet(dofs={"wrist": Continuous("wrist")})
    with pytest.raises(ValueError, match="exact inverse"):
        decode(controls, [0.0, 0.0])


def test_encode_cannot_overflow_a_float32_wire():
    controls = ControlSet(dofs={"torque": Continuous("torque")})
    old = np.seterr(all="raise")
    try:
        assert encode(controls, {"torque": 1.0}).tolist() == [1.0]
    finally:
        np.seterr(**old)


# --- the resolved set itself -----------------------------------------------------


def test_rest_values_is_the_neutral_frame():
    assert MIXED.rest_values() == {"wrist": 0.0, "force": 0.0, "grasp": "rest"}


def test_channel_labels_are_the_aliases_in_declaration_order():
    """What a target publishes as channel names: the user's vocabulary, not addresses."""
    assert MIXED.channel_labels() == ("wrist", "force")


def test_an_empty_control_set_is_usable():
    empty = ControlSet()
    assert empty.rest_values() == {}
    assert empty.channel_labels() == ()
    assert encode(empty, {}).tolist() == []


def test_a_resolved_dof_is_immutable():
    """A control space that changed under a running bus would be unaccountable."""
    with pytest.raises(FrozenInstanceError):
        MIXED.dofs["wrist"].lo = 0.0


@pytest.mark.parametrize("alias", ["wrist", "drive_x", "My Wrist", "fist", "x-2"])
def test_the_transforms_treat_the_alias_as_opaque(alias):
    """The reason this whole module survived the alias migration untouched."""
    controls = ControlSet(dofs={alias: Continuous(alias)})
    assert substitute_rest(controls, {alias: 0.5})[alias] == 0.5
    assert clip(controls, {alias: 5.0})[0][alias] == 1.0
    assert encode(controls, {alias: 0.25}).tolist() == [0.25]
    assert decode(controls, [0.25])[alias] == pytest.approx(0.25)


class TestAClassifierActivationIsGatedNotStreamed:
    """A classifier's probability must reach a target as 0 or 1, never as itself.

    The reason is that a continuous target address is a *position*. Sending 0.73 into
    one says the finger is 73% curled, which is not what a 73%-confident classifier
    meant. Gating it here, before the fan-out weights and before the wire, is what lets
    one grouped mapping serve a regressor and a classifier alike.
    """

    GATED = ControlSet(dofs={"fist": Continuous("fist", lo=0.0, hi=1.0, threshold=0.6)})

    @pytest.mark.parametrize(
        ("probability", "expected"),
        [(0.0, 0.0), (0.42, 0.0), (0.599, 0.0), (0.6, 1.0), (0.73, 1.0), (1.0, 1.0)],
    )
    def test_a_probability_becomes_an_activation(self, probability, expected):
        assert substitute_rest(self.GATED, {"fist": probability})["fist"] == expected

    def test_the_threshold_is_inclusive(self):
        """Declaring 0.6 and reading exactly 0.6 must activate, not sit at the edge."""
        assert substitute_rest(self.GATED, {"fist": 0.6})["fist"] == 1.0

    def test_no_threshold_leaves_the_value_alone(self):
        """The regression path is untouched: a regressed 0.73 is a real position."""
        plain = ControlSet(dofs={"fist": Continuous("fist", lo=0.0, hi=1.0)})
        assert substitute_rest(plain, {"fist": 0.73})["fist"] == 0.73

    def test_a_missing_activation_still_rests(self):
        """Gating must not turn an absent value into a spurious activation."""
        assert substitute_rest(self.GATED, {})["fist"] == 0.0

    def test_unusable_input_rests_rather_than_gating_garbage(self):
        """rest, not `"" >= 0.6`."""
        assert substitute_rest(self.GATED, {"fist": "closed"})["fist"] == 0.0
