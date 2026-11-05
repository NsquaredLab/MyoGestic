"""The piano's gate, songs and scoring as arithmetic, and one headless frame of it."""

from __future__ import annotations

import math
import runpy
import time
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from imgui_bundle import hello_imgui, imgui

import myogestic.core
from myogestic.widgets.piano import (
    INPUT_LATENCY_MS,
    NOTE_WINDOW_MS,
    REPLAY_MS,
    PianoGate,
    PianoRhythm,
    PianoTask,
    check_calibration,
)


def scores(gesture: int) -> list[float]:
    return [float(i == gesture) for i in range(7)]


def feed(gate: PianoGate, gesture: int, start: int, ms: int) -> list[int]:
    """One prediction every 31 ms, a 32 Hz predict loop."""
    return [gate.update(scores(gesture), t) for t in range(start, start + ms, 31)]


@pytest.mark.parametrize("finger", range(5))
def test_a_finger_plays_one_key_sustains_and_needs_rest_to_strike_again(finger):
    gate = PianoGate()
    assert all(n == -1 for n in feed(gate, finger + 1, 0, 310)), "struck before any rest"
    feed(gate, 0, 310, 310)
    assert gate.ready
    playing = feed(gate, finger + 1, 620, 3100)
    assert playing[:2] == [-1, -1], "one tick is not a strike"
    assert all(n == finger for n in playing[2:]), "a held finger dropped or retriggered"
    assert gate.update(scores(0), 3720) == -1
    feed(gate, 0, 3751, 186)
    assert feed(gate, finger + 1, 3937, 124)[-1] == finger


def test_fist_ambiguity_and_spikes_stay_silent_and_a_dropout_needs_fresh_rest():
    g = PianoGate()
    feed(g, 0, 0, 310)
    assert all(n == -1 for n in feed(g, 6, 310, 310))
    assert g.update([0.1, 0.4, 0.4, 0.1, 0, 0, 0], 620) == -1
    assert g.update(scores(2), 651) == -1
    assert g.update(scores(0), 682) == -1
    feed(g, 0, 713, 155)
    feed(g, 2, 868, 124)
    assert g.note == 1
    assert g.update(scores(2), 2000) == -1
    assert not g.ready
    assert all(n == -1 for n in feed(g, 2, 2031, 620))
    g.update(scores(0), 10)
    assert not g.ready


def test_uncertainty_releases_a_key_without_rearming_the_held_finger():
    g = PianoGate()
    feed(g, 0, 0, 310)
    feed(g, 3, 310, 124)
    assert g.note == 2
    g.update([0.1] * 7, 434)
    assert g.note == -1
    assert all(n == -1 for n in feed(g, 3, 465, 620))
    g.update([math.nan, 0, 0, 0, 0, 0, 0], 1085)
    assert g.note == -1 and not g.ready


def test_a_held_note_survives_a_dip_that_could_not_start_one():
    g = PianoGate()
    feed(g, 0, 0, 310)
    feed(g, 1, 310, 124)
    borderline = [0.515, 0.69, -0.15, -0.04, -0.13, 0.01, 0.1]
    assert g.update(borderline, 434) == 0
    assert g.update(scores(0), 465) == -1
    feed(g, 0, 496, 155)
    for t in range(651, 961, 31):
        assert g.update(borderline, t) == -1


def test_good_accuracy_cannot_hide_one_unlearned_finger():
    with pytest.raises(ValueError, match="Ring"):
        check_calibration([1, 1, 1, 1, 0.5, 1, 1], 0.99)
    with pytest.raises(ValueError, match="Pinky"):
        check_calibration([1, 1, 1, 1, 1, math.nan, 1], 0.99)
    with pytest.raises(ValueError, match="too similar"):
        check_calibration([1] * 7, 0.7)
    check_calibration([1, 1, 0.9, 0.9, 0.8, 0.8, 1], 0.92)


def go_to(r: PianoRhythm, ms: float) -> None:
    r.advance(ms - r.time)


def play(r: PianoRhythm, note) -> None:
    """Strike on the line, hold through a hold, release."""
    go_to(r, note.at + INPUT_LATENCY_MS)
    r.input(note.finger)
    if note.duration:
        r.advance(note.duration)
    r.input(-1)


def test_a_tap_is_judged_at_the_line_once():
    r = PianoRhythm()
    r.start()
    first = r.notes[0]
    go_to(r, first.at + INPUT_LATENCY_MS)
    r.input(4)
    assert first.state == "waiting" and r.score == 0
    r.input(first.finger)
    assert first.state == "hit" and r.score == 100
    r.input(first.finger)
    assert r.score == 100


def test_a_finger_held_before_its_window_cannot_auto_hit():
    r = PianoRhythm()
    r.start()
    go_to(r, r.notes[0].at - NOTE_WINDOW_MS - 1 + INPUT_LATENCY_MS)
    r.input(0)
    go_to(r, r.notes[0].at + INPUT_LATENCY_MS)
    r.input(0)
    assert r.score == 0
    r.input(-1)
    r.input(0)
    assert r.score == 100


@pytest.mark.parametrize("release_after", [400, 1100, 1300])
def test_a_hold_needs_its_tail(release_after):
    r = PianoRhythm()
    r.start()
    held = next(n for n in r.notes if n.duration)
    go_to(r, held.at + INPUT_LATENCY_MS)
    r.input(held.finger)
    assert held.state == "holding" and r.score == 0
    r.advance(release_after)
    r.input(-1)
    early = release_after < 1040
    assert held.state == ("miss" if early else "hit")
    assert r.score == (0 if early else 200)


def test_a_repeated_note_needs_a_new_strike_even_after_a_hold():
    r = PianoRhythm()
    r.reset(1)
    r.start()
    first, second = r.notes[2], r.notes[3]
    assert first.finger == second.finger
    go_to(r, first.at + INPUT_LATENCY_MS)
    r.input(first.finger)
    go_to(r, second.at + INPUT_LATENCY_MS)
    r.input(second.finger)
    assert first.state == "hit" and second.state == "waiting"
    r.input(-1)
    r.input(second.finger)
    assert second.state == "hit"


def test_misses_do_not_stop_the_song():
    r = PianoRhythm()
    r.start()
    r.advance(r.end)
    assert r.phase == "complete" and r.hits == 0
    assert all(n.state == "miss" for n in r.notes)
    r.input(0)
    r.advance(10000)
    assert r.score == 0


def test_pause_freezes_a_hold_and_resume_replays_it():
    r = PianoRhythm()
    r.start()
    held = r.notes[2]
    go_to(r, held.at + INPUT_LATENCY_MS)
    r.input(held.finger)
    r.advance(450)
    paused_at = r.time
    r.pause()
    r.input(-1)
    r.advance(15000)
    assert r.time == paused_at and held.state == "holding"
    r.resume()
    assert held.state == "waiting" and r.time == held.at - REPLAY_MS
    go_to(r, held.at + INPUT_LATENCY_MS)
    r.input(held.finger)
    r.advance(held.duration)
    assert held.state == "hit" and r.score == 200


@pytest.mark.parametrize("round_", range(3))
def test_every_song_can_be_played_clean_with_time_to_release(round_):
    r = PianoRhythm()
    r.reset(round_)
    r.start()
    for note in r.notes:
        play(r, note)
    go_to(r, r.end)
    assert r.phase == "complete"
    assert r.hits == r.combo == len(r.notes)
    for prev, nxt in pairwise(r.notes):
        assert nxt.at - prev.at - prev.duration >= 1100


def test_pause_just_after_a_hold_rewinds_before_its_onset():
    r = PianoRhythm()
    r.start()
    for note in r.notes:
        play(r, note)
    last = r.notes[-1]
    r.advance(300)
    r.pause()
    r.resume()
    assert r.time == last.at - REPLAY_MS and last.state == "waiting"
    assert r.hits == len(r.notes) - 1
    play(r, last)
    go_to(r, r.end)
    assert r.hits == len(r.notes)


def test_it_draws_free_and_mid_song_and_records_a_finished_song(imgui_frame):
    free = PianoTask(follow=False, widget_id="piano_free")
    song = PianoTask(widget_id="piano_song")
    song.rhythm.start()
    song.rhythm.advance(song.rhythm.notes[0].at)
    song._last = time.monotonic()

    def draw() -> None:
        imgui.begin_child("cell", imgui.ImVec2(600, 900))
        free.ui(2)
        song.ui(song.expected)
        imgui.end_child()

    imgui_frame(draw)
    assert free._count == 1 and free.expected == -1
    assert song.expected == song.rhythm.notes[0].finger

    song.rhythm.time = song.rhythm.end  # the song ends inside `ui`, where it is logged
    song._last = time.monotonic()
    imgui_frame(lambda: song.ui(-1))
    assert song.songs == [{"song": 1, "score": 100, "hits": 1, "notes": len(song.rhythm.notes)}]


EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "start_here" / "magic_piano.py"


def test_the_example_draws_record_train_and_play(monkeypatch, implot_frame, tmp_path):
    """`test_examples` draws the first step only; this draws the other three, mid-use."""
    pytest.importorskip("catboost")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(myogestic.core.App, "run", lambda self, *a, **k: None)
    # The logo image needs a running window; the header falls back to the wordmark.
    monkeypatch.setattr(hello_imgui, "asset_exists", lambda name: False)
    ns = runpy.run_path(str(EXAMPLE), run_name="__main__")
    app, steps, pipeline = ns["app"], ns["steps"], ns["pipeline"]
    app.ctx.participant = "P01"
    stream = app.ctx.streams["emg"]
    stream._source = ns["DummyHandSource"]()
    assert stream.reconnect()
    draw = lambda: app._ui_fn(app.ctx)  # noqa: E731

    app.start_recording()
    ns["lesson"].update(start=time.monotonic() - 5.0, label=None)
    steps.active = 1
    implot_frame(draw)
    assert app.ctx.session.label_track, "the lesson labelled nothing"
    app.stop_recording(wait=True)

    pipeline.model = SimpleNamespace(estimator=None, report={"accuracy": 0.9})
    steps.active = 2
    implot_frame(draw)

    pipeline.predictions = {"class": 3, "proba": [0.1, 0.0, 0.0, 0.8, 0.1, 0.0, 0.0], "note": 2}
    app.ctx.state = "predicting"
    steps.active = 3
    try:
        implot_frame(draw)
        assert ns["piano"]._note == 2
    finally:
        app.ctx.state = "idle"
        stream.disconnect()
