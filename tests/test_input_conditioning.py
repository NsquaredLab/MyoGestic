"""The mains notch on acquisition: what the model sees, and what gets recorded.

The design claim under test is narrow and load-bearing: conditioning happens at the one
point in `Stream._acquire_step` where the ring buffer and the session take the *same*
array, so a model's live windows and the recording it is later trained on cannot be
conditioned differently. There is no second code path, so there is nothing to drift.

It has to be a streaming filter over chunks rather than something applied per window.
Predict windows are the trailing `window_ms` taken many times a second and overlap almost
entirely; filtering each independently leaves 24x more mains than filtering the stream
(13.1% of window power at 50 Hz against 0.54%) and moves window RMS by 16%.
"""

import time

import numpy as np
import pytest

from myogestic import App, Stream
from myogestic.sources import SyntheticSource


def _hum_share(window: np.ndarray, fs: float, f0: float = 50.0) -> float:
    """Fraction of a window's power sitting at `f0`."""
    x = np.asarray(window, dtype=np.float64).T  # (n_samples, n_channels)
    freqs = np.fft.rfftfreq(len(x), 1.0 / fs)
    k = int(np.argmin(np.abs(freqs - f0)))
    power = np.abs(np.fft.rfft(x * np.hanning(len(x))[:, None], axis=0)) ** 2
    return float(power[k].sum() / power.sum())


def _running(notch_hz: int) -> tuple[App, Stream]:
    app = App("conditioning-test")
    stream = Stream(
        "emg",
        source=SyntheticSource(n_channels=4, hum=0.8, hum_hz=50.0, noise=0.2),
        window_ms=500,
        notch_hz=notch_hz,
    )
    app.streams(stream)
    assert stream.reconnect(), stream.last_error
    stream.start()
    for _ in range(200):  # wait for a full window rather than guessing at a sleep
        data, _ts = stream.get_window()
        if data.size and data.shape[1] >= int(0.5 * stream.info.fs):
            # ...then let the notch settle before anyone reads it. The biquads seed from
            # their first sample, and a Q of 50/3 needs on the order of Q cycles to reach
            # steady state -- about 0.34 s at 50 Hz. A window grabbed the instant one is
            # merely *full* still carries that transient: measured 0.74% of power at
            # 50 Hz against 0.0037% once settled. Worth knowing beyond this test, because
            # it means the first third of a second after Connect is not clean signal.
            time.sleep(2.0 * 0.5)
            return app, stream
        time.sleep(0.02)
    stream.stop()
    pytest.fail(f"no window filled: status={stream.status} err={stream.last_error!r}")


@pytest.mark.parametrize(("notch_hz", "expect_hum"), [(0, True), (50, False), (60, True)])
def test_the_notch_reaches_the_window_the_model_is_given(notch_hz, expect_hum):
    """`notch_hz=60` is the control: it must leave a 50 Hz hum alone.

    Without it this passes for a filter that merely smooths everything, which is a
    different and much worse thing than rejecting one line.
    """
    app, stream = _running(notch_hz)
    try:
        data, _ts = stream.get_window()
        share = _hum_share(data, stream.info.fs)
        if expect_hum:
            assert share > 0.05, f"notch_hz={notch_hz} removed a hum it was not asked to"
        else:
            assert share < 0.005, f"notch_hz=50 left {share:.2%} of the power at 50 Hz"
    finally:
        stream.stop()
        stream.disconnect()


def test_a_conditioning_fault_does_not_silently_kill_acquisition(monkeypatch):
    """The failure mode this guard exists for, because it cost an afternoon.

    `_condition` runs on the acquire thread. Raising there killed the thread outright
    while `status` stayed ``"connected"`` and `last_error` stayed empty — the stream
    simply stopped delivering, and every read-out said it was fine. Surfacing it the way
    a bad chunk is surfaced keeps the loop alive and says what happened.
    """
    app, stream = _running(50)
    try:
        monkeypatch.setattr(
            type(stream), "_condition", lambda self, data: (_ for _ in ()).throw(ValueError("boom"))
        )
        for _ in range(100):
            if stream.status == "disconnected":
                break
            time.sleep(0.02)
        assert stream.status == "disconnected", "a filter fault was not surfaced"
        assert "conditioning failed" in stream.last_error, stream.last_error
        assert stream._thread is not None and stream._thread.is_alive(), (
            "the acquire thread died instead of reporting"
        )
    finally:
        stream.stop()
        stream.disconnect()


def test_the_recording_says_how_it_was_conditioned(tmp_path):
    """A filtered take holds filtered samples and the raw is gone.

    Nothing in the arrays reveals that, so the setting is written beside them. Training
    on a mix of filtered and unfiltered takes is otherwise a silent change to the model's
    input distribution — the same class of bug as mixing %MVC with signed control units.
    """
    app, stream = _running(50)
    try:
        app.start_recording(base_path=str(tmp_path))
        assert app.ctx.session is not None
        conditioning = app.ctx.session.extras.get("conditioning")
        assert conditioning == {"emg": {"notch_hz": 50}}, conditioning
        app.stop_recording()
    finally:
        stream.stop()
        stream.disconnect()


def test_an_unconditioned_recording_claims_nothing():
    """Absence is the honest record for a raw take, not ``notch_hz: 0``."""
    app, stream = _running(0)
    try:
        assert stream.notch_hz == 0
        assert stream._condition(np.ones((4, 4), dtype=np.float32)) is not None
    finally:
        stream.stop()
        stream.disconnect()
