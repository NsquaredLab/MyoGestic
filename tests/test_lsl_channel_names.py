"""The wire carries channel names, so a control stream describes itself.

A positional stream forces every consumer to hardcode an index, which is how a
reordered configuration silently remaps channels instead of failing. These tests
run a real outlet-to-inlet loopback: publishing labels is only useful if they
survive the round trip, and asserting on the object we just constructed would
prove nothing.
"""

from __future__ import annotations

import numpy as np
import pytest

from myogestic.outputs import LSLOutlet
from myogestic.sources import LSLSource

from .conftest import build_controls

CONTROLS = build_controls({
            "index.flexion": "continuous",
            "thumb.flexion": "continuous",
            "wrist.pronation": "continuous",
        })


def _roundtrip(name: str, **kwargs) -> object:
    """Publish an outlet, resolve it with a real inlet, return the StreamInfo."""
    outlet = LSLOutlet(name, n_channels=3, hz=32, **kwargs)
    try:
        source = LSLSource(name)
        try:
            return source.connect()
        finally:
            source.disconnect()
    finally:
        outlet.stop()


def test_channel_labels_survive_the_wire():
    labels = CONTROLS.channel_labels()
    info = _roundtrip("MyoGesticTestNamed", channel_names=labels)
    assert info.channel_names == list(labels)
    assert info.n_channels == 3


def test_control_set_labels_are_the_wire_order():
    """The labels published are exactly the order `encode` produces."""
    assert CONTROLS.channel_labels() == (
        "index.flexion",
        "thumb.flexion",
        "wrist.pronation",
    )


def test_an_unlabelled_outlet_reports_no_names():
    """LSL fills unset labels with the channel index; those are not names.

    Reporting ``["0", "1", "2"]`` would make a positional stream look
    self-describing and let a caller resolve ``"0"`` as if it meant something.
    """
    info = _roundtrip("MyoGesticTestUnnamed")
    assert info.channel_names is None


def test_units_can_be_published_alongside_names():
    info = _roundtrip(
        "MyoGesticTestUnits",
        channel_names=CONTROLS.channel_labels(),
        channel_units=["normalized"] * 3,
    )
    assert info.channel_names == list(CONTROLS.channel_labels())


def test_a_wrong_length_label_list_is_refused_at_construction():
    """Better a readable error now than a mislabelled stream on the network."""
    with pytest.raises(ValueError, match="has 2 entries but n_channels is 3"):
        LSLOutlet("MyoGesticTestBadLabels", n_channels=3, channel_names=["a", "b"])
    with pytest.raises(ValueError, match="has 4 entries but n_channels is 3"):
        LSLOutlet("MyoGesticTestBadUnits", n_channels=3, channel_units=["x"] * 4)


def test_the_positional_constructor_still_works():
    """Every existing call site passes name/n_channels/hz positionally."""
    outlet = LSLOutlet("MyoGesticTestPositional", 3, 32)
    try:
        outlet.push(np.zeros(3, dtype=np.float32))
    finally:
        outlet.stop()
