from __future__ import annotations

import numpy as np
import numpy.typing as npt
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.stream import StreamInfo


class LSLSource:
    """Pull samples from a Lab Streaming Layer outlet by name.

    The default real-time source for MyoGestic: name the outlet you want
    on your local LSL network, drop the source into a :class:`Stream`,
    and the framework's acquisition thread handles the rest. Uses
    `mne_lsl` under the hood.

    Parameters
    ----------
    stream_name
        LSL outlet name to subscribe to (e.g. ``"TestEMG1"``,
        ``"VHI_Control"``). Resolved by name only - channel layout and
        sample rate come from the outlet's own metadata.
    dtype
        Dtype the samples are stored as (one of
        :data:`~myogestic.stream.SUPPORTED_DTYPES`). Default ``"float32"``.
        Incoming samples are cast to this dtype, so a compact choice (e.g.
        ``"int16"``) halves ring-buffer and recording size. ``None`` keeps
        the outlet's **native** wire format (lossless for int amps).
        Note: the window passed to ``@pipeline.extract`` is always upcast
        to float32 regardless of this choice.

    Examples
    --------
    >>> from myogestic import Stream
    >>> from myogestic.sources import LSLSource
    >>> stream = Stream("emg", source=LSLSource("TestEMG1"),
    ...                 window_ms=1000)
    >>> # keep a 16-bit amp's native format to halve memory / disk:
    >>> raw = LSLSource("TestEMG1", dtype=None)

    The source is non-blocking: :meth:`read` pulls whatever is
    immediately available from the inlet and returns ``(None, None)``
    when the outlet has produced nothing new since the last call. The
    acquisition thread paces itself by waiting for the inlet to fill,
    so a fast spin loop is harmless.
    """

    def __init__(self, stream_name: str, dtype: npt.DTypeLike | None = "float32"):
        self._name = stream_name
        # None -> honour the outlet's native wire format (resolved in connect);
        # otherwise cast incoming samples to this dtype.
        self._requested_dtype = None if dtype is None else np.dtype(dtype)
        self._dtype = np.dtype(np.float32)  # resolved in connect()
        self._inlet: StreamInlet | None = None

    def connect(self) -> StreamInfo:
        """Resolve the outlet by name and open an inlet.

        Returns a :class:`StreamInfo` whose channel count and sample rate
        come from the outlet's metadata. ``dtype`` is the value requested
        at construction (default float32), or the outlet's **native** wire
        format when constructed with ``dtype=None``. Blocks up to 10 s
        waiting for the outlet to appear on the network.

        Raises
        ------
        RuntimeError
            if no outlet with ``stream_name`` is found.
            The error message lists every outlet that *is* currently
            advertised, to make typos and stream-name mismatches
            obvious.
        """
        streams = resolve_streams(timeout=10.0, name=self._name)
        if not streams:
            available = [s.name for s in resolve_streams(timeout=2.0)]
            raise RuntimeError(
                f"LSL stream '{self._name}' not found. Available streams: {available}"
            )
        info = streams[0]
        self._inlet = StreamInlet(info, max_buffered=10)
        # mne_lsl exposes the outlet's native wire dtype as info.dtype.
        native = np.dtype(info.dtype)
        self._dtype = self._requested_dtype if self._requested_dtype is not None else native
        return StreamInfo(n_channels=info.n_channels, fs=info.sfreq, dtype=self._dtype)

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Pull whatever samples are immediately available.

        Non-blocking. Returns ``(data, timestamps)`` where ``data`` is
        ``(n_samples, n_channels)`` in the configured ``dtype`` (default
        float32) and ``timestamps`` is a 1-D float64 array of LSL clock
        seconds. Returns ``(None, None)`` if the inlet hasn't been opened
        or no new samples are pending.
        """
        if self._inlet is None:
            return None, None
        data, timestamps = self._inlet.pull_chunk(timeout=0.0)
        if timestamps is None or len(timestamps) == 0:
            return None, None
        return (np.asarray(data, dtype=self._dtype), np.asarray(timestamps, dtype=np.float64)
        )

    def disconnect(self) -> None:
        """Close the inlet. Safe to call multiple times."""
        if self._inlet:
            self._inlet.close_stream()
            self._inlet = None

    def discover(self) -> list[dict[str, str]]:
        """Scan for available LSL streams on the network."""
        found = resolve_streams(timeout=2.0)
        return [
            {"name": s.name, "info": f"{s.n_channels}ch {s.sfreq:.0f}Hz {s.stype}"} for s in found
        ]

    def reconnect(self, target: str | None = None) -> StreamInfo:
        """Reconnect to the same or a different LSL stream."""
        self.disconnect()
        if target is not None:
            self._name = target
        return self.connect()
