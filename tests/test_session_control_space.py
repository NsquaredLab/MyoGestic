"""A recording must carry enough to be interpreted years later.

Channel names alone do not say what a number *meant*: ``-1`` is a full excursion
for a signed DOF and out of range for a one-way one, and nothing recoverable
distinguishes "declared one-way" from "signed, but this operator never went
negative". Persisting the control space is what closes that gap — and reading a
target back **by name** is what stops a reordered configuration from silently
training on the wrong channel.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from myogestic.controls import load_control_map, read_control_space
from myogestic.session import Session, iter_aligned_windows, open_session_store
from myogestic.stream import StreamInfo

#: What a recording is made under: the user's aliases and the target controls they drove.
CONTROL_MAP = load_control_map(
    {
        "dofs": {
            "my_index": "vhi.prediction.index",
            "fist": [
                {"target": "vhi.prediction.thumb", "weight": 0.6},
                "vhi.prediction.middle",
            ],
        }
    }
)


def _record(tmp_path, *, names, control_space=None, n=40):
    """Write a two-stream session and return its folder."""
    session = Session(base_path=str(tmp_path))
    session.init_stream("emg", StreamInfo(n_channels=2, fs=100.0, dtype=np.float32))
    session.init_stream(
        "control", StreamInfo(n_channels=2, fs=100.0, dtype=np.float32, channel_names=names)
    )
    ts = np.arange(n, dtype=np.float64) / 100.0
    session.append("emg", np.ones((n, 2), dtype=np.float32), ts)
    control = np.stack([np.full(n, -0.5, np.float32), np.full(n, 0.25, np.float32)], axis=1)
    session.append("control", control, ts)
    session.add_label(0, timestamp=0.0)
    session.save_meta("test-app", class_names=["Rest"], control_space=control_space)
    session.close()
    return session.path


def test_control_space_round_trips(tmp_path):
    """What was recorded must rebuild the exact mapping it was recorded under."""
    path = _record(tmp_path, names=["my_index", "fist"],
                   control_space=CONTROL_MAP.as_control_space())
    meta = json.loads((path / "meta.json").read_text())
    assert meta["schema_version"] == 3
    rebuilt = read_control_space(meta["control_space"])
    assert rebuilt.as_control_space() == CONTROL_MAP.as_control_space()


def test_control_space_preserves_the_routing_and_its_weights(tmp_path):
    """What a channel name alone cannot carry: which target control it drove, and how hard.

    An archived number is meaningless without this. `fist` at 1.0 meant full flexion on
    middle *and* 0.6 on the thumb — recoverable only because the mapping was persisted.
    """
    path = _record(tmp_path, names=["my_index", "fist"],
                   control_space=CONTROL_MAP.as_control_space())
    rebuilt = read_control_space(json.loads((path / "meta.json").read_text())["control_space"])
    refs = {r.address: r.weight for r in rebuilt.bindings["fist"].targets}
    assert refs == {"vhi.prediction.thumb": 0.6, "vhi.prediction.middle": 1.0}
    assert rebuilt.bindings["my_index"].targets[0].address == "vhi.prediction.index"


def test_a_recording_says_which_control_space_format_it_used(tmp_path):
    """Legible rather than inferred — the reason the format is tagged."""
    from myogestic.controls import CONTROL_SPACE_FORMAT

    path = _record(tmp_path, names=["my_index", "fist"],
                   control_space=CONTROL_MAP.as_control_space())
    meta = json.loads((path / "meta.json").read_text())
    assert meta["control_space"]["format"] == CONTROL_SPACE_FORMAT


def test_control_space_is_optional(tmp_path):
    """Every existing caller omits it, and must keep working."""
    path = _record(tmp_path, names=None)
    meta = json.loads((path / "meta.json").read_text())
    assert "control_space" not in meta
    session = open_session_store(path)
    try:
        assert "control" in session.stores
    finally:
        session.close()


def test_older_archives_without_a_schema_version_still_load():
    """The committed fixtures predate versioning entirely."""
    for name in ("vhi_pose_moved", "vhi_pose_rest"):
        session = open_session_store(f"tests/fixtures/{name}.session.zip")
        try:
            assert session.get_continuous("vhi_control")[0].shape[1] == 9
        finally:
            session.close()


def test_aligned_windows_can_be_keyed_by_channel_name(tmp_path):
    """The index-free training path: select a target by name, not by position."""
    path = _record(tmp_path, names=["my_index", "fist"])
    windows = list(
        iter_aligned_windows([path], "emg", ["control"], 100, 100, with_names=True)
    )
    assert windows, "expected at least one window"
    _primary, aligned, _ts = windows[0]
    assert set(aligned["control"]) == {"my_index", "fist"}
    assert aligned["control"]["my_index"] == pytest.approx(-0.5)
    assert aligned["control"]["fist"] == pytest.approx(0.25)


def test_positional_aligned_windows_are_unchanged(tmp_path):
    """Default stays byte-for-byte what every current caller receives."""
    path = _record(tmp_path, names=["my_index", "fist"])
    windows = list(iter_aligned_windows([path], "emg", ["control"], 100, 100))
    _primary, aligned, _ts = windows[0]
    assert isinstance(aligned["control"], np.ndarray)
    assert aligned["control"].tolist() == pytest.approx([-0.5, 0.25])


def test_with_names_refuses_a_recording_that_has_none(tmp_path):
    """Better a named refusal than a positional guess dressed as a name."""
    path = _record(tmp_path, names=None)
    with pytest.raises(ValueError, match="has no channel names"):
        list(iter_aligned_windows([path], "emg", ["control"], 100, 100, with_names=True))


def test_with_names_refuses_metadata_that_does_not_match_the_data(tmp_path):
    """Three names for two channels means the metadata describes something else."""
    path = _record(tmp_path, names=["a.x", "b.y", "c.z"])
    with pytest.raises(ValueError, match="channel names but 2 channels"):
        list(iter_aligned_windows([path], "emg", ["control"], 100, 100, with_names=True))
