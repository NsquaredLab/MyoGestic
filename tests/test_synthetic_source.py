"""`SyntheticSource`: what its live knobs actually do to the samples.

The knob under test is `direction`, which splits `activation` across an
agonist/antagonist pair so that a two-way gesture gives two *different* signals.
Without it "wrist down" and "wrist up" are the same waveform at the same
amplitude, no regressor can separate them, and a proportional-control example
cannot be demonstrated without hardware.

Chunks are read straight off the source rather than through a `Stream`, so
nothing here depends on a background thread's timing.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from myogestic.sources import SyntheticSource

#: Four chunks of 64 samples is a stable enough RMS while keeping the paced
#: `read()` to about an eighth of a second per source.
_CHUNKS = 4
_N = 8


def _read(source: SyntheticSource, chunks: int = _CHUNKS) -> np.ndarray:
    """Connect and concatenate ``chunks`` reads into one (samples, channels) block."""
    source.connect()
    return np.concatenate([source.read()[0] for _ in range(chunks)])


def _half_rms(data: np.ndarray) -> tuple[float, float]:
    """RMS of the first half of the channels, and of the second."""
    half = data.shape[1] // 2
    return (
        float(np.sqrt(np.mean(data[:, :half] ** 2))),
        float(np.sqrt(np.mean(data[:, half:] ** 2))),
    )


def test_direction_defaults_to_neutral():
    """Every app written before the knob existed builds the source without naming it."""
    assert SyntheticSource().direction == 0.0


@pytest.mark.parametrize("direction", [-1.0, 0.0, 1.0])
def test_direction_zero_is_exactly_the_old_behaviour(direction: float):
    """The formula as it stood before `direction`, against what the source now produces.

    `activation` is part of the reference because it predates `direction`; what is
    pinned is that steering is the *only* new term, and that at the default it
    contributes nothing. This is the compatibility guarantee, so the reference is
    written out here rather than imported: it has to keep meaning "what the source did
    before the knob existed" even if the source is rewritten. Seeding `numpy.random` makes
    the noise term reproducible, so the comparison is exact rather than
    statistical, over a single chunk so no assumption is needed about how the
    Gaussian stream splits across calls.

    Parametrised over all three positions to prove the reference *can* fail —
    only the neutral one is meant to match it.
    """
    fs, noise, hum, hum_hz, activation = 2048.0, 0.12, 0.35, 50.0, 0.7

    np.random.seed(20260808)
    source = SyntheticSource(_N, fs, noise=noise, hum=hum, hum_hz=hum_hz, activation=activation)
    source.direction = direction
    source.connect()
    got, _ = source.read()

    np.random.seed(20260808)
    t = np.arange(got.shape[0]) / fs
    want = (
        activation * np.sin(2 * np.pi * np.outer(t, 5.0 + np.arange(_N)))
        + hum * np.sin(2 * np.pi * hum_hz * t)[:, None]
        + noise * np.random.randn(*got.shape)
    ).astype(np.float32)

    if direction == 0.0:
        assert np.array_equal(got, want), "the default is no longer the old behaviour"
    else:
        assert not np.array_equal(got, want)


def test_direction_separates_the_channel_halves():
    """The whole point: the two halves' RMS swaps as direction sweeps -1 to +1."""
    rms = {d: _half_rms(_read(SyntheticSource(_N, direction=d))) for d in (-1.0, 0.0, 1.0)}
    down_first, down_second = rms[-1.0]
    rest_first, rest_second = rms[0.0]
    up_first, up_second = rms[1.0]

    # At rest the halves are indistinguishable — which is exactly why a signed
    # gesture needs the knob. Each channel carries its own sine, so allow slack.
    assert rest_first == pytest.approx(rest_second, rel=0.05)
    # Steering silences one half's sines, leaving it at noise plus hum only.
    assert down_first > 1.5 * down_second
    assert up_second > 1.5 * up_first
    # And the loud half is never louder than Activation alone would make it.
    assert down_first == pytest.approx(rest_first, rel=0.05)
    assert up_second == pytest.approx(rest_second, rel=0.05)


def test_the_half_contrast_is_monotonic_across_the_sweep():
    """Down / Rest / Up must be *ordered* in one feature, not merely different.

    A regressor fits the ordering, so two directions that separate without
    ordering would train happily and then predict nonsense in between.
    """
    contrast = []
    for direction in (-1.0, -0.5, 0.0, 0.5, 1.0):
        first, second = _half_rms(_read(SyntheticSource(_N, direction=direction)))
        contrast.append(second - first)
    assert all(b > a for a, b in itertools.pairwise(contrast)), contrast


def test_noise_and_hum_do_not_scale_with_direction():
    """An electrode picks both up regardless; scaling them is a free SNR cue.

    Measured with the sines off (``activation=0``), so what remains in the
    samples is the noise and the hum and nothing else.
    """
    rms = {
        d: float(np.sqrt(np.mean(_read(SyntheticSource(_N, activation=0.0, direction=d)) ** 2)))
        for d in (-1.0, 0.0, 1.0)
    }
    assert rms[-1.0] == pytest.approx(rms[0.0], rel=0.05)
    assert rms[1.0] == pytest.approx(rms[0.0], rel=0.05)


def test_direction_is_clamped_so_an_overshooting_model_stays_monotonic():
    """Past -1 an unclamped gain goes negative: the quiet half loud again, phase flipped."""
    beyond = _half_rms(_read(SyntheticSource(_N, direction=-4.0)))
    limit = _half_rms(_read(SyntheticSource(_N, direction=-1.0)))
    assert beyond == pytest.approx(limit, rel=0.05)


def test_direction_is_live():
    """It must be writable mid-stream, or it cannot cue a subject during a recording."""
    source = SyntheticSource(_N)
    source.connect()
    source.direction = 1.0
    first, second = _half_rms(np.concatenate([source.read()[0] for _ in range(_CHUNKS)]))
    assert second > 1.5 * first
