"""A fake amplifier, for building and testing an app without hardware."""

from __future__ import annotations

import time

import numpy as np

from myogestic.stream import StreamInfo


class SyntheticSource:
    """In-process synthetic EMG — sine waves plus noise, paced by the wall clock.

    A stand-in for a real amplifier while you build an app, demonstrate one, or
    run a test. It implements the same ``connect`` / ``read`` / ``disconnect``
    contract as `LSLSource` and the OTB sources, plus the optional
    ``discover`` / ``reconnect`` extensions, so every widget behaves exactly as
    it would against hardware.

    Each channel carries one distinct sine (5 Hz, 6 Hz, …) with a shared mains
    hum on top, so the signal viewer's notch filter and per-channel controls
    have something real to act on. ``noise``, ``hum`` and ``hum_hz`` are public
    and can be changed **while streaming**.

    This is a test signal, not a model of EMG: real EMG is a stochastic,
    burst-modulated process, and this is a fixed tone with white noise on it. It
    exercises the plot, the filters, the scaling and the recording path
    faithfully; a classifier trained on it learns which frequency a channel is.

    Timestamps come from the ``mne_lsl`` ``local_clock()`` domain rather than a
    relative counter, so "now" and last-sample age read correctly.

    ``read`` blocks until the next chunk is due, the way a real inlet's blocking
    pull does. Without that the acquire thread spins and squashes thousands of
    chunks onto one x-position.

    Parameters
    ----------
    n_channels
        Channel count the `StreamInfo` advertises.
    fs
        Sample rate in Hz.
    noise
        Gaussian noise standard deviation, against a sine of amplitude 1. Also
        a live attribute — assign to it while streaming and the next chunk
        follows, no reconnect.
    hum
        Mains-hum amplitude, common-mode across every channel. Live, like
        ``noise``. Turn it up to give the viewer's Notch control something
        obvious to remove.
    hum_hz
        Mains-hum frequency, 50 Hz in most of the world and 60 Hz in the
        Americas. Live — drag it away from whichever the viewer's Notch is set
        to and the hum comes back, which is the notch's bandwidth made visible.
    require_target
        When ``True`` the source starts with **no** target selected, so
        ``connect()`` raises until one is chosen via ``reconnect()``. That makes
        a fresh stream present as *disconnected*, which is what you want to
        exercise a Scan → Connect flow. When ``False`` (default) it connects
        immediately.

    Examples
    --------
    >>> from myogestic import Stream
    >>> from myogestic.sources import SyntheticSource
    >>> stream = Stream("emg", source=SyntheticSource(n_channels=8), window_ms=1000)
    >>> stream.reconnect()  # nothing attaches a stream on its own
    True
    """

    #: Samples per read; N / fs sets the per-chunk pacing (~31 ms at 2048 Hz).
    _CHUNK = 64

    def __init__(
        self,
        n_channels: int = 8,
        fs: float = 2048.0,
        *,
        noise: float = 0.12,
        hum: float = 0.35,
        hum_hz: float = 50.0,
        activation: float = 1.0,
        direction: float = 0.0,
        require_target: bool = False,
    ) -> None:
        self._n = n_channels
        self._fs = fs
        #: Gaussian noise standard deviation, against a sine of amplitude 1.
        #: Public and **live**: the acquire thread reads it once per chunk, so
        #: writing it from the UI thread changes the signal on the next chunk
        #: with no reconnect. A plain float assignment is atomic under the GIL,
        #: so no lock is needed.
        self.noise = noise
        #: Mains-hum amplitude, common-mode across every channel — the thing the
        #: viewer's Notch control removes. Live, like `noise`.
        self.hum = hum
        #: Mains-hum frequency. Live. Sweeping it off the notch's 50 or 60 Hz is
        #: how you see how narrow that filter actually is.
        self.hum_hz = hum_hz
        #: How hard the imaginary muscle is working, 0..1, scaling the sine amplitude.
        #: Live, like `noise`. Defaults to 1 so a source nobody touches is what it always
        #: was. It exists so a synthetic signal can carry a *state* worth classifying:
        #: with a fixed amplitude every gesture is the same waveform, so a model trained
        #: on it separates nothing and a demo of prediction proves nothing.
        self.activation = activation
        #: Which way the imaginary wrist is going, -1..+1, splitting `activation`
        #: between the first half of the channels and the second — an agonist /
        #: antagonist pair. Live, like `noise`. At -1 only the first half carries the
        #: sines, at +1 only the second, at 0 (the default) both do and the source is
        #: exactly what it was before this knob existed. Without it every direction of
        #: a bidirectional gesture has the same RMS and MAV, so no regressor can tell
        #: "down" from "up" and a proportional-control demo needs hardware.
        self.direction = direction
        self._target: str | None = None if require_target else "Synthetic EMG"
        self._pos = 0
        self._next_tick: float | None = None

    # -- Source protocol ------------------------------------------------

    def connect(self) -> StreamInfo:
        """Start generating, and report the geometry that was asked for."""
        if self._target is None:
            raise ConnectionError("No device selected — Scan, then Connect.")
        from mne_lsl.lsl import local_clock

        self._next_tick = local_clock()
        return StreamInfo(n_channels=self._n, fs=self._fs, dtype=np.dtype("float32"))

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Return the next chunk, blocking until it is due."""
        from mne_lsl.lsl import local_clock

        # Block until the next chunk is due, so the acquire thread paces to
        # `fs` instead of spinning and squashing thousands of chunks onto one
        # x-position. Mirrors a real LSL inlet's blocking pull_chunk.
        assert self._next_tick is not None
        target = self._next_tick + self._CHUNK / self._fs
        now = local_clock()
        if target > now:
            time.sleep(target - now)
        self._next_tick = target

        n = self._CHUNK
        t = (self._pos + np.arange(n)) / self._fs
        self._pos += n
        # One distinct sine (5..5+n_channels Hz) + noise per channel, plus a
        # shared mains hum on every channel so the viewer's Notch control has
        # something to remove.
        freqs = 5.0 + np.arange(self._n)
        # Read once per chunk so a mid-chunk write from the UI thread cannot
        # split one chunk across two amplitudes.
        noise, hum_amp, hum_hz = self.noise, self.hum, self.hum_hz
        level = self.activation
        # Clamped on read rather than on write, because whatever steers `direction` —
        # a slider, or a regressor that overshoots its training range — must not drive
        # a gain below zero, where the quiet half grows loud again with its phase
        # inverted and the mapping stops being monotonic.
        direction = min(max(self.direction, -1.0), 1.0)
        hum = hum_amp * np.sin(2 * np.pi * hum_hz * t)[:, None]
        # `direction` splits `activation` across an agonist/antagonist pair by
        # attenuating one half only, so the loud half stays at `activation` and no
        # steering exceeds what Activation alone gives — and at 0 both gains are
        # exactly 1.0, which is what makes the default bit-for-bit unchanged.
        gains = np.full(self._n, level, dtype=np.float64)
        half = self._n // 2
        gains[:half] *= 1.0 - max(direction, 0.0)
        gains[half:] *= 1.0 + min(direction, 0.0)
        # `activation` and `direction` scale the sines only. Noise and mains hum are
        # what the electrode picks up whether or not the muscle is working, so scaling
        # them too would hand a classifier a clean signal-to-noise cue that no real
        # recording has.
        data = (
            gains * np.sin(2 * np.pi * np.outer(t, freqs))
            + hum
            + noise * np.random.randn(n, self._n)
        ).astype(np.float32)
        # Chunk of `n` samples ending at the wall clock we just paced to.
        ts = (target + (np.arange(n) - (n - 1)) / self._fs).astype(np.float64)
        return data, ts

    def disconnect(self) -> None:
        """Nothing to release — the generator holds no handle."""

    # -- Optional extensions --------------------------------------------

    def discover(self) -> list[dict[str, str]]:
        """Report the single fake device, so Scan → Connect flows work."""
        return [{"name": "Synthetic EMG", "info": f"{self._n} ch · {self._fs:.0f} Hz"}]

    def reconnect(self, target: str | None = None) -> StreamInfo:
        """Reconnect, optionally selecting a discovered target first."""
        if target is not None:
            self._target = target
        return self.connect()


__all__ = ["SyntheticSource"]
