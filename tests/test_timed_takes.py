"""Take deadlines and cancellation, independent of ImGui or wall-clock sleeps."""

from dataclasses import FrozenInstanceError

import pytest

from myogestic.widgets.panels.recording import _TakeMachine


@pytest.fixture
def take():
    calls = []
    machine = _TakeMachine(lambda: calls.append("record"), lambda: calls.append("stop"))
    return machine, calls


def test_warmup_record_save_and_expire(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, warmup_s=2.0, now=10.0)
    assert machine.status.phase == "warmup"
    assert machine.status.warmup_left_s == 2.0
    assert calls == []
    machine.advance(recording=False, now=11.4)
    assert machine.status.warmup_left_s == pytest.approx(0.6)
    machine.advance(recording=False, now=12.0)
    assert calls == ["record"]
    assert machine.status.phase == "recording"
    machine.advance(recording=True, now=16.999)
    assert calls == ["record"]
    machine.advance(recording=True, now=17.0)
    assert calls == ["record", "stop"]
    assert machine.status.phase == "saved"
    assert machine.status.saved_text == "Saved · Fist · 5.0 s"
    machine.advance(recording=False, now=18.99)
    assert machine.status.phase == "saved"
    machine.advance(recording=False, now=19.0)
    assert machine.status.phase == "idle"
    assert calls == ["record", "stop"]


def test_warmup_off_starts_on_press_even_at_zero(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, now=0.0)
    assert calls == ["record"]
    assert machine.status.phase == "recording"
    machine.advance(recording=True, now=0.3)
    assert machine.status.elapsed_s == 0.3


def test_cancel_warmup_never_records_or_saves(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, warmup_s=2.0, now=0.0)
    machine.stop(now=1.0)
    machine.advance(recording=False, now=20.0)
    assert machine.status.phase == "idle"
    assert calls == []


def test_stop_early_keeps_captured_duration_once(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, now=0.0)
    machine.stop(now=1.4)
    machine.stop(now=1.5)
    assert calls == ["record", "stop"]
    assert machine.status.saved_text == "Saved · Fist · 1.4 s (stopped early)"


def test_outside_stop_wins_over_expired_deadline(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, now=0.0)
    machine.advance(recording=False, now=6.0)
    assert machine.status.phase == "idle"
    assert calls == ["record"]


@pytest.mark.parametrize("warmup", [0.0, 2.0])
def test_invalidated_take_never_fires_late(take, warmup):
    machine, calls = take
    machine.start("Fist", length_s=5.0, warmup_s=warmup, now=0.0)
    machine.advance(recording=not warmup, valid=False, now=0.5)
    machine.advance(recording=False, now=20.0)
    assert machine.status.phase == "idle"
    assert calls == ([] if warmup else ["record", "stop"])


def test_outside_start_during_warmup_is_not_owned(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, warmup_s=2.0, now=0.0)
    machine.advance(recording=True, now=3.0)
    assert machine.status.phase == "idle"
    assert calls == []


def test_slow_frame_stops_immediately_and_reports_actual_duration(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, now=0.0)
    machine.advance(recording=True, now=5.25)
    machine.advance(recording=False, now=5.5)
    assert calls == ["record", "stop"]
    assert machine.status.elapsed_s == 5.25


def test_late_warmup_frame_still_captures_full_length(take):
    machine, calls = take
    machine.start("Fist", length_s=5.0, warmup_s=2.0, now=0.0)
    machine.advance(recording=False, now=3.0)
    machine.advance(recording=True, now=7.9)
    assert calls == ["record"]
    machine.advance(recording=True, now=8.0)
    assert calls == ["record", "stop"]


def test_start_stop_elapsed_and_immutable_snapshot(take):
    machine, calls = take
    machine.start("Fist", now=10.0)
    snapshot = machine.status
    machine.advance(recording=True, now=17.4)
    assert machine.status.elapsed_s == pytest.approx(7.4)
    assert not machine.status.timed
    assert snapshot.elapsed_s == 0.0
    with pytest.raises(FrozenInstanceError):
        snapshot.elapsed_s = 9.0
    machine.stop(now=20.0)
    assert calls == ["record", "stop"]
    assert machine.status.saved_text == "Saved · Fist · 10.0 s"


def test_injected_clock(take):
    calls = []
    now = [42.0]
    machine = _TakeMachine(lambda: calls.append("record"), lambda: calls.append("stop"),
                           clock=lambda: now[0])
    machine.start("Fist", length_s=5.0)
    now[0] = 47.0
    machine.advance(recording=True)
    assert calls == ["record", "stop"]


@pytest.mark.parametrize("warmup", [0.0, 2.0])
def test_session_setup_time_does_not_shorten_capture(warmup):
    now, calls = [0.0], []

    def start():
        calls.append("record")
        now[0] += 0.25  # Creating the session and allocating its stream stores.

    machine = _TakeMachine(start, lambda: calls.append("stop"), clock=lambda: now[0])
    machine.start("Fist", length_s=5.0, warmup_s=warmup)
    if warmup:
        now[0] = warmup
        machine.advance(recording=False)
    now[0] = warmup + 5.0
    machine.advance(recording=True)
    assert calls == ["record"]
    assert machine.status.elapsed_s == 4.75
    now[0] += 0.25
    machine.advance(recording=True)
    assert calls == ["record", "stop"]
    assert machine.status.saved_text == "Saved · Fist · 5.0 s"


@pytest.mark.parametrize(("seconds", "expected"), [(5.1 - 2.0, "0:03.1"), (59.96, "1:00.0")])
def test_clock_rounds_tenths_without_losing_a_digit(seconds, expected):
    from myogestic.widgets.panels._recording_controls import _clock

    assert _clock(seconds) == expected
