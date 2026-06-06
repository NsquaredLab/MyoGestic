import pytest

from myogestic.outputs import EdgeTrigger


def test_fires_on_first_call():
    fired = []
    et = EdgeTrigger(fired.append)
    assert et.fire_if_changed("A") is True
    assert fired == ["A"]


def test_suppresses_repeat():
    fired = []
    et = EdgeTrigger(fired.append)
    et.fire_if_changed("A")
    assert et.fire_if_changed("A") is False
    assert et.fire_if_changed("A") is False
    assert fired == ["A"]


def test_fires_on_change():
    fired = []
    et = EdgeTrigger(fired.append)
    et.fire_if_changed("A")
    assert et.fire_if_changed("B") is True
    assert fired == ["A", "B"]


def test_rebase_suppresses_next_matching_fire():
    fired = []
    et = EdgeTrigger(fired.append)
    et.rebase("X")
    assert et.fire_if_changed("X") is False
    assert fired == []


def test_rebase_doesnt_suppress_different_value():
    fired = []
    et = EdgeTrigger(fired.append)
    et.rebase("X")
    assert et.fire_if_changed("Y") is True
    assert fired == ["Y"]


def test_last_property_tracks_state():
    fired = []
    et = EdgeTrigger(fired.append)
    assert et.last is None
    et.fire_if_changed("A")
    assert et.last == "A"
    et.rebase("Z")
    assert et.last == "Z"


def test_typed_with_int():
    """Generic over T — works with ints too, not just strings."""
    fired: list[int] = []
    et: EdgeTrigger[int] = EdgeTrigger(fired.append)
    et.fire_if_changed(0)
    et.fire_if_changed(0)
    et.fire_if_changed(1)
    assert fired == [0, 1]


def test_stable_ticks_requires_consecutive_holds():
    fired = []
    et = EdgeTrigger(fired.append, n_stable_ticks=3)
    assert et.fire_if_changed("A") is False  # 1st hold
    assert et.fire_if_changed("A") is False  # 2nd hold
    assert et.fire_if_changed("A") is True  # 3rd -> fires
    assert fired == ["A"]


def test_stable_ticks_swallows_flicker():
    fired = []
    et = EdgeTrigger(fired.append, n_stable_ticks=3)
    et.rebase("Rest")
    # Rapid Fist/Rest flicker never reaches 3 consecutive Fist -> nothing fires.
    for v in ["Fist", "Rest", "Fist", "Rest", "Fist", "Rest"]:
        et.fire_if_changed(v)
    assert fired == []
    # Once Fist holds for 3 in a row, it fires.
    et.fire_if_changed("Fist")
    et.fire_if_changed("Fist")
    assert et.fire_if_changed("Fist") is True
    assert fired == ["Fist"]


def test_stable_ticks_rebase_discards_pending_candidate():
    fired = []
    et = EdgeTrigger(fired.append, n_stable_ticks=3)
    et.fire_if_changed("A")  # candidate A, count 1
    et.fire_if_changed("A")  # count 2 (not yet fired)
    et.rebase("Z")  # discard the half-formed A candidate
    assert et.fire_if_changed("A") is False  # must re-earn from 1
    assert et.fire_if_changed("A") is False
    assert et.fire_if_changed("A") is True
    assert fired == ["A"]
    assert et.last == "A"


def test_stable_ticks_default_is_immediate():
    """n_stable_ticks=1 (default) keeps the original fire-on-first-change behaviour."""
    fired = []
    et = EdgeTrigger(fired.append)  # default n_stable_ticks=1
    assert et.fire_if_changed("A") is True
    assert fired == ["A"]


def test_stable_ticks_must_be_positive():
    with pytest.raises(ValueError, match="n_stable_ticks"):
        EdgeTrigger(lambda _v: None, n_stable_ticks=0)
