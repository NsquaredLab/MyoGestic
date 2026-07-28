"""Read legacy VHI pose recordings as canonical control values.

The legacy Virtual Hand Interface consumed a 9-float pose vector whose meaning
lived nowhere: the gRPC contract carries no channel semantics, and MyoGestic's own
docs and examples disagreed about several channels. The mapping below was read out
of the VHI source, where the two consumers
(``PredictedHandSkeleton``/``ControlHandSkeleton``) index the sample they receive:

===  ====================================================  ======================
ch   what VHI does with it                                 canonical name
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

- There are **no wrist channels**. Channels 6-8 are dead on both ends, which is why
  they are exactly ``0.0`` in every reference recording.
- The **positive half renders**. VHI multiplies the sample by a per-bone gain with
  no clamping, and the flexion gains are negative, so legacy ``-1`` is flexion and
  ``+1`` simply rotates the other way. The positive half is missing from the
  reference recordings because the operator never extended, **not** because VHI
  cannot render it. Nothing here may treat its absence as a limit.

This module exists for migration only. It is deliberately a reader: the canonical
standard does not know these channels exist, and nothing in it should learn.
"""

from __future__ import annotations

import numpy as np

#: Canonical names for the six legacy pose channels VHI actually consumed, in wire
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
    """Legacy 9-channel pose samples as canonical DOF values in ``[-1, 1]``.

    A single negation, because canonical ``+1`` is the direction a name denotes and
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
    values = np.clip(-arr[..., : len(LEGACY_POSE_DOFS)], -1.0, 1.0)
    return {name: values[..., i] for i, name in enumerate(LEGACY_POSE_DOFS)}


def encode_pose(values: dict[str, float]) -> np.ndarray:
    """Canonical DOF values as a legacy 9-channel pose frame.

    The inverse of `decode_pose`, for driving an unmodified VHI build during
    migration. Names absent from ``values`` are sent at rest, and channels 6-8 are
    zero because nothing reads them.

    Exists so the canonical layer can be exercised end to end against the old
    binary before anything changes on the VHI side — its upgrade path is deletion,
    not generalisation.

    Examples
    --------
    >>> from myogestic.vhi.legacy import encode_pose
    >>> encode_pose({"index.flexion": 1.0}).tolist()
    [0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    """
    frame = np.zeros(LEGACY_POSE_WIDTH, dtype=np.float32)
    for i, name in enumerate(LEGACY_POSE_DOFS):
        v = values.get(name)
        if v is None:
            continue
        frame[i] = -float(np.clip(v, -1.0, 1.0))
    return frame
