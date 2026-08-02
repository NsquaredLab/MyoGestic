"""The channel layout of VHI's recorded ``vhi_control`` pose.

A recorded session carries VHI's ground-truth hand as a 9-float vector, and the wire says
nothing about what the nine mean — the gRPC contract carries no channel semantics, and
MyoGestic's own docs and examples once disagreed about several of them. The mapping below
was read out of the VHI source, where both skeletons index the sample they receive.

===  ====================================================  ======================
ch   what VHI does with it                                 name
===  ====================================================  ======================
0    thumb flexion — bones 1/2/3 X axis                    ``thumb.flexion``
1    thumb abduction — bones 1/2/3 Z axis                  ``thumb.abduction``
2    index flexion — bones 4, 5, 6                         ``index.flexion``
3    middle flexion — bones 7, 8, 9                        ``middle.flexion``
4    ring flexion — bones 10, 11, 12                       ``ring.flexion``
5    little flexion — bones 13, 14, 15                     ``little.flexion``
6-8  wrist flexion, abduction, rotation — bone 0           ``wrist.*``
===  ====================================================  ======================

**The values are control-standard**: ``+1`` is the direction the name denotes, ``0`` is rest.
There is no second convention and no decoding step. There used to be: VHI's ground-truth
outlet published VHI's own rig units, in which a fist read ``-1`` on the flexion
channels — the opposite of the prediction stream it existed to be compared against — and this
module was a bridge that negated them. Both ends speak the standard now, and recordings made
before that were converted once by `myogestic.tools.migrate_vhi_sessions`, which stamps
``pose_convention`` into the session's metadata. A session without that stamp has not been
converted; convert it rather than teaching a reader to branch.

Channels 6-8 are zero in every session recorded before 2026-07-31, because the old VHI build
hardcoded them rather than reading the wrist it was already animating. That is a fact about
the corpus, not about the format, and nothing here may treat it as a limit.

This is a *layout*, not an interface. The control standard does not know these channels exist
and nothing in it should learn: a live target is asked where its controls are
(`myogestic.remote.RemoteTarget` does exactly that), and only recorded data needs a table.
"""

from __future__ import annotations

import numpy as np

#: Names for the nine recorded pose channels, in wire order.
POSE_DOFS: tuple[str, ...] = (
    "thumb.flexion",
    "thumb.abduction",
    "index.flexion",
    "middle.flexion",
    "ring.flexion",
    "little.flexion",
    "wrist.flexion",
    "wrist.abduction",
    "wrist.rotation",
)

#: Target address -> the pose channel that carries it.
#:
#: Both the short and explicit axis forms appear because a configuration may use either.
ADDRESS_CHANNELS: dict[str, int] = {
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
    "vhi.prediction.wrist.flexion": 6,
    "vhi.prediction.wrist.abduction": 7,
    "vhi.prediction.wrist.rotation": 8,
}

#: Channels in a recorded pose frame.
POSE_WIDTH = 9


def split_pose(frame: np.ndarray) -> dict[str, np.ndarray]:
    """Name the channels of a recorded pose frame.

    A pure relabelling — the values are already control-standard and are passed through
    untouched. It is deliberately not a rescale: mapping an observed ``[0, 1]`` support onto
    ``[-1, 1]`` would invent an extension half that was never recorded *and* move rest away
    from ``0.0``, which on a limb controller is the one value that must not drift.

    Parameters
    ----------
    frame
        One frame ``(9,)`` or a block of them ``(n_samples, 9)``.

    Returns
    -------
    dict[str, numpy.ndarray]
        One entry per name in `POSE_DOFS`, shaped like the input minus its channel axis.

    Raises
    ------
    ValueError
        If ``frame`` is not 9 channels wide — a narrower frame is not a VHI pose and
        guessing which channels are missing would be worse than refusing.

    Examples
    --------
    >>> import numpy as np
    >>> from myogestic.vhi.pose import split_pose
    >>> fist = np.array([1, -1, 1, 1, 1, 1, 0, 0, 0], dtype=np.float32)
    >>> split_pose(fist)["index.flexion"].tolist()
    1.0
    """
    arr = np.asarray(frame, dtype=np.float32)
    if arr.shape[-1] != POSE_WIDTH:
        raise ValueError(
            f"a VHI pose frame is {POSE_WIDTH} channels wide, got {arr.shape[-1]}."
        )
    return {name: arr[..., i] for i, name in enumerate(POSE_DOFS)}
