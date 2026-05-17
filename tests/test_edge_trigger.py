from myogestic.edge_trigger import EdgeTrigger


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
