import numpy as np
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

    Examples
    --------
    >>> from myogestic import Stream
    >>> from myogestic.sources import LSLSource
    >>> stream = Stream("emg", source=LSLSource("TestEMG1"),
    ...                 window_seconds=1.0)

    The source is non-blocking: :meth:`read` pulls whatever is
    immediately available from the inlet and returns ``(None, None)``
    when the outlet has produced nothing new since the last call. The
    acquisition thread paces itself by waiting for the inlet to fill,
    so a fast spin loop is harmless.
    """

    def __init__(self, stream_name: str):
        self._name = stream_name
        self._inlet: StreamInlet | None = None

    def connect(self) -> StreamInfo:
        """Resolve the outlet by name and open an inlet.

        Returns a :class:`StreamInfo` whose channel count, sample rate,
        and dtype come from the outlet's metadata. Blocks up to 10 s
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
        return StreamInfo(
            n_channels=info.n_channels,
            fs=info.sfreq,
            dtype=np.dtype(np.float32),
        )

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Pull whatever samples are immediately available.

        Non-blocking. Returns ``(data, timestamps)`` where ``data`` is
        ``(n_samples, n_channels)`` float32 and ``timestamps`` is a 1-D
        float64 array of LSL clock seconds. Returns ``(None, None)`` if
        the inlet hasn't been opened or no new samples are pending.
        """
        if self._inlet is None:
            return None, None
        data, timestamps = self._inlet.pull_chunk(timeout=0.0)
        if timestamps is None or len(timestamps) == 0:
            return None, None
        return (
            np.asarray(data, dtype=np.float32),
            np.asarray(timestamps, dtype=np.float64),
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
