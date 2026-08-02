"""Lab Streaming Layer output — publishes prediction vectors to an LSL outlet."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet

from myogestic.outputs.outlet import Outlet


class LSLOutlet(Outlet):
    """Publish a 1-D vector to a Lab Streaming Layer outlet.

    The dual of [`LSLSource`][myogestic.sources.LSLSource] - call ``.push(vec)``
    from inside ``@pipeline.predict``, and the framework's daemon output
    thread re-sends the latest pushed vector at the configured ``hz``.
    Channel count is locked at construction time so the LSL metadata
    matches what subscribers see.

    Parameters
    ----------
    name
        Outlet name advertised on the LSL network. Typically the
        stream name that downstream tools (the Virtual Hand, a
        recorder, another MyoGestic app) resolve by.
    n_channels
        Fixed channel count. Push vectors must have this
        length or `_send` raises ``ValueError`` instead of
        silently mis-sending.
    hz
        Send rate of the daemon thread (Hz). Default 50. Push
        faster than ``hz`` is fine: latest-wins, the slot just gets
        overwritten.
    channel_names
        Optional per-channel labels, published in the stream's description so a
        subscriber can resolve a channel **by name** instead of by position. Must
        be exactly ``n_channels`` long. Pass
        ``ControlSet.channel_labels()`` to make a control stream
        self-describing: a reordered configuration then renames channels rather
        than silently remapping them.
    channel_units
        Optional per-channel unit strings, same length rule. Control-standard
        DOFs are normalized, so ``"normalized"`` is the honest value for them.
    source_id
        Optional stable identifier for this outlet. LSL uses it to recognise the
        same logical stream across a restart, so a subscriber can reconnect
        instead of treating it as a new stream.

    Examples
    --------
    >>> outlet = LSLOutlet("VHI_Hand", n_channels=9, hz=32)
    >>> @pipeline.predict
    ... def predict(model, features):
    ...     pose = model.compose_pose(features)
    ...     outlet.push(pose)
    ...     return {"pose": pose}
    """

    def __init__(
        self,
        name: str,
        n_channels: int,
        hz: float = 50,
        *,
        channel_names: Sequence[str] | None = None,
        channel_units: Sequence[str] | None = None,
        source_id: str = "",
    ):
        info = StreamInfo(name, "Control", n_channels, hz, "float32", source_id)
        for label, values in (("channel_names", channel_names), ("channel_units", channel_units)):
            if values is None:
                continue
            if len(values) != n_channels:
                raise ValueError(
                    f"{label} has {len(values)} entries but n_channels is {n_channels}. "
                    f"Give one per channel, or omit it."
                )
        if channel_names is not None:
            info.set_channel_names(list(channel_names))
        if channel_units is not None:
            info.set_channel_units(list(channel_units))
        self._outlet = StreamOutlet(info)
        self._n_channels = int(n_channels)
        #: What this stream is published as. Readable so a log line, a test double or a
        #: debugger can say which stream an outlet is. `RemoteTarget` keys its outlets by
        #: address rather than reading this, so a substitute need not provide one.
        self.name = name
        super().__init__(hz=hz)

    def stop(self) -> None:
        """Stop the daemon thread and take the stream off the network.

        Overridden because the base class only stops the thread, and an `LSLOutlet`
        holds a resource: liblsl keeps a stream discoverable for as long as its
        `StreamOutlet` is alive, not for as long as anything is pushing to it. Dropping
        the reference and waiting for the collector is not enough either — the app
        raises the GC threshold at startup, so a stopped outlet can stay resolvable for
        a long time.

        That matters because a stopped-but-live outlet is not inert. It shares its
        ``source_id`` with the outlet that replaced it, so a consumer sees two equally
        valid producers of one stream and may resolve the dead one — reading a layout
        that no longer matches, silently, with every channel after the first change
        shifted by one.
        """
        super().stop()
        self._outlet = None

    def _send(self, data: np.ndarray) -> None:
        # Validate before push_sample - pylsl gives a cryptic error on
        # mismatch, and a silent push_chunk-then-noop is worse.
        if self._outlet is None:
            # `stop` released it while this tick was in flight. The send thread only
            # checks `_running` between ticks, so without this the last one raises on a
            # dropped outlet — a traceback for an orderly shutdown.
            return
        if data.ndim != 1 or data.shape[0] != self._n_channels:
            raise ValueError(
                f"LSLOutlet expected 1-D vector of length {self._n_channels}, "
                f"got shape={data.shape}."
            )
        self._outlet.push_sample(data.astype(np.float32))  # type: ignore
