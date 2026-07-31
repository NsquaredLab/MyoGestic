"""Read VHI's recorded pose as control values.

Not the v1 bridge — that is gone. This is the reader for VHI's **pose transport**,
which is a 9-float vector in the renderer's own units and is what a recorded session
contains. It survived the v2 cutover because it has to: the LSL outlets are the
renderer's, past sessions cannot be re-recorded, and a model trained on archived
kinematics needs its targets in the space they were captured in.

The channel meaning lives nowhere on the wire — the gRPC contract carries no channel
semantics, and MyoGestic's own docs and examples once disagreed about several
channels. The mapping below was read out of the VHI source, where the two consumers
(``PredictedHandSkeleton``/``ControlHandSkeleton``) index the sample they receive:

===  ====================================================  ======================
ch   what VHI does with it                                 name
===  ====================================================  ======================
0    thumb flexion — bones 1/2/3 X axis                    ``thumb.flexion``
1    thumb abduction — bones 1/2/3 Z axis                  ``thumb.abduction``
2    index flexion — bones 4, 5, 6                         ``index.flexion``
3    middle flexion — bones 7, 8, 9                        ``middle.flexion``
4    ring flexion — bones 10, 11, 12                       ``ring.flexion``
5    little flexion — bones 13, 14, 15                     ``little.flexion``
6-8  **never read by any consumer**                        — dropped
===  ====================================================  ======================

Two consequences worth stating, because both contradict what the old docs implied:

- **Nothing wrote channels 6-8**, which is why they are exactly ``0.0`` in every
  reference recording. That is a fact about the corpus, not about the renderer: VHI renders
  all three as the wrist now — flexion, abduction and rotation on bone 0, which parents
  every digit. A *recording* still has nothing in any of them, so this reader still drops
  all three; it decodes an archive, not a live stream.
- The **positive half renders**. The positive half is missing from the reference
  recordings because the operator never extended, **not** because VHI cannot render it.
  Nothing here may treat its absence as a limit.

**This reads an archive, and only an archive.** A live ``VHI_Control`` now publishes
standard values — a fist is ``+1`` on the flexion channels — and putting a current frame
through `decode_pose` would flip it into nonsense. The conventions are distinguishable on
the wire: VHI advertises ``pose_convention`` in the outlet's metadata and bumped its
``source_id`` to ``control_hand_002_standard``. A recording that carries neither predates
the change and is legacy; that is the assumption this module encodes.

It is deliberately a *reader*. The control standard does not know these channels
exist and nothing in it should learn: a live target is asked where its controls are
(`myogestic.vhi.VhiTarget` does exactly that), and only recorded data needs a table.

The module keeps its historical name so archived code and published references still
resolve; ``LEGACY_`` here means "the renderer's units", not "the removed v1 service".
"""

from __future__ import annotations

import numpy as np

#: Per-channel sign taking a legacy pose to the control standard.
#:
#: Not a blanket negation, which is what this was and what made it wrong on one channel.
#: The five flexion channels ran the other way in the renderer's units, so they flip. Thumb
#: abduction did not: the legacy readback divided by a *positive* Z gain while the fist's
#: thumb Z is negative, so a recorded fist already reads ``-1`` there — adduction, which is
#: what a fist does and what the standard calls ``-1``. Negating it turned every archived
#: fist into a thumb held away from the palm.
_TO_STANDARD = np.array([-1, 1, -1, -1, -1, -1], dtype=np.float32)

#: Names for the six legacy pose channels VHI actually consumed, in wire
#: order. Channels 6-8 are omitted because no consumer reads them.
LEGACY_POSE_DOFS: tuple[str, ...] = (
    "thumb.flexion",
    "thumb.abduction",
    "index.flexion",
    "middle.flexion",
    "ring.flexion",
    "little.flexion",
)

#: Target address -> the legacy pose channel that renders it.
#:
#: The legacy wire predates the manifest, so a pre-v2 VHI cannot be *asked* what it
#: exports — this is the same mapping, stated once, so a configuration written against
#: v2 addresses still drives an unmodified build. Both the short and explicit axis forms
#: appear because a configuration may use either.
LEGACY_ADDRESS_CHANNELS: dict[str, int] = {
    "vhi.prediction.thumb": 0,
    "vhi.prediction.thumb.flexion": 0,
    "vhi.prediction.thumb.abduction": 1,
    "vhi.prediction.index": 2,
    "vhi.prediction.index.flexion": 2,
    "vhi.prediction.middle": 3,
    "vhi.prediction.middle.flexion": 3,
    "vhi.prediction.ring": 4,
    "vhi.prediction.ring.flexion": 4,
    "vhi.prediction.little": 5,
    "vhi.prediction.little.flexion": 5,
}

#: Width of a legacy pose frame on the wire, including the three dead channels.
LEGACY_POSE_WIDTH = 9


def decode_pose(frame: np.ndarray) -> dict[str, np.ndarray]:
    """Legacy 9-channel pose samples as control DOF values in ``[-1, 1]``.

    A single negation, because a control ``+1`` is the direction a name denotes and
    VHI's flexion gains were negative. Exact and symmetric — deliberately **not** a
    rescale: mapping the observed ``[-1, 0]`` support onto ``[-1, 1]`` would invent
    an extension half that was never recorded *and* move rest away from ``0.0``,
    which on a limb controller is the one value that must not drift.

    Parameters
    ----------
    frame
        One frame ``(9,)`` or a block of them ``(n_samples, 9)``.

    Returns
    -------
    dict[str, numpy.ndarray]
        One entry per name in `LEGACY_POSE_DOFS`, shaped like the input minus its
        channel axis. Channels 6-8 are dropped.

    Raises
    ------
    ValueError
        If ``frame`` is not 9 channels wide — a narrower frame is not a legacy pose
        and guessing which channels are missing would be worse than refusing.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.vhi.legacy import decode_pose
    >>> fist = np.array([-1, -1, -1, -1, -1, -1, 0, 0, 0], dtype=np.float32)
    >>> decode_pose(fist)["index.flexion"].tolist()
    1.0
    """
    arr = np.asarray(frame, dtype=np.float32)
    if arr.shape[-1] != LEGACY_POSE_WIDTH:
        raise ValueError(
            f"a legacy VHI pose frame is {LEGACY_POSE_WIDTH} channels wide, got "
            f"{arr.shape[-1]}. Channels 6-8 are unused but still present on the wire."
        )
    values = np.clip(arr[..., : len(LEGACY_POSE_DOFS)] * _TO_STANDARD, -1.0, 1.0)
    return {name: values[..., i] for i, name in enumerate(LEGACY_POSE_DOFS)}
