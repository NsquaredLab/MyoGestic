"""Magic Piano: five keys, one bent finger at a time, and songs that fall to a line.

A seven-class model (Rest, five fingers, Fist) is a lot to ask of a subject, and a
confusion matrix gives them no reason to keep at it. A piano does: each finger is a key,
a song asks for them in order, and a missed note says which finger the model does not
know yet.

The widget is *only* the game, like `PongTask`. It reads no stream, no session and no
model. `PianoTask.ui` takes the key being played as a plain int, so the classifier and
the recording stay the app's business. `PianoGate` turns class scores into that int; it
lives here because every app that drives the piano needs one.

The gate, the songs and the scoring are module level and imgui-free, so they are tested
as arithmetic rather than through a frame. Times are milliseconds throughout.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic._theme import display_font, mono_font
from myogestic.widgets.common import (
    CONSOLE_BG,
    CONSOLE_TEXT,
    IDLE,
    ON_PRIMARY_TEXT,
    PALETTE,
    SUCCESS,
    hairline,
    mono_text,
    muted,
    panel_header,
    primary,
    primary_button,
    segmented,
    ui_px,
)

#: The keys, thumb to pinky. A finger's class index is its key index plus one: Rest is
#: class 0 and Fist class 6, and neither plays anything.
NOTES = ("C", "D", "E", "F", "G")
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
#: The scores `PianoGate.update` expects, in this order.
PIANO_CLASSES = ("Rest", *FINGERS, "Fist")

# ponytail: the gate thresholds were tuned on a 32 Hz, seven-class classifier whose
# scores are probabilities (they sum to 1, as `predict_proba` does). A new amplifier,
# montage or model can need them retuned; these are the knobs.
#: A fresh strike needs the top class at this score, leading the runner-up by this much.
STRIKE_SCORE = 0.55
STRIKE_LEAD = 0.20
#: A key already sounding is kept on less: small dips must not cut a long note short.
SUSTAIN_SCORE = 0.40
SUSTAIN_LEAD = 0.08
#: Rest held this long arms the next strike, so one held finger strikes once.
REST_ARM_MS = 93.0
#: A finger must lead this long before it strikes, so a one-tick spike stays silent.
STABLE_MS = 62.0
#: A gap between score updates longer than this resets the gate (a dropout, a pause).
GAP_RESET_MS = 100.0

#: Calibration floor: every class recognised this often, and this often overall. Good
#: overall accuracy can hide one finger the model never learned.
MIN_RECALL = 0.7
MIN_ACCURACY = 0.8

#: A note counts if struck within this of its time at the line.
NOTE_WINDOW_MS = 320.0
#: Struck within this, it is perfect (100 points, not 70). Holds score double.
PERFECT_MS = 150.0
# ponytail: recognition delay the scoring forgives, so a strike on the line scores as
# one. Window length plus gate confirmation; retune if a different window is used.
INPUT_LATENCY_MS = 150.0
#: How long a note takes to fall the height of the track.
NOTE_TRAVEL_MS = 4000.0
#: Released this close to a hold's end still counts as holding it through.
RELEASE_GRACE_MS = 160.0
#: Song timing: the lead-in, a hold's length, the gap after a tap and after a hold.
LEAD_IN_MS = 3000.0
HOLD_MS = 1200.0
TAP_GAP_MS = 1500.0
RELEASE_MS = 1100.0
#: Resume replays from this far before the interrupted note.
REPLAY_MS = 1200.0
#: How long the simulated hand holds a tap.
DEMO_TAP_MS = 380.0
#: Fingers per song, cycling. Every third note and the last are holds.
MELODIES = ((0, 1, 2, 3, 4, 3, 2, 1, 0), (0, 2, 4, 4, 2, 1, 0), (2, 2, 3, 4, 4, 3, 2, 1, 0))

TIP = "Short note: bend and release. Long note: keep holding."


def check_calibration(recall: Sequence[float], accuracy: float) -> None:
    """Refuse a model that cannot play every key.

    Parameters
    ----------
    recall
        Held-out recall per class, in `PIANO_CLASSES` order.
    accuracy
        Held-out accuracy over all classes.

    Raises
    ------
    ValueError
        Naming each class below `MIN_RECALL`, or saying the movements were too similar
        when only `MIN_ACCURACY` fails.
    """
    if len(recall) != len(PIANO_CLASSES):
        raise ValueError(f"Need recall for {len(PIANO_CLASSES)} classes, got {len(recall)}.")
    weak = [
        name
        for name, value in zip(PIANO_CLASSES, recall, strict=True)
        if value is None or not math.isfinite(value) or value < MIN_RECALL
    ]
    if weak or not math.isfinite(accuracy) or accuracy < MIN_ACCURACY:
        reason = (
            f"Could not reliably recognise {', '.join(weak)}."
            if weak
            else "The finger movements were too similar."
        )
        raise ValueError(
            f"{reason} Record another lesson, bending one finger at a time and relaxing "
            "between moves."
        )


class PianoGate:
    """Turn seven class scores into at most one sounding key.

    One deliberately bent finger plays one key. Rest and Fist are silent, and so is
    anything ambiguous. A finger must be released to rest before it strikes again, so
    noise cannot hammer a held key, and a key already sounding is kept on through small
    score dips (`SUSTAIN_SCORE`) that could not start a fresh one.

    Attributes
    ----------
    note
        The key sounding now, ``0`` to ``4``, or ``-1``.
    ready
        Whether Rest has been seen long enough to arm a strike since the last reset.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Silence the key and require a fresh rest before the next strike."""
        self.note = -1
        self.ready = False
        self._armed = False
        self._previous: float | None = None
        self._rest_since: float | None = None
        self._candidate = -1
        self._since = 0.0

    def update(self, scores: Sequence[float], at_ms: float) -> int:
        """Feed one prediction and return the key sounding after it.

        Parameters
        ----------
        scores
            One score per class, in `PIANO_CLASSES` order.
        at_ms
            When the scores were produced, in milliseconds on any monotonic clock. A
            repeated or earlier time is ignored; a gap over `GAP_RESET_MS` resets.

        Returns
        -------
        int
            The key, ``0`` (thumb) to ``4`` (pinky), or ``-1`` for none.
        """
        if not math.isfinite(at_ms):
            self.reset()
            return self.note
        if self._previous is not None:
            if at_ms <= self._previous:
                return self.note
            if at_ms - self._previous > GAP_RESET_MS:
                self.reset()
        self._previous = at_ms
        scores = [float(s) for s in scores]
        if len(scores) != len(PIANO_CLASSES) or not all(math.isfinite(s) for s in scores):
            self.reset()
            return self.note
        # Stable descending sort, so a tie keeps the lower class first.
        top, second = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:2]
        lead = scores[top] - scores[second]
        sustaining = (
            self.note >= 0
            and top == self.note + 1
            and scores[top] >= SUSTAIN_SCORE
            and lead >= SUSTAIN_LEAD
        )
        best = top if sustaining or (scores[top] >= STRIKE_SCORE and lead >= STRIKE_LEAD) else -1
        if best == 0:
            if self._rest_since is None:
                self._rest_since = at_ms
            if at_ms - self._rest_since >= REST_ARM_MS:
                self._armed = self.ready = True
        else:
            self._rest_since = None
        if best != self._candidate:
            self._candidate, self._since = best, at_ms
        finger = best - 1 if 1 <= best <= len(FINGERS) else -1
        # Rest and ambiguity release at once; the next strike still needs the rest.
        if finger != self.note:
            self.note = -1
        if finger >= 0 and self._armed and at_ms - self._since >= STABLE_MS:
            self.note, self._armed = finger, False
        return self.note


@dataclass
class FallingNote:
    """One note of a song.

    Parameters
    ----------
    finger
        The key, ``0`` to ``4``.
    at
        When it reaches the line, in milliseconds of song time.
    duration
        How long to hold it, or ``0`` for a tap.
    state
        ``"waiting"``, ``"holding"``, ``"hit"`` or ``"miss"``.
    points
        What it scored once hit.
    """

    finger: int
    at: float
    duration: float
    state: str = "waiting"
    points: int = 0


def piano_song(round_: int = 0) -> list[FallingNote]:
    """The notes of song ``round_ % 3``, each leaving time to release and re-arm."""
    melody = MELODIES[round_ % len(MELODIES)]
    notes: list[FallingNote] = []
    at = LEAD_IN_MS
    for i, finger in enumerate(melody):
        duration = HOLD_MS if i % 3 == 2 or i == len(melody) - 1 else 0.0
        notes.append(FallingNote(finger, at, duration))
        at += duration + RELEASE_MS if duration else TAP_GAP_MS
    return notes


class PianoRhythm:
    """Song time, the subject's keys, and the score they earn.

    Feed `input` the key sounding now on every change and `advance` the elapsed
    milliseconds every frame. A tap is hit when its finger strikes within
    `NOTE_WINDOW_MS` of its time; a hold must also be kept until its tail reaches the
    line. Strikes are judged `INPUT_LATENCY_MS` back, the time recognition takes.

    Attributes
    ----------
    phase
        ``"ready"``, ``"playing"``, ``"paused"`` or ``"complete"``.
    time
        Song time in milliseconds.
    round
        Which song; `piano_song` cycles through three.
    """

    def __init__(self) -> None:
        self.round = 0
        self.reset()

    def reset(self, round_: int | None = None) -> None:
        """Load song ``round_`` (the current one by default), ready to start."""
        if round_ is not None:
            self.round = round_
        self.notes = piano_song(self.round)
        self.phase = "ready"
        self.time = 0.0
        self.feedback = TIP
        self._feedback_until = 0.0
        self._finger = -1

    @property
    def score(self) -> int:
        """Points from every note hit so far."""
        return sum(n.points for n in self.notes if n.state == "hit")

    @property
    def hits(self) -> int:
        """Notes hit so far."""
        return sum(n.state == "hit" for n in self.notes)

    @property
    def combo(self) -> int:
        """Notes hit since the last miss."""
        combo = 0
        for n in self.notes:
            if n.state == "hit":
                combo += 1
            elif n.state == "miss":
                combo = 0
        return combo

    @property
    def end(self) -> float:
        """Song time at which the song is complete."""
        last = self.notes[-1]
        return last.at + last.duration + NOTE_WINDOW_MS + INPUT_LATENCY_MS + 700.0

    @property
    def holding(self) -> FallingNote | None:
        """The hold being played, if any."""
        return next((n for n in self.notes if n.state == "holding"), None)

    def start(self) -> None:
        """Start the current song from the top."""
        self.reset()
        self.phase = "playing"

    def pause(self) -> None:
        """Freeze song time; `resume` replays the interrupted note."""
        if self.phase == "playing":
            self.phase = "paused"

    def resume(self) -> None:
        """Rewind to before the interrupted note and play on, with no penalty."""
        if self.phase != "paused":
            return
        rewind = max(0.0, self.time - REPLAY_MS)
        first = next(
            (i for i, n in enumerate(self.notes) if n.at + n.duration >= rewind - NOTE_WINDOW_MS),
            -1,
        )
        if first < 0:
            self.time = rewind
        else:
            self.time = max(0.0, min(rewind, self.notes[first].at - REPLAY_MS))
            # By note index, not by the rewound clock: a hold completed just before can
            # overlap the preparation time and keeps the score it earned.
            for note in self.notes[first:]:
                note.state, note.points = "waiting", 0
        self._finger = -1
        self._feedback_until = 0.0
        self.phase = "playing"

    def _say(self, message: str) -> None:
        self.feedback = message
        self._feedback_until = self.time + 1000.0

    def _finish(self, note: FallingNote, hit: bool) -> None:
        note.state = "hit" if hit else "miss"
        if not hit:
            self._say("Released early. Keep going!" if note.duration else "Missed. Keep going!")
        elif note.duration:
            self._say("Lovely hold!")
        else:
            self._say("Perfect!" if note.points == 100 else "Nice!")

    def input(self, finger: int) -> None:
        """The key sounding now changed to ``finger`` (``-1`` for none)."""
        if self.phase != "playing" or finger == self._finger:
            return
        self._finger = finger
        at = self.time - INPUT_LATENCY_MS
        held = self.holding
        if held is not None and finger != held.finger:
            self._finish(held, at >= held.at + held.duration - RELEASE_GRACE_MS)
        if finger < 0:
            return
        note = next(
            (
                n
                for n in self.notes
                if n.state == "waiting" and n.finger == finger and abs(n.at - at) <= NOTE_WINDOW_MS
            ),
            None,
        )
        if note is None:
            self._say("At the line, then bend.")
            return
        note.points = (100 if abs(note.at - at) <= PERFECT_MS else 70) * (2 if note.duration else 1)
        if note.duration:
            note.state = "holding"
            self._say("Hold… follow the tail")
        else:
            self._finish(note, True)

    def advance(self, ms: float) -> None:
        """Move song time on by ``ms``, missing notes that passed unplayed."""
        if self.phase != "playing" or not math.isfinite(ms) or ms < 0:
            return
        self.time += ms
        at = self.time - INPUT_LATENCY_MS
        for note in self.notes:
            if note.state == "waiting" and at > note.at + NOTE_WINDOW_MS:
                note.state = "miss"
                self._say("Missed. Keep going!")
            elif note.state == "holding" and at >= note.at + note.duration:
                self._finish(note, True)
        if self.time >= self.end:
            self.phase = "complete"

    @property
    def instruction(self) -> str:
        """One line telling the subject what to do now."""
        if self.phase == "complete":
            return f"{self.hits} of {len(self.notes)} notes · {self.score} points"
        if self.phase == "paused":
            return "Paused. Press Resume song when you are ready."
        if self.phase == "ready":
            return "Press Start song. Bend at the line; hold for long notes."
        if self.time < LEAD_IN_MS - 600.0:
            return f"Get ready · {math.ceil((LEAD_IN_MS - self.time) / 1000.0)}"
        if self.holding is not None:
            return "Hold… until the tail reaches the line"
        return (
            self.feedback
            if self.time < self._feedback_until
            else "Bend as the note reaches the line"
        )

    def demo_finger(self) -> int:
        """The finger a perfect player would be bending now, or ``-1``."""
        if self.phase != "playing":
            return -1
        note = next(
            (n for n in self.notes if n.at <= self.time < n.at + (n.duration or DEMO_TAP_MS)),
            None,
        )
        return -1 if note is None else note.finger


#: A frame longer than this pauses the song: notes the subject never saw must not miss.
_MAX_FRAME_MS = 250.0
#: How long a key glows after a hit.
_FLASH_S = 0.18
_KEYS_H = 92.0
_MIN_TRACK_H = 80.0


def _colour(finger: int, alpha: float = 1.0) -> imgui.ImVec4:
    """A finger's colour: `PALETTE` by *class* index, so keys match the session chips."""
    c = PALETTE[(finger + 1) % len(PALETTE)]
    return imgui.ImVec4(float(c[0]), float(c[1]), float(c[2]), alpha)


def _text(text: str, x: float, y: float, tone: imgui.ImVec4, *, size: float | None = None) -> None:
    """Text centred on ``x`` with its top at ``y``; ``size`` in screen pixels uses the display face."""
    font = display_font() if size else None
    if size:
        imgui.push_font(font or imgui.get_font(), size / imgui.get_style().font_scale_main)
    try:
        width = imgui.calc_text_size(text).x
        imgui.get_window_draw_list().add_text(
            imgui.ImVec2(x - width / 2, y), imgui.get_color_u32(tone), text
        )
    finally:
        if size:
            imgui.pop_font()


class PianoTask:
    """Five keys and a falling-note song, played one gated finger at a time.

    Call `ui` every frame with the key sounding now: ``0`` (thumb) to ``4`` (pinky), or
    ``-1``. Hand it a `PianoGate`'s output, not a raw argmax: the gate is what makes
    a held finger strike once and an ambiguous prediction stay silent.

    **Free** is a five-note playground. **Follow** drops a song down five lanes to a
    line: bend as a note reaches it, and keep bending through a ``HOLD`` until its tail
    does. Nothing falls until **Start song**, and a frame that stalls pauses the song
    rather than costing the subject notes they never saw.

    Parameters
    ----------
    follow
        Open on a song (Follow) rather than the playground (Free).
    widget_id
        ImGui id scope. Give each instance its own when an app renders more than one.

    Attributes
    ----------
    rhythm
        The song being played: its notes, phase and score.
    songs
        One summary per finished song, oldest first, for an app to save with a take.

    Examples
    --------
    >>> from myogestic.widgets import PianoTask
    >>> piano = PianoTask()
    >>> piano.ui(-1)
    """

    def __init__(self, *, follow: bool = True, widget_id: str = "piano") -> None:
        self.rhythm = PianoRhythm()
        self.songs: list[dict] = []
        self._follow = follow
        self._widget_id = widget_id
        self._note = -1
        self._count = 0
        self._last: float | None = None
        self._flash: dict[int, float] = {}

    @property
    def follow(self) -> bool:
        """Whether a song is shown (Follow) rather than the playground (Free)."""
        return self._follow

    @follow.setter
    def follow(self, value: bool) -> None:
        if value != self._follow:
            self._follow = value
            self.rhythm.reset(0)

    @property
    def expected(self) -> int:
        """The key the song asks for now, or ``-1``: always ``-1`` in Free."""
        return self.rhythm.demo_finger() if self._follow else -1

    def ui(self, note: int) -> None:
        """Render the piano and play ``note``. Call once per frame.

        Parameters
        ----------
        note
            The key sounding now, ``0`` to ``4``, or ``-1`` (anything else counts as
            ``-1``). A held note is one key held, not repeated strikes.
        """
        imgui.push_id(self._widget_id)
        try:
            now = time.monotonic()
            note = note if note in range(len(NOTES)) else -1
            self._tick(now, note)
            self._header_ui()
            dl = imgui.get_window_draw_list()
            origin = imgui.get_cursor_screen_pos()
            avail = imgui.get_content_region_avail()
            keys_h = ui_px(_KEYS_H)
            gap = imgui.get_style().item_spacing.y
            track_h = max(avail.y - keys_h - 2 * gap, ui_px(_MIN_TRACK_H))
            track = imgui.ImVec2(avail.x, track_h)
            imgui.dummy(imgui.ImVec2(avail.x, track_h + gap + keys_h))
            far = imgui.ImVec2(origin.x + track.x, origin.y + track.y)
            dl.add_rect_filled(origin, far, imgui.get_color_u32(CONSOLE_BG), ui_px(4))
            if self._follow:
                self._track_ui(dl, origin, track)
            else:
                self._free_ui(origin, track)
            self._keys_ui(dl, imgui.ImVec2(origin.x, far.y + gap), avail.x, keys_h, now)
        finally:
            imgui.pop_id()

    def _tick(self, now: float, note: int) -> None:
        """Advance song time and play ``note`` against it."""
        rhythm = self.rhythm
        dt = 0.0 if self._last is None else (now - self._last) * 1000.0
        self._last = now
        before = [n.state for n in rhythm.notes]
        was = rhythm.phase
        if dt > _MAX_FRAME_MS:
            rhythm.pause()
        elif self._follow:
            rhythm.advance(dt)
        if self._follow and rhythm.phase == "paused":
            note = -1
        if note != self._note:
            self._note = note
            if note >= 0:
                self._count += 1
            if self._follow:
                rhythm.input(note)
        for state, n in zip(before, rhythm.notes, strict=False):
            if n.state == "hit" and state != "hit":
                self._flash[n.finger] = now + _FLASH_S
        if was == "playing" and rhythm.phase == "complete":
            self.songs.append(
                {
                    "song": rhythm.round % len(MELODIES) + 1,
                    "score": rhythm.score,
                    "hits": rhythm.hits,
                    "notes": len(rhythm.notes),
                }
            )

    def _header_ui(self) -> None:
        """Title, Free / Follow, the song action and the score."""
        rhythm = self.rhythm
        playing = self._follow and rhythm.phase == "playing"
        panel_header("Magic Piano", fa.ICON_FA_MUSIC, status=SUCCESS if playing else IDLE)
        mode = segmented("piano_mode", ["Free", "Follow"], int(self._follow))
        self.follow = bool(mode)
        if self._follow:
            imgui.same_line()
            if rhythm.phase == "playing":
                if imgui.button(f"{fa.ICON_FA_PAUSE}  Pause##piano_song"):
                    rhythm.pause()
            else:
                label = {"paused": "Resume song", "complete": "Next song"}.get(
                    rhythm.phase, "Start song"
                )
                if primary_button(f"{fa.ICON_FA_PLAY}  {label}##piano_song"):
                    if rhythm.phase == "paused":
                        rhythm.resume()
                    else:
                        if rhythm.phase == "complete":
                            rhythm.reset(rhythm.round + 1)
                        rhythm.start()
                    self._last = time.monotonic()
        detail = (
            f"song {rhythm.round % len(MELODIES) + 1} · {rhythm.score} points · "
            f"{rhythm.combo} streak"
            if self._follow
            else f"{self._count} {'note' if self._count == 1 else 'notes'} played"
        )
        imgui.same_line()
        font = mono_font()  # measured in the face it is drawn in
        if font is not None:
            imgui.push_font(font, imgui.get_style().font_size_base)
        width = imgui.calc_text_size(detail).x
        if font is not None:
            imgui.pop_font()
        room = imgui.get_content_region_avail().x
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + max(0.0, room - width))
        imgui.align_text_to_frame_padding()
        mono_text(detail, muted(), width=room)

    def _track_ui(self, dl: imgui.ImDrawList, origin: imgui.ImVec2, size: imgui.ImVec2) -> None:
        """Five lanes, the falling notes and the line they fall to."""
        rhythm = self.rhythm
        lane = size.x / len(NOTES)
        line_y = origin.y + size.y - ui_px(16)
        speed = (line_y - origin.y) / NOTE_TRAVEL_MS
        faint = imgui.get_color_u32(hairline())
        for i in range(1, len(NOTES)):
            x = origin.x + i * lane
            dl.add_line(imgui.ImVec2(x, origin.y), imgui.ImVec2(x, origin.y + size.y), faint)
        dl.push_clip_rect(origin, imgui.ImVec2(origin.x + size.x, origin.y + size.y), True)
        cap = ui_px(11)
        pad = min(ui_px(8), lane * 0.12)
        for n in rhythm.notes:
            if n.state in ("hit", "miss"):
                continue
            head = line_y - (n.at - rhythm.time) * speed
            top, bottom = head - n.duration * speed - cap, head + cap
            if bottom < origin.y or top > origin.y + size.y:
                continue
            x0 = origin.x + n.finger * lane + pad
            fill = _colour(n.finger, 1.0 if n.state == "holding" else 0.85)
            dl.add_rect_filled(
                imgui.ImVec2(x0, top),
                imgui.ImVec2(x0 + lane - 2 * pad, bottom),
                imgui.get_color_u32(fill),
                ui_px(6),
            )
            label = "HOLD" if n.duration else NOTES[n.finger]
            _text(
                label, x0 + lane / 2 - pad, head - imgui.get_text_line_height() / 2, ON_PRIMARY_TEXT
            )
        dl.pop_clip_rect()
        line = imgui.ImVec4(CONSOLE_TEXT.x, CONSOLE_TEXT.y, CONSOLE_TEXT.z, 0.55)
        dl.add_line(
            imgui.ImVec2(origin.x, line_y),
            imgui.ImVec2(origin.x + size.x, line_y),
            imgui.get_color_u32(line),
            thickness=ui_px(2),
        )
        _text(rhythm.instruction, origin.x + size.x / 2, origin.y + ui_px(10), CONSOLE_TEXT)

    def _free_ui(self, origin: imgui.ImVec2, size: imgui.ImVec2) -> None:
        """The playground: the key sounding now, large, or an invitation to play."""
        centre = origin.x + size.x / 2
        if self._note < 0:
            _text(
                "Bend a finger. Make a little music.",
                centre,
                origin.y + size.y / 2 - imgui.get_text_line_height() / 2,
                CONSOLE_TEXT,
            )
            return
        big = min(size.y * 0.45, ui_px(120))
        top = origin.y + (size.y - big - imgui.get_text_line_height()) / 2
        _text(NOTES[self._note], centre, top, _colour(self._note), size=big)
        _text(FINGERS[self._note], centre, top + big, CONSOLE_TEXT)

    def _keys_ui(
        self, dl: imgui.ImDrawList, origin: imgui.ImVec2, width: float, height: float, now: float
    ) -> None:
        """Five keys; the one sounding is filled with its finger's colour."""
        key_w = width / len(NOTES)
        gap = ui_px(4)
        for i, (name, finger) in enumerate(zip(NOTES, FINGERS, strict=True)):
            x0 = origin.x + i * key_w + (gap / 2 if i else 0)
            x1 = origin.x + (i + 1) * key_w - (gap / 2 if i < len(NOTES) - 1 else 0)
            p0, p1 = imgui.ImVec2(x0, origin.y), imgui.ImVec2(x1, origin.y + height)
            lit = i == self._note
            fill = _colour(i) if lit else imgui.get_style().color_(imgui.Col_.frame_bg)
            dl.add_rect_filled(p0, p1, imgui.get_color_u32(fill), ui_px(6))
            dl.add_rect(p0, p1, imgui.get_color_u32(hairline()), ui_px(6), thickness=ui_px(1))
            if self._flash.get(i, 0.0) > now:
                dl.add_rect(p0, p1, imgui.get_color_u32(SUCCESS), ui_px(6), thickness=ui_px(3))
            centre = (x0 + x1) / 2
            big = min(height * 0.5, key_w * 0.6)
            _text(
                name, centre, origin.y + ui_px(6), ON_PRIMARY_TEXT if lit else primary(), size=big
            )
            _text(
                finger,
                centre,
                origin.y + height - imgui.get_text_line_height() - ui_px(6),
                ON_PRIMARY_TEXT if lit else muted(),
            )


__all__ = [
    "FINGERS",
    "NOTES",
    "PIANO_CLASSES",
    "FallingNote",
    "PianoGate",
    "PianoRhythm",
    "PianoTask",
    "check_calibration",
    "piano_song",
]
