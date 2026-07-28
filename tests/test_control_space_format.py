"""A recording must say which control-space format it used, and refuse the older one.

The alias/address form is required. An older control space declared its own kinds and
ranges — facts the target now owns — so there is no faithful way to read it forward:
reinterpreting it would put invented semantics on archived data and present them as
recorded fact. It is refused by name instead, and the refusal says what to do.
"""

from __future__ import annotations

import json

import pytest

from myogestic.controls import (
    CONTROL_SPACE_FORMAT,
    load_control_map,
    read_control_space,
)

NEW = {"dofs": {"my_index": "vhi.prediction.index", "fist": ["vhi.prediction.middle"]}}


def test_a_written_control_space_names_its_own_format():
    """Legible rather than inferred — a reader should not have to guess from the shape."""
    persisted = load_control_map(NEW).as_dict()
    assert persisted["format"] == CONTROL_SPACE_FORMAT


def test_it_round_trips():
    persisted = load_control_map(NEW).as_dict()
    assert read_control_space(persisted).addresses() == (
        "vhi.prediction.index",
        "vhi.prediction.middle",
    )


def test_it_survives_a_json_round_trip():
    """It is stored in meta.json, so the trip through JSON is the real one."""
    persisted = json.loads(json.dumps(load_control_map(NEW).as_dict()))
    assert read_control_space(persisted).bindings.keys() == {"my_index", "fist"}


@pytest.mark.parametrize(
    "old",
    [
        {"dofs": {"index.flexion": "continuous"}},
        {"dofs": {"hand.grasp": ["rest", "fist"]}},
        {"dofs": {"grip.force": {"kind": "continuous", "range": [0.0, 1.0]}}},
        {"standard_version": "1", "dofs": {"index.flexion": {"kind": "continuous"}}},
    ],
)
def test_a_pre_alias_control_space_fails_fast(old):
    """Not normalised, not guessed at — refused, with the reason."""
    with pytest.raises(ValueError, match="predates the alias/address format"):
        read_control_space(old)


def test_the_refusal_says_what_to_do():
    with pytest.raises(ValueError) as excinfo:
        read_control_space({"dofs": {"index.flexion": "continuous"}})
    message = str(excinfo.value)
    assert CONTROL_SPACE_FORMAT in message, "it must name the format it wanted"
    assert "Re-record" in message, "and what the reader should do about it"


def test_an_unknown_format_is_refused_by_name():
    """A newer writer must not be silently misread by an older reader."""
    with pytest.raises(ValueError, match="unknown control-space format"):
        read_control_space({"format": "alias-address/99", "dofs": {}})


def test_nothing_is_rewritten_on_read():
    """Reading must not mutate the archive it was handed."""
    persisted = load_control_map(NEW).as_dict()
    before = json.dumps(persisted, sort_keys=True)
    read_control_space(persisted)
    assert json.dumps(persisted, sort_keys=True) == before
