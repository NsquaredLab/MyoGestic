from __future__ import annotations

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet

from myogestic.outputs import Output


class LSLOutlet(Output):
    """Publish a 1-D vector to a Lab Streaming Layer outlet.

    The dual of :class:`~myogestic.sources.LSLSource` - call ``.push(vec)``
    from inside ``@pipeline.predict``, and the framework's daemon output
    thread re-sends the latest pushed vector at the configured ``hz``.
    Channel count is locked at construction time so the LSL metadata
    matches what subscribers see.

    Args:
        name: Outlet name advertised on the LSL network. Typically the
            stream name that downstream tools (the Virtual Hand, a
            recorder, another MyoGestic app) resolve by.
        n_channels: Fixed channel count. Push vectors must have this
            length or :meth:`_send` raises ``ValueError`` instead of
            silently mis-sending.
        hz: Send rate of the daemon thread (Hz). Default 50. Push
            faster than ``hz`` is fine: latest-wins, the slot just gets
            overwritten.

    Example:
        >>> outlet = LSLOutlet("VHI_Hand", n_channels=9, hz=32)
        >>> @pipeline.predict
        ... def predict(model, features):
        ...     pose = model.compose_pose(features)
        ...     outlet.push(pose)
        ...     return {"pose": pose}
    """

    def __init__(self, name: str, n_channels: int, hz: float = 50):
        info = StreamInfo(name, "Control", n_channels, hz, "float32", "")
        self._outlet = StreamOutlet(info)
        self._n_channels = int(n_channels)
        super().__init__(hz=hz)

    def _send(self, data: np.ndarray) -> None:
        # Validate before push_sample - pylsl gives a cryptic error on
        # mismatch, and a silent push_chunk-then-noop is worse.
        if data.ndim != 1 or data.shape[0] != self._n_channels:
            raise ValueError(
                f"LSLOutlet expected 1-D vector of length {self._n_channels}, "
                f"got shape={data.shape}."
            )
        self._outlet.push_sample(data.astype(np.float32))  # type: ignore[arg-type]
