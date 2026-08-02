"""Regression-lock what VHI's recorded ``vhi_control`` archives actually contain.

The 9-channel layout is undocumented on the wire: the proto carries no channel semantics,
and MyoGestic's own docs and examples once disagreed about what several channels mean. The
only authority is what VHI itself recorded, so two archives are committed here as fixtures
and their properties pinned.

Provenance: both are real recorded sessions with the subject EMG stream **removed** — only
VHI's own ``vhi_control`` output, its timestamps and metadata remain. They are the smallest
archive of each kind out of the 31 that carry a ``vhi_control`` stream.

Both have been converted to the control standard by
`myogestic.tools.migrate_vhi_sessions`, along with every other archived session. They were
recorded in VHI's old units, where a fist read ``-1`` on the flexion channels; the target
was publishing the opposite of the stream it was meant to be compared against. That is fixed
at both ends and the recordings were migrated once, so there is a single convention on disk
and nothing reads a sign at runtime. These assertions are what say the migration landed.
"""

from __future__ import annotations

import json
import pathlib
import zipfile

import numpy as np
import pytest

from myogestic.session import open_session_store
from myogestic.vhi.pose import POSE_DOFS, split_pose

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
MOVED = FIXTURES / "vhi_pose_moved.session.zip"
RESTED = FIXTURES / "vhi_pose_rest.session.zip"


def _pose(path: pathlib.Path) -> np.ndarray:
    """The recorded `vhi_control` frames, read through the real session loader."""
    session = open_session_store(path)
    try:
        data, _ts = session.get_continuous("vhi_control")
        return np.asarray(data)
    finally:
        session.close()


def _flexed(path: pathlib.Path) -> np.ndarray:
    """The most-flexed frame in an archive."""
    pose = _pose(path)
    return pose[int(np.argmax(pose[:, 0]))]


def test_fixtures_carry_no_subject_signal():
    """Only VHI's own output ships in the repo — the EMG stream was stripped."""
    for path in (MOVED, RESTED):
        session = open_session_store(path)
        try:
            assert sorted(session.stores) == ["vhi_control"]
        finally:
            session.close()


def test_pose_is_nine_channels():
    assert _pose(MOVED).shape[1] == 9
    assert _pose(RESTED).shape[1] == 9


def test_the_fixtures_declare_the_standard_convention():
    """The stamp is what stops a reader from having to guess, so it is not optional."""
    for path in (MOVED, RESTED):
        meta = json.loads(zipfile.ZipFile(path).read("meta.json"))
        assert meta.get("pose_convention") == "standard", path.name


def test_a_recorded_fist_is_standard_plus_one():
    """The claim the whole direction fix rests on, read off real recorded data.

    A fist flexes every digit — ``+1`` — and brings the thumb *across* them, which is
    adduction and therefore ``-1`` on channel 1. These archives read ``-1`` on all six
    before the migration: VHI's ground-truth stream was publishing the opposite of the
    prediction stream, so every model trained on it needed its weights flipped by hand.
    """
    assert _flexed(MOVED) == pytest.approx([1.0, -1.0] + [1.0] * 4 + [0.0] * 3, abs=1e-6)


def test_only_the_flexion_half_was_ever_recorded():
    """The operator only ever flexed, so nothing goes negative but the adducted thumb.

    A property of the corpus, not of VHI — the target is linear across the full signed
    domain, so extension moves. Nothing may treat this as a limit.
    """
    pose = _pose(MOVED)
    flexion = np.delete(pose, 1, axis=1)  # channel 1 is adduction in a fist, so negative
    assert flexion.min() == pytest.approx(0.0, abs=1e-6)
    assert flexion.max() == pytest.approx(1.0, abs=1e-6)


def test_the_corpus_is_rank_one():
    """Channels 0-5 move together: the recorded "5-DOF" data holds one DOF.

    ``<= 1`` and not ``== 1`` because an all-zero rest archive is rank 0, and both
    kinds are committed here.
    """
    assert np.linalg.matrix_rank(_pose(MOVED)) <= 1
    assert np.linalg.matrix_rank(_pose(RESTED)) == 0


def test_the_other_digits_track_the_thumb_up_to_the_adduction_sign():
    """The rank-1 collapse is exact to float32, so no per-finger data exists."""
    pose = _pose(MOVED)
    moved = pose[pose[:, 0] > 0.5]
    assert moved.size, "fixture must contain flexed frames"
    assert np.abs(moved[:, 2:6] - moved[:, 0:1]).max() < 1e-6
    assert np.abs(moved[:, 1] + moved[:, 0]).max() < 1e-6


def test_the_wrist_channels_are_empty_in_the_archive():
    """The old target hardcoded them to zero rather than reading the wrist it animated.

    A fact about the corpus, and only that: VHI fills all three now, so a session recorded
    after 2026-07-31 carries real wrist kinematics.
    """
    for path in (MOVED, RESTED):
        assert np.abs(_pose(path)[:, 6:]).max() == 0.0


def test_rest_archive_is_all_zero():
    """A rest frame is zeros, which is what makes 0.0 the neutral value."""
    assert np.count_nonzero(_pose(RESTED)) == 0


# --- the layout ---------------------------------------------------------------


def test_split_pose_names_every_channel():
    named = split_pose(_pose(MOVED))
    assert tuple(named) == POSE_DOFS
    assert len(named) == 9


def test_split_pose_passes_values_through_untouched():
    """A relabelling, not a conversion. There is no second convention to convert from."""
    pose = _pose(MOVED)
    named = split_pose(pose)
    for i, name in enumerate(POSE_DOFS):
        assert named[name] == pytest.approx(pose[:, i], abs=0.0), name


@pytest.mark.parametrize("width", [1, 5, 6, 8, 10])
def test_a_frame_of_the_wrong_width_is_refused(width):
    """Guessing which channels are missing would be worse than refusing."""
    with pytest.raises(ValueError, match="9 channels wide"):
        split_pose(np.zeros(width, dtype=np.float32))
