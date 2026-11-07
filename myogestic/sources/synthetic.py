"""A fake amplifier, for building and testing an app without hardware."""

from __future__ import annotations

import time
from typing import Literal

import numpy as np

from myogestic.stream import StreamInfo


class SyntheticSource:
    """In-process test signals or stochastic EMG, paced by the wall clock.

    A stand-in for a real amplifier while you build an app, demonstrate one, or
    run a test. It implements the same ``connect`` / ``read`` / ``disconnect``
    contract as `LSLSource` and the OTB sources, plus the optional
    ``discover`` / ``reconnect`` extensions, so every widget behaves exactly as
    it would against hardware.

    By default each channel carries one distinct sine (5 Hz, 6 Hz, …) with a shared mains
    hum on top, so the signal viewer's notch filter and per-channel controls
    have something real to act on. ``noise``, ``hum`` and ``hum_hz`` are public
    and can be changed while streaming.

    The default test signal is a fixed tone with white noise. Real EMG is
    stochastic and burst-modulated. Use the tone to test plotting and recording;
    a classifier trained on it learns channel frequencies.

    Opt into ``waveform="emg"`` for band-limited, heavy-tailed noise with local
    electrode correlation. Its spectrum and amplitude statistics approximate
    aggregates from 8-channel forearm bracelet recordings, without replaying
    samples. Use it for demonstrations; it does not model motor-unit physiology.
    Filter history persists across reads and reconnects.

    Timestamps use ``mne_lsl``'s ``local_clock()`` domain for current-time
    and sample-age readings.

    On desktop, ``read`` blocks until the next chunk is due, the way a real
    inlet's blocking pull does. In a browser it returns ``(None, None)`` until
    then, so the frame scheduler can keep drawing without a sleep.

    Parameters
    ----------
    n_channels
        Channel count the `StreamInfo` advertises.
    fs
        Sample rate in Hz.
    noise
        Gaussian noise standard deviation, against a sine of amplitude 1. Also
        a live attribute; assignments while streaming affect the next chunk.
    hum
        Mains-hum amplitude, common-mode across every channel. Live, like
        ``noise``. Turn it up to give the viewer's Notch control something
        obvious to remove.
    hum_hz
        Mains-hum frequency, 50 Hz in most of the world and 60 Hz in the
        Americas. Change it live to move the hum outside the viewer's Notch
        bandwidth.
    activation
        Carrier amplitude, normally 0..1. Live; background noise and hum remain
        present at zero activation.
    direction
        Live agonist/antagonist balance, clamped to -1..1. Negative values
        attenuate the second channel half; positive values attenuate the first.
    waveform : {"sine", "emg"}, default "sine"
        Carrier to generate. ``"sine"`` uses the default test signal
        and its random-number sequence. ``"emg"`` uses a stateful FIR
        filter, heavy-tailed innovations and circular neighbour mixing. Select
        at construction; the amplitude, balance, noise and hum knobs stay live.
    require_target
        When ``True``, ``connect()`` raises until ``reconnect()`` selects
        a target. Use this to test a disconnected stream's Scan → Connect
        flow. The default ``False`` permits immediate connection.

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
        waveform: Literal["sine", "emg"] = "sine",
        require_target: bool = False,
    ) -> None:
        if waveform not in ("sine", "emg"):
            raise ValueError("waveform must be 'sine' or 'emg'")
        self._waveform = waveform
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
        #: How hard the imaginary muscle is working, 0..1, scaling the carrier amplitude.
        #: Live, like `noise`. Defaults to 1. Vary it between gestures to create distinct
        #: synthetic training signals.
        self.activation = activation
        #: Which way the imaginary wrist is going, -1..+1, splitting `activation`
        #: between the first half of the channels and the second — an agonist /
        #: antagonist pair. Live, like `noise`. At -1 only the first half carries the
        #: sines; at +1 only the second does. At the default 0 both do. Use it to produce
        #: distinct RMS and MAV for "down" and "up" in a proportional-control demo.
        self.direction = direction
        self._target: str | None = None if require_target else "Synthetic EMG"
        self._pos = 0
        self._next_tick: float | None = None
        if waveform == "emg":
            self._init_emg()

    def _init_emg(self) -> None:
        """Build a short frequency-sampled FIR once, using only aggregate constants."""
        # Active-take median spectrum from 8-channel forearm bracelet recordings:
        # 65 Hz peak, 80 Hz median, 173 Hz 90%-power roll-off, after 20–450 Hz
        # band-pass and harmonic notches. Smooth over the notch gaps rather than
        # baking a particular mains frequency into the carrier.
        hz = [0, 15, 20, 30, 40, 60, 70, 80, 100, 120, 150, 180, 220, 280, 350, 450, 500]
        power = [
            0,
            0,
            0.08,
            0.62,
            0.79,
            0.95,
            1,
            0.87,
            0.68,
            0.55,
            0.18,
            0.18,
            0.09,
            0.04,
            0.004,
            0,
            0,
        ]
        taps = 2 * int(self._fs * 0.064) + 1
        taps = max(taps, 33)
        design_size = 1 << (4 * taps - 1).bit_length()
        magnitude = np.sqrt(np.interp(np.fft.rfftfreq(design_size, 1 / self._fs), hz, power))
        impulse = np.fft.fftshift(np.fft.irfft(magnitude, n=design_size))
        centre, half = design_size // 2, taps // 2
        self._emg_fir = impulse[centre - half : centre + half + 1] * np.hanning(taps)
        # Arbitrary display units: with the playground's noise=.05 and
        # activation=.8, match the paired Rest/Fist RMS ratio (median .101).
        self._emg_fir *= 0.5 / np.linalg.norm(self._emg_fir)
        concentration = np.sum(self._emg_fir**4) / np.sum(self._emg_fir**2) ** 2
        spatial = (1 + 0.38**4) / (1 + 0.38**2) ** 2 if self._n > 1 else 1.0
        # FIR averaging reduces excess kurtosis by sum(h**4)/sum(h**2)**2;
        # compensate when fs changes so the texture stays equally bursty.
        # A raw kurtosis of 4.8 gives about 4.32 after the calibration band's
        # harmonic notches and the additive background noise.
        self._emg_sigma = 0.5 * np.sqrt(np.log1p((4.8 - 3) / (3 * concentration * spatial)))
        self._emg_history = np.zeros((taps - 1, self._n))
        self._emg_fft_size = 0

    def _emg_carrier(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Return continuous filtered innovations and independent background noise."""
        # Draw per sample, not per process, so changing chunk size preserves the
        # random stream. Lognormal scale gives short stochastic bursts; after
        # filtering its Pearson kurtosis approximates the recorded median 4.32.
        random = np.random.randn(n, 3 * self._n)
        sigma = self._emg_sigma
        carrier = random[:, : self._n] * np.exp(sigma * random[:, self._n : 2 * self._n] - sigma**2)
        if self._n > 1:
            # a/(1+a²) ≈ .332 at a=.38: correlate adjacent electrodes only,
            # including the bracelet's last/first pair, independently of hum.
            carrier = (carrier + 0.38 * np.roll(carrier, 1, axis=1)) / np.sqrt(1 + 0.38**2)
        history = len(self._emg_history)
        block = np.concatenate((self._emg_history, carrier))
        fft_size = 1 << (len(block) - 1).bit_length()
        if fft_size != self._emg_fft_size:
            self._emg_transfer = np.fft.rfft(self._emg_fir, n=fft_size)[:, None]
            self._emg_fft_size = fft_size
        # Overlap-save: the history-length prefix contains circular aliasing;
        # every returned sample is an ordinary causal FIR output.
        filtered = np.fft.irfft(
            np.fft.rfft(block, n=fft_size, axis=0) * self._emg_transfer,
            n=fft_size,
            axis=0,
        )[history : history + n]
        self._emg_history = block[-history:].copy()
        return filtered, random[:, 2 * self._n :]

    # -- Source protocol ------------------------------------------------

    def connect(self) -> StreamInfo:
        """Start generating, and report the geometry that was asked for."""
        if self._target is None:
            raise ConnectionError("No device selected — Scan, then Connect.")
        from mne_lsl.lsl import local_clock

        self._next_tick = local_clock()
        return StreamInfo(n_channels=self._n, fs=self._fs, dtype=np.dtype("float32"))

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Return the next chunk; in a browser, every chunk that is due, or no data yet."""
        from mne_lsl.lsl import local_clock

        from myogestic._browser import IS_BROWSER

        # Block until the next chunk is due, so the acquire thread paces to
        # `fs` instead of spinning and squashing thousands of chunks onto one
        # x-position. Mirrors a real LSL inlet's blocking pull_chunk.
        assert self._next_tick is not None
        now = local_clock()
        chunks = 1
        if IS_BROWSER:
            # The frame loop calls this once per frame, so a slow frame must not slow
            # the signal: hand out every chunk that is due. After a long stall (a
            # hidden tab) drop all but one second of backlog and keep the clock.
            chunks = int((now - self._next_tick) * self._fs // self._CHUNK)
            if chunks < 1:
                return None, None
            cap = max(1, int(self._fs // self._CHUNK))
            if chunks > cap:
                self._next_tick = now - cap * self._CHUNK / self._fs
                chunks = cap
        target = self._next_tick + chunks * self._CHUNK / self._fs
        if not IS_BROWSER and target > now:
            time.sleep(target - now)
        self._next_tick = target

        n = self._CHUNK * chunks
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
        # steering exceeds what Activation alone gives. At 0 both gains are 1.0.
        gains = np.full(self._n, level, dtype=np.float64)
        half = self._n // 2
        gains[:half] *= 1.0 - max(direction, 0.0)
        gains[half:] *= 1.0 + min(direction, 0.0)
        # `activation` and `direction` scale the sines only. Noise and mains hum are
        # what the electrode picks up whether or not the muscle is working, so scaling
        # them too would hand a classifier a clean signal-to-noise cue that no real
        # recording has.
        if self._waveform == "emg":
            carrier, background = self._emg_carrier(n)
            data = (gains * carrier + hum + noise * background).astype(np.float32)
        else:
            data = (
                gains * np.sin(2 * np.pi * np.outer(t, freqs))
                + hum
                + noise * np.random.randn(n, self._n)
            ).astype(np.float32)
        # Chunk of `n` samples ending at the wall clock we just paced to.
        ts = (target + (np.arange(n) - (n - 1)) / self._fs).astype(np.float64)
        return data, ts

    def disconnect(self) -> None:
        """Release no resources; the generator holds no handle."""

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
