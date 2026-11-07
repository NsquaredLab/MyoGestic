"""Opt-in EMG texture, calibrated to 8-channel forearm bracelet recordings.

Targets are medians over 49 active takes (spectrum, Pearson kurtosis and circular
neighbour correlation), and six paired Rest/Fist takes (RMS ratio). Both reference
and generated data use a fourth-order 20–450 Hz Butterworth band-pass and Q=30
50 Hz harmonic notches; discard one second at either edge. Welch uses one-second
Hann windows, 50% overlap; peak uses a 21 Hz boxcar. Normalize each channel's PSD
before averaging channels. Aggregate constants only, never recording excerpts.

Tolerances allow finite seeded realizations and variation across takes: peak
±15 Hz, spectral median ±12 Hz, 90% roll-off ±25 Hz, kurtosis ±0.6, neighbour
correlation ±0.06 and Rest/Fist RMS ratio ±0.025. This is a demo texture rather
than a physiological motor-unit simulation or a replay of any participant.
"""

import hashlib

import numpy as np
import pytest
from scipy import signal, stats

from myogestic.sources import SyntheticSource


@pytest.fixture(autouse=True)
def unpaced(monkeypatch):
    """Exercise acquisition without wall-clock waits or RNG leakage to other tests."""
    state = np.random.get_state()
    monkeypatch.setattr("myogestic._browser.IS_BROWSER", False)
    monkeypatch.setattr("time.sleep", lambda _: None)
    yield
    np.random.set_state(state)


def samples(source, count=32768, seed=20261107):
    np.random.seed(seed)
    source.connect()
    return np.concatenate([source.read()[0] for _ in range(count // source._CHUNK)])


def cleaned(x, fs):
    x = signal.sosfiltfilt(
        signal.butter(4, [20, 450], fs=fs, btype="bandpass", output="sos"), x, axis=0
    )
    for hz in range(50, 500, 50):
        b, a = signal.iirnotch(hz, 30, fs=fs)
        x = signal.filtfilt(b, a, x, axis=0)
    return x[int(fs) : -int(fs)]


def test_legacy_default_fixed_seed_is_bit_identical():
    x = samples(SyntheticSource(), count=512, seed=8675309)
    assert (
        hashlib.sha256(x.tobytes()).hexdigest()
        == "4ec36d30ab5c951c3e16bfda0ce2c3c531bccb8b93b9ee5be5e2e9d11af9dcc5"
    )


def test_explicit_sine_is_the_default():
    assert np.array_equal(
        samples(SyntheticSource(), 512), samples(SyntheticSource(waveform="sine"), 512)
    )


def test_unknown_waveform_is_rejected():
    with pytest.raises(ValueError, match="waveform"):
        SyntheticSource(waveform="ecg")


@pytest.mark.parametrize("fs", [1000, 1024, 2048])
def test_emg_matches_recorded_spectral_shape_and_distribution(fs):
    x = cleaned(
        samples(SyntheticSource(fs=fs, waveform="emg", noise=0.05, hum=0, activation=0.8)), fs
    )
    f, p = signal.welch(x, fs, nperseg=fs, axis=0)
    p = (p / np.trapezoid(p, f, axis=0)).mean(axis=1)
    peak = f[np.argmax(np.convolve(p, np.ones(21) / 21, mode="same"))]
    cdf = np.cumsum(p) / np.sum(p)
    assert peak == pytest.approx(65, abs=15)
    assert f[np.searchsorted(cdf, 0.5)] == pytest.approx(80, abs=12)
    assert f[np.searchsorted(cdf, 0.9)] == pytest.approx(173, abs=25)
    assert np.median(stats.kurtosis(x, axis=0, fisher=False)) == pytest.approx(4.319, abs=0.6)
    corr = np.corrcoef(x.T)
    assert np.mean([corr[i, (i + 1) % 8] for i in range(8)]) == pytest.approx(0.3316, abs=0.06)
    assert p[f < 20].sum() / p.sum() < 0.01
    assert p[f > 450].sum() / p.sum() < 0.01


def test_emg_rest_active_ratio_matches_paired_takes():
    rms = []
    for activation in (0, 0.8):
        x = cleaned(
            samples(
                SyntheticSource(fs=1000, waveform="emg", noise=0.05, hum=0, activation=activation)
            ),
            1000,
        )
        rms.append(np.median(np.sqrt(np.mean(x * x, axis=0))))
    assert rms[0] / rms[1] == pytest.approx(0.10143, abs=0.025)


def test_emg_filter_and_random_stream_are_continuous_across_chunk_sizes():
    expected = samples(SyntheticSource(fs=1024, waveform="emg"), count=4096)
    source = SyntheticSource(fs=1024, waveform="emg")
    source.connect()
    np.random.seed(20261107)
    blocks = []
    for size in (1, 17, 127, 3, 512, 64, 3372):
        source._CHUNK = size
        data, ts = source.read()
        assert data.dtype == np.float32 and ts.dtype == np.float64
        blocks.append(data)
    np.testing.assert_allclose(np.concatenate(blocks), expected, atol=3e-7, rtol=1e-6)


@pytest.mark.parametrize("n_channels", [1, 3, 8, 64])
def test_emg_channel_geometry(n_channels):
    x = samples(SyntheticSource(n_channels, waveform="emg"), 128)
    assert x.shape == (128, n_channels)
    assert np.isfinite(x).all()


def test_live_activation_and_direction_change_the_next_chunk():
    source = SyntheticSource(waveform="emg", noise=0, hum=0)
    source.connect()
    source.activation = 0
    for _ in range(4):  # warm the causal carrier filter while activation is zero
        assert not source.read()[0].any()
    source.activation = 0.8
    source.direction = -1
    x, _ = source.read()
    assert x[:, :4].std() > 0.1
    assert not x[:, 4:].any()
    source.direction = 1
    x, _ = source.read()
    assert not x[:, :4].any()
    assert x[:, 4:].std() > 0.1
    source.direction = 4
    np.random.seed(12)
    beyond = source.read()[0]
    # Direction clamps before applying gains; the muted half stays muted.
    assert not beyond[:, :4].any()


def test_live_noise_hum_and_hum_frequency_are_unscaled():
    source = SyntheticSource(fs=1000, waveform="emg", activation=0, noise=0, hum=0)
    source.connect()
    assert not source.read()[0].any()
    source.hum, source.hum_hz = 0.4, 60
    source.direction = -1
    pos = source._pos
    x, _ = source.read()
    want = 0.4 * np.sin(2 * np.pi * 60 * (pos + np.arange(64)) / 1000)
    np.testing.assert_allclose(x, np.broadcast_to(want[:, None], x.shape), atol=2e-8)
    source.hum_hz = 50
    pos = source._pos
    x, _ = source.read()
    want = 0.4 * np.sin(2 * np.pi * 50 * (pos + np.arange(64)) / 1000)
    np.testing.assert_allclose(x, np.broadcast_to(want[:, None], x.shape), atol=2e-8)
    source.hum = 0
    source.noise = 0.2
    x, _ = source.read()
    assert x.std() == pytest.approx(0.2, abs=0.025)
    source.noise = 0
    assert not source.read()[0].any()
