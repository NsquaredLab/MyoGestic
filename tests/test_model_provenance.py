"""A model is only meaningful in the output space it was fitted for.

Loading one trained on a one-way ``[0, 1]`` DOF against a signed ``[-1, 1]``
configuration produces motion in a direction the model never learned, and nothing
in the artifact itself would say so. These pin the sidecar that closes that gap —
and that it stays entirely optional, since artifacts saved before it existed must
keep loading.
"""

from __future__ import annotations

import pytest

from myogestic.controls import load_dofs
from myogestic.ml import load_pickle, save_pickle

SIGNED = load_dofs({"dofs": {"index.flexion": "continuous"}})
ONE_WAY = load_dofs(
    {"dofs": {"index.flexion": {"kind": "continuous", "range": [0.0, 1.0]}}}
)


def test_a_model_saved_without_controls_has_no_sidecar(tmp_path):
    """The default path is unchanged for every existing caller."""
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib")
    assert not (tmp_path / "m.joblib.controls.json").exists()
    assert load_pickle(path) == {"weights": 1}


def test_provenance_round_trips(tmp_path):
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib", controls=SIGNED)
    assert (tmp_path / "m.joblib.controls.json").exists()
    assert load_pickle(path, controls=SIGNED) == {"weights": 1}


def test_a_mismatched_control_space_is_refused(tmp_path):
    """Same DOF name, different declared range — the case a name cannot catch."""
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib", controls=ONE_WAY)
    with pytest.raises(ValueError, match="was trained for"):
        load_pickle(path, controls=SIGNED)


def test_a_different_dof_set_is_refused(tmp_path):
    other = load_dofs({"dofs": {"thumb.flexion": "continuous"}})
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib", controls=SIGNED)
    with pytest.raises(ValueError, match="was trained for"):
        load_pickle(path, controls=other)


def test_a_sidecar_less_model_is_refused_when_checking(tmp_path):
    """An artifact predating provenance is indistinguishable from a wrong one."""
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib")
    with pytest.raises(ValueError, match="no control-space sidecar"):
        load_pickle(path, controls=SIGNED)


def test_the_override_is_explicit(tmp_path):
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib")
    assert load_pickle(path, controls=SIGNED, allow_unverified=True) == {"weights": 1}


def test_checking_is_opt_in(tmp_path):
    """Omitting `controls` never consults the sidecar, even when one exists."""
    path = save_pickle({"weights": 1}, tmp_path / "m.joblib", controls=ONE_WAY)
    assert load_pickle(path) == {"weights": 1}
