"""Regression-lock the legacy VHI pose evidence the migration bridge is built on.

The legacy 9-channel `vhi_control` layout is undocumented on the wire: the proto
carries no channel semantics, and MyoGestic's own docs and examples disagree about
what several channels mean. The only authority is what VHI itself recorded, so two
archives are committed here as fixtures and their properties pinned.

Provenance: both are real recorded sessions with the subject EMG stream **removed**
— only VHI's own `vhi_control` output, its timestamps and metadata remain. They are
the smallest archive of each kind out of the 31 that carry a `vhi_control` stream
(6904 samples in total, 24 of them rank>=1 and 7 all-zero).

What these numbers are for: the four hand-written pose tables in ``examples/``
declare channel 1 as ``0`` in a fist. VHI records it at exactly ``-1.0``. When the
bridge and those tables are corrected, these assertions are what prove which
reading was right.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pytest

from myogestic.session import open_session_store
from myogestic.vhi.legacy import LEGACY_POSE_DOFS, decode_pose

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


def test_only_the_negative_half_was_ever_recorded():
    """Max is 0.0, not +1: the operator only ever flexed.

    This is a property of the corpus, not of VHI — the renderer multiplies linearly
    with no clamp, so the positive half renders as extension. Nothing may treat this
    as evidence that VHI cannot render it.
    """
    pose = _pose(MOVED)
    assert pose.max() == pytest.approx(0.0, abs=1e-9)
    assert pose.min() == pytest.approx(-1.0, abs=1e-6)


def test_channel_one_is_minus_one_in_a_fist():
    """The fact that indicts four hand-written pose tables, which all say 0.

    Exact, not approximate: channel 1 is the one channel VHI records at precisely
    ``-1.0``, so an equality assertion is the strongest available statement.
    """
    pose = _pose(MOVED)
    most_flexed = pose[int(np.argmin(pose[:, 0]))]
    assert most_flexed[1] == -1.0


def test_the_flexed_frame_matches_the_recorded_values():
    pose = _pose(MOVED)
    most_flexed = pose[int(np.argmin(pose[:, 0]))]
    assert most_flexed == pytest.approx([-1.0] * 6 + [0.0] * 3, abs=1e-6)


def test_the_corpus_is_rank_one():
    """Channels 0-5 move together: the recorded "5-DOF" data holds one DOF.

    ``<= 1`` and not ``== 1`` because an all-zero rest archive is rank 0, and both
    kinds are committed here.
    """
    assert np.linalg.matrix_rank(_pose(MOVED)) <= 1
    assert np.linalg.matrix_rank(_pose(RESTED)) == 0


def test_channels_one_to_five_track_channel_zero():
    """The rank-1 collapse is exact to float32, so no per-finger data exists."""
    pose = _pose(MOVED)
    moved = pose[pose[:, 0] < -0.5]
    assert moved.size, "fixture must contain flexed frames"
    assert np.abs(moved[:, 1:6] - moved[:, 0:1]).max() < 1e-6


def test_channels_six_to_eight_are_dead():
    """No VHI consumer reads them: `PredictedHandSkeleton` stops at `currentData[5]`."""
    for path in (MOVED, RESTED):
        assert np.abs(_pose(path)[:, 6:]).max() == 0.0


def test_rest_archive_is_all_zero():
    """A rest frame is zeros, which is what makes 0.0 the canonical neutral value."""
    assert np.count_nonzero(_pose(RESTED)) == 0


# --- the bridge, read against the recordings above ----------------------------


def test_decode_names_only_the_channels_vhi_consumed():
    """Six DOFs, not nine: channels 6-8 are read by no VHI consumer."""
    decoded = decode_pose(_pose(MOVED))
    assert tuple(decoded) == LEGACY_POSE_DOFS
    assert len(decoded) == 6


def test_decode_is_a_single_negation():
    """Not a rescale: rescaling would invent an extension half and move rest."""
    pose = _pose(MOVED)
    decoded = decode_pose(pose)
    for i, name in enumerate(LEGACY_POSE_DOFS):
        assert decoded[name] == pytest.approx(-pose[:, i], abs=1e-6)


def test_decoded_values_stay_inside_the_canonical_domain():
    decoded = decode_pose(_pose(MOVED))
    for values in decoded.values():
        assert values.min() >= -1.0
        assert values.max() <= 1.0


def test_the_recorded_corpus_only_reaches_the_positive_half():
    """The operator only flexed, so canonical values never go negative.

    A property of the corpus, not of the target: VHI multiplies with no clamp, so
    the extension half renders fine. Nothing may read this as a limit.

    Note the archive itself is a sustained fist — every one of its samples has
    channels 0-5 at full flexion, so the ``0.0`` that ``pose.max()`` reports comes
    from the three dead channels rather than from any rest frame.
    """
    stacked = np.stack(list(decode_pose(_pose(MOVED)).values()))
    assert stacked.min() >= 0.0, "a negative value would mean recorded extension"
    assert stacked.max() == pytest.approx(1.0, abs=1e-6)


def test_thumb_abduction_decodes_to_full_scale_in_a_fist():
    """Channel 1 is exactly -1.0 recorded, so it decodes to exactly +1.0."""
    pose = _pose(MOVED)
    decoded = decode_pose(pose[int(np.argmin(pose[:, 0]))])
    assert float(decoded["thumb.abduction"]) == 1.0


def test_all_six_dofs_are_identical_because_the_corpus_is_rank_one():
    pose = _pose(MOVED)
    decoded = decode_pose(pose[pose[:, 0] < -0.5])
    reference = decoded["thumb.flexion"]
    for name, values in decoded.items():
        assert values == pytest.approx(reference, abs=1e-6), name


def test_rest_frames_decode_to_canonical_rest():
    for values in decode_pose(_pose(RESTED)).values():
        assert np.count_nonzero(values) == 0


@pytest.mark.parametrize("width", [1, 5, 6, 8, 10])
def test_a_frame_of_the_wrong_width_is_refused(width):
    """Guessing which channels are missing would be worse than refusing."""
    with pytest.raises(ValueError, match="9 channels wide"):
        decode_pose(np.zeros(width, dtype=np.float32))


# --- the whole loop, as the converted example runs it --------------------------
