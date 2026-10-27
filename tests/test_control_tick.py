"""The output clock stays paced, single-flight and independent of model input."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from myogestic.controls import ControlTicker


@pytest.mark.parametrize("hz", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_output_rate_must_be_finite_and_positive(hz):
    with pytest.raises(ValueError, match="hz"):
        ControlTicker(hz)


def test_not_due_frames_are_skipped_and_gaps_do_not_catch_up():
    ticker, sent = ControlTicker(20), []
    for now in (1.0, 1.01, 1.06, 6.0, 6.001, 6.06):
        result = ticker.run(lambda stamp: sent.append(stamp) or "sent", now=now)
        assert result == ("sent" if now in (1.0, 1.06, 6.0, 6.06) else None)
    assert sent == [1.0, 1.06, 6.0, 6.06]


def test_immediate_delivery_defers_the_next_paced_frame():
    ticker, sent = ControlTicker(20), []
    ticker.run(sent.append, now=1.0)
    ticker.run(sent.append, now=1.01, immediate=True)
    assert ticker.run(sent.append, now=1.05) is None
    ticker.run(sent.append, now=1.07)
    assert sent == [1.0, 1.01, 1.07]


@pytest.mark.parametrize("immediate", [False, True])
def test_older_timestamp_is_ignored_even_when_immediate(immediate):
    ticker, sent = ControlTicker(20), []
    ticker.run(sent.append, now=2.0)
    assert ticker.run(sent.append, now=1.0, immediate=immediate) is None
    ticker.run(sent.append, now=2.01)
    ticker.run(sent.append, now=2.06)
    assert sent == [2.0, 2.06]


def test_busy_delivery_never_waits_or_changes_the_clock():
    ticker, sent = ControlTicker(20), []
    entered, release = Event(), Event()

    def send(now):
        entered.set()
        assert release.wait(5)
        sent.append(now)
        return "delivered"

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(ticker.run, send, now=1.0)
        try:
            assert entered.wait(5)
            skipped = pool.submit(ticker.run, sent.append, now=10.0, immediate=True)
            assert skipped.result(timeout=1) is None
            assert sent == []
        finally:
            release.set()
        assert pending.result(timeout=1) == "delivered"
    ticker.run(sent.append, now=1.06)
    assert sent == [1.0, 1.06]


def test_failed_delivery_releases_the_ticker_without_advancing_the_clock():
    ticker, sent = ControlTicker(20), []

    def fail(now):
        raise RuntimeError("output unavailable")

    with pytest.raises(RuntimeError, match="output unavailable"):
        ticker.run(fail, now=1.0)
    ticker.run(sent.append, now=1.01)
    assert sent == [1.01]
