from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np

from myogestic.session._io import open_session_store

log = logging.getLogger("myogestic.session")

#: A target sample arriving more than this many of its own sample periods after the
#: previous one is a hole in the recording, not the next sample. `iter_target_windows`
#: drops a window ending inside one rather than interpolating across it. Three periods
#: tolerates ordinary timestamp jitter and a single dropped sample; a dropped *chunk* —
#: the realistic failure — is an order of magnitude wider.
_MAX_GAP_PERIODS = 3.0

#: How much longer than ``window_ms`` a window's recorded samples may actually span
#: before `iter_target_windows` drops it. Its causal argument rejects taking the window
#: centre because that predicts the past by half a window; a window whose samples reach
#: back half again as far carries the same error, so that is where the line goes.
_MAX_SPAN_SLACK = 1.5


class SessionSplit[P: str | Path](NamedTuple):
    """Which sessions carry a stream, which do not, and which could not be opened.

    Attributes
    ----------
    with_stream
        Paths whose recording contains the stream — the `iter_aligned_windows` set.
    without_stream
        Paths that opened fine and simply do not have it — the `iter_labeled_windows`
        fallback set.
    unreadable
        ``(path, exception)`` for every path that would not open at all. Returned rather
        than logged, because *where* a skipped session is reported belongs to the caller:
        a training callback puts it in the app's own log, not in `logging`.
    """

    with_stream: list[P]
    without_stream: list[P]
    unreadable: list[tuple[P, Exception]]


def split_sessions_by_stream[P: str | Path](
    paths: Iterable[P], stream: str
) -> SessionSplit[P]:
    """Sort session paths by whether they recorded ``stream``, without holding them open.

    The question every mixed training callback asks first: sessions with a kinematics
    stream train against it, the rest fall back to synthetic targets from their labels.

    Each session is opened only to read its store list and is **closed again straight
    away** — an open `zarr.storage.ZipStore` keeps a lock on the ``.session.zip``, which
    on Windows blocks deleting or moving the file afterwards.

    Parameters
    ----------
    paths
        Session locations — folders or ``.session.zip`` archives, e.g. ``data.paths``.
    stream
        The stream name to test for, e.g. ``"vhi_control"``.

    Returns
    -------
    SessionSplit
        The three-way outcome, each list in the order the paths came in.

    Examples
    --------
    >>> from myogestic.session import split_sessions_by_stream
    >>> kin, labels, unreadable = split_sessions_by_stream([], "vhi_control")
    >>> kin, labels, unreadable
    ([], [], [])
    """
    with_stream: list[P] = []
    without_stream: list[P] = []
    unreadable: list[tuple[P, Exception]] = []
    for path in paths:
        try:
            sess = open_session_store(path)
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop the rest
            unreadable.append((path, exc))
            continue
        try:
            present = stream in sess.stores
        finally:
            sess.close()
        (with_stream if present else without_stream).append(path)
    return SessionSplit(with_stream, without_stream, unreadable)


def iter_labeled_windows(
    paths: list[str] | list[Path],
    stream_name: str,
    window_ms: float,
    hop_ms: float,
    classes: set[int] | None = None,
) -> Iterator[tuple[np.ndarray, np.ndarray, int]]:
    """Yield ``(window, ts, class_index)`` triples from labeled segments.

    ``window`` is channels-first ``(n_channels, n_samples)`` — the
    library's standard signal layout. ``ts`` is the matching 1-D
    timestamp array. Walks each session's label track, finds the time
    interval each label covers (this label's timestamp to next label's
    timestamp), and chops that interval into fixed-size windows. Works
    for folders and ``.session.zip`` sessions.

    Examples
    --------
    >>> from myogestic.session import iter_labeled_windows
    >>> for window, timestamps, class_index in iter_labeled_windows(
    ...     ["sessions/demo.session.zip"], "emg", 200, 100
    ... ):
    ...     print(window.shape, class_index)
    """
    if window_ms <= 0:
        raise ValueError(f"window_ms must be > 0 (got {window_ms})")
    if hop_ms <= 0:
        raise ValueError(f"hop_ms must be > 0 (got {hop_ms})")

    for path in paths:
        try:
            sess = open_session_store(path)
        except Exception as e:
            log.warning("skipping %s: %s", path, e)
            continue
        # finally: close the session each iteration so its zarr/ZipStore handles
        # are released — on Windows an open ZipStore locks the .session.zip, so a
        # leaked handle blocks deleting/moving the file after training.
        try:
            if stream_name not in sess.stores:
                log.info("skipping %s: stream %r not present", path, stream_name)
                continue
            info = sess.stream_info(stream_name)
            fs = info.fs
            if fs <= 0:
                log.warning("skipping %s: bad fs=%s for stream %r", path, fs, stream_name)
                continue
            # `ms * fs / 1000`, not `ms / 1000 * fs`: the latter truncates the float slop
            # off an exact product, so 290 ms at 100 Hz comes out as 28 samples of signal
            # rather than 29.
            win_samples = int(window_ms * fs / 1000)
            hop_samples = max(1, int(hop_ms * fs / 1000))
            if win_samples < 1:
                continue

            data = np.array(sess.stores[stream_name]).astype(np.float32, copy=False)
            ts = np.array(sess.ts_stores[stream_name])
            events = sess.label_track
            if len(data) == 0 or not events:
                log.info("skipping %s: empty data or no labels", path)
                continue

            for i, event in enumerate(events):
                if event.class_index < 0:
                    continue
                if classes is not None and event.class_index not in classes:
                    continue
                idx_start = int(np.argmin(np.abs(ts - event.timestamp)))
                idx_end = (
                    int(np.argmin(np.abs(ts - events[i + 1].timestamp)))
                    if i + 1 < len(events)
                    else len(ts)
                )
                if idx_end - idx_start < win_samples:
                    continue
                for start in range(idx_start, idx_end - win_samples + 1, hop_samples):
                    stop = start + win_samples
                    yield data[start:stop].T, ts[start:stop], event.class_index
        finally:
            sess.close()


def iter_target_windows(
    paths: list[str] | list[Path],
    stream_name: str,
    target_stream_name: str,
    window_ms: float,
    hop_ms: float,
    phases: set[str] | None = None,
) -> Iterator[tuple[np.ndarray, np.ndarray, float]]:
    """Yield ``(window, ts, target)`` triples against a recorded continuous target.

    The continuous sibling of `iter_labeled_windows`. That one walks the label track and
    hands back a *class index*, so a session of three cued classes holds three distinct
    target values — a regressor trained on ``-1 / 0 / +1`` has never seen an intermediate
    one, and nothing in the data says what half a contraction should produce, so whatever
    it emits there comes from the estimator's own bias rather than the recording. This
    one pairs each window with the value of a **recorded target
    stream** — a `myogestic.sources.target.TargetSource` the subject was following — so
    the targets densely cover the range and interpolation is learned rather than hoped
    for.

    ``window`` is channels-first ``(n_channels, n_samples)`` and ``ts`` the matching 1-D
    timestamp array, exactly as in `iter_labeled_windows`. ``target`` is channel 0 of the
    target stream, in whatever units it was recorded in (percent MVC for a force ramp,
    signed ``[-1, +1]`` for a cursor) — this function does not rescale it.

    **The target is the value at the window's END.** The model is causal: it sees a
    trailing window of EMG and must emit the command for *now*, so the instant the window
    ends is the instant it is answering for. Taking the centre would train it to predict
    the past by half a window, and the mean would train it to output a smeared average
    that lags every ramp — both produce a model that scores well offline and drags in the
    hand.

    **Alignment is by timestamp, never by index.** The target stream is typically far
    slower than the EMG (100 Hz beside 2 kHz) and starts and stops at its own chunk
    boundaries, so sample *i* of one is not sample *i* of the other. The lookup starts
    from the newest target sample at or before the window's end. A window whose end falls
    outside the target stream's own time span is **dropped**, not clamped to the first or
    last recorded value, because clamping would invent ground truth for the seconds the
    subject was not being shown anything. A window ending inside a *hole* in the target
    stream is dropped for exactly that reason: a gap wider than `_MAX_GAP_PERIODS` sample
    periods is a dropout, and the span it covers is as unrecorded as the span past the
    end.

    **The value is interpolated only within one phase.** Inside a phase the trajectory is
    smooth and slow, so `numpy.interp` between the two bracketing target samples reads it
    more finely than the target's own rate. Across a phase *change* the value is held at
    the same sample that supplied the phase, because the value can step there —
    `TargetSource.stop` drops the level and switches to ``idle`` in a single sample — and
    interpolating through a step produces a level the subject was never shown: a
    plausible-looking label for effort that never happened.

    **A window must also span the time it claims to.** Windows are cut by sample index,
    so wherever the *signal* stream dropped out, ``win_samples`` consecutive recorded
    samples reach back further than `window_ms`. Such a window is dropped once it spans
    more than `_MAX_SPAN_SLACK` times its nominal length: the target at its end is not
    the answer for samples much older than it, which is the causal argument above
    failing rather than an edge case of it.

    **Phases.** Channel 1 carries the phase code (`PHASE_CODES`). By default only windows
    ending in a phase where the subject is actually following the target are yielded —
    every name in `PHASE_CODES` except ``"idle"`` (no block running) and ``"done"`` (block
    finished). Both sit at target ``0`` while the subject does whatever they like, which
    is exactly the data that teaches a model that silence means zero *and* that zero means
    silence. Pass `phases` to override, e.g. ``phases=set(PHASE_CODES)`` to keep
    everything, or ``{"hold"}`` for plateaus only.

    **A window straddling a phase boundary** is classified by its end, the same instant
    that gives it its target, and both are read from the same target sample, so the two
    can never disagree. A window reaching from ``rest`` into ``ramp_up`` is a ``ramp_up``
    window and is kept; one whose last sample lands past the end of the block is ``done``
    and is dropped, along with the EMG that trails it.

    Parameters
    ----------
    paths
        Session locations — folders or ``.session.zip`` archives.
    stream_name
        The signal to window, e.g. ``"emg"``.
    target_stream_name
        The recorded `TargetSource` stream, e.g. ``"target"``.
    window_ms
        Window length in milliseconds.
    hop_ms
        Step between consecutive window starts, in milliseconds.
    phases
        Phase **names** (not codes) to keep. ``None`` means every phase except
        ``"idle"`` and ``"done"``.

    Raises
    ------
    ValueError
        If `window_ms` or `hop_ms` is not positive, if `phases` names a phase that is not
        in `PHASE_CODES`, or if a session is missing the target stream, recorded it empty,
        or did not record it from a `TargetSource` — fewer than that source's two
        channels, or channel names that are not its ``["target_pct", "phase"]``. Unlike a
        missing
        *signal* stream — which is skipped with a log line, as in `iter_labeled_windows` —
        a missing target is raised: this iterator exists for the target, and silently
        dropping the one session recorded without it means training on two thirds of the
        data and never being told.

    Examples
    --------
    >>> from myogestic.session import iter_target_windows
    >>> for window, timestamps, target in iter_target_windows(
    ...     ["sessions/demo.session.zip"], "emg", "target", 200, 100
    ... ):
    ...     print(window.shape, target)
    """
    # Imported here, not at module scope: `myogestic.sources` pulls in `replay`, which
    # imports this package back again.
    from myogestic.sources.target import PHASE_CODES

    if window_ms <= 0:
        raise ValueError(f"window_ms must be > 0 (got {window_ms})")
    if hop_ms <= 0:
        raise ValueError(f"hop_ms must be > 0 (got {hop_ms})")

    wanted = set(PHASE_CODES) - {"idle", "done"} if phases is None else set(phases)
    if unknown := sorted(wanted - set(PHASE_CODES)):
        raise ValueError(
            f"phases: unknown phase name(s) {unknown}. Pass names from "
            f"myogestic.sources.target.PHASE_CODES: {sorted(PHASE_CODES)}"
        )
    wanted_codes = {PHASE_CODES[name] for name in wanted}

    for path in paths:
        try:
            sess = open_session_store(path)
        except Exception as e:
            log.warning("skipping %s: %s", path, e)
            continue
        # finally: release the session's handles each iteration (see
        # iter_labeled_windows) — a leaked ZipStore locks the .session.zip on Windows.
        try:
            if stream_name not in sess.stores:
                log.info("skipping %s: stream %r not present", path, stream_name)
                continue
            if target_stream_name not in sess.stores:
                raise ValueError(
                    f"{path}: no stream named {target_stream_name!r} to take targets "
                    f"from (this session recorded {sorted(sess.stores)}). Record a "
                    f"TargetSource under that name alongside the signal, or train this "
                    f"session from its label track with iter_labeled_windows."
                )

            target = np.array(sess.stores[target_stream_name])
            target_ts = np.array(sess.ts_stores[target_stream_name])
            if target.ndim != 2 or target.shape[1] < 2:
                width = target.shape[1] if target.ndim > 1 else 1
                raise ValueError(
                    f"{path}: stream {target_stream_name!r} has {width} channel(s); a "
                    f"target stream carries the two TargetSource channels (value, phase "
                    f"code). Pass the name of the stream a TargetSource was recorded "
                    f"under."
                )
            if len(target_ts) == 0:
                raise ValueError(
                    f"{path}: stream {target_stream_name!r} recorded no samples, so no "
                    f"window has a target. Connect the TargetSource before starting the "
                    f"recording, or drop this session from the training set."
                )

            target_info = sess.stream_info(target_stream_name)
            # Two channels is far too weak a test on its own — any control stream has at
            # least that many, and its second column rounds to *some* phase code, so
            # windows come out against the wrong column and nothing says so. The names
            # are in the recording already; a target stream is the one whose channel 1 is
            # the phase code.
            target_names = target_info.channel_names
            if target_names and len(target_names) > 1 and target_names[1] != "phase":
                raise ValueError(
                    f"{path}: stream {target_stream_name!r} has channels "
                    f"{list(target_names)}; a TargetSource records "
                    f"['target_pct', 'phase'] and channel 1 must be the phase code. Pass "
                    f"the name of the stream a TargetSource was recorded under."
                )

            info = sess.stream_info(stream_name)
            fs = info.fs
            if fs <= 0:
                log.warning("skipping %s: bad fs=%s for stream %r", path, fs, stream_name)
                continue
            # `ms * fs / 1000`, not `ms / 1000 * fs`: the latter truncates the float slop
            # off an exact product, so 290 ms at 100 Hz comes out as 28 samples of signal
            # rather than 29.
            win_samples = int(window_ms * fs / 1000)
            hop_samples = max(1, int(hop_ms * fs / 1000))
            if win_samples < 1:
                continue

            data = np.array(sess.stores[stream_name]).astype(np.float32, copy=False)
            ts = np.array(sess.ts_stores[stream_name])
            if len(data) == 0:
                log.info("skipping %s: empty data for stream %r", path, stream_name)
                continue

            values = target[:, 0].astype(np.float64, copy=False)
            codes = target[:, 1]
            target_fs = target_info.fs
            max_gap = _MAX_GAP_PERIODS / target_fs if target_fs > 0 else float("inf")
            max_span = _MAX_SPAN_SLACK * (win_samples - 1) / fs

            yielded = 0
            for start in range(0, len(data) - win_samples + 1, hop_samples):
                stop = start + win_samples
                t_end = ts[stop - 1]
                if t_end < target_ts[0] or t_end > target_ts[-1]:
                    continue
                # These are win_samples *recorded* samples, not win_samples worth of
                # wall time: across a dropout they reach back arbitrarily far, and the
                # target at t_end answers for none of them.
                if t_end - ts[start] > max_span:
                    continue
                # Phase is a code, so it is held from the last target sample at or before
                # the window end — interpolating it would invent a phase 1.5.
                held = int(np.searchsorted(target_ts, t_end, side="right")) - 1
                code = int(round(float(codes[held])))
                if code not in wanted_codes:
                    continue
                nxt = held + 1
                if nxt < len(target_ts) and target_ts[nxt] - target_ts[held] > max_gap:
                    continue  # a hole: nothing was recorded across it to interpolate
                if nxt == len(target_ts) or code != int(round(float(codes[nxt]))):
                    # A step, or the very last sample. Hold, so the value comes from the
                    # same sample as the phase instead of sliding towards the next level.
                    value = float(values[held])
                else:
                    value = float(np.interp(t_end, target_ts, values))
                yield data[start:stop].T, ts[start:stop], value
                yielded += 1
            if yielded == 0:
                log.info(
                    "%s: no window kept — check that %r overlaps %r in time and that the "
                    "block ran (phases kept: %s)",
                    path,
                    target_stream_name,
                    stream_name,
                    sorted(wanted),
                )
        finally:
            sess.close()


def iter_aligned_windows(
    paths: list[str] | list[Path],
    primary_stream_name: str,
    aligned_stream_names: list[str],
    window_ms: float,
    hop_ms: float,
    n_alignment_samples: int = 1,
    *,
    with_names: bool = False,
) -> Iterator[tuple[np.ndarray, dict[str, Any], np.ndarray]]:
    """Yield ``(primary_window, aligned, ts)`` for regression training.

    ``primary_window`` is channels-first ``(n_channels, n_samples)``.
    For each primary window, find the nearest sample in every aligned
    stream at the window midpoint and average ``n_alignment_samples``
    around that index.

    With ``with_names=True`` each aligned stream's value is a
    ``dict[channel_name, float]`` instead of a bare vector, so a training script
    selects a target by name rather than by wire position. That is the difference
    between a script that keeps working when a configuration is reordered and one
    that silently trains on the wrong channel. Requires the recording to carry
    channel names; it raises naming the stream if it does not.

    Examples
    --------
    >>> from myogestic.session import iter_aligned_windows
    >>> for window, aligned, timestamps in iter_aligned_windows(
    ...     ["sessions/demo.session.zip"], "emg", ["vhi_control"], 200, 50
    ... ):
    ...     target = aligned["vhi_control"]
    """
    if window_ms <= 0:
        raise ValueError(f"window_ms must be > 0 (got {window_ms})")
    if hop_ms <= 0:
        raise ValueError(f"hop_ms must be > 0 (got {hop_ms})")
    if n_alignment_samples < 1:
        raise ValueError(f"n_alignment_samples must be >= 1 (got {n_alignment_samples})")

    n_left = n_alignment_samples // 2
    n_right = n_alignment_samples - n_left

    for path in paths:
        try:
            sess = open_session_store(path)
        except Exception as e:
            log.warning("skipping %s: %s", path, e)
            continue
        # finally: release the session's handles each iteration (see
        # iter_labeled_windows) — a leaked ZipStore locks the .session.zip on
        # Windows.
        try:
            if primary_stream_name not in sess.stores:
                log.info("skipping %s: primary stream %r missing", path, primary_stream_name)
                continue
            missing = [s for s in aligned_stream_names if s not in sess.stores]
            if missing:
                log.info("skipping %s: aligned streams missing: %s", path, missing)
                continue

            info = sess.stream_info(primary_stream_name)
            fs = info.fs
            if fs <= 0:
                log.warning("skipping %s: bad fs=%s on %r", path, fs, primary_stream_name)
                continue
            # `ms * fs / 1000`, not `ms / 1000 * fs`: the latter truncates the float slop
            # off an exact product, so 290 ms at 100 Hz comes out as 28 samples of signal
            # rather than 29.
            win_samples = int(window_ms * fs / 1000)
            hop_samples = max(1, int(hop_ms * fs / 1000))
            if win_samples < 1:
                continue

            primary_data = np.array(sess.stores[primary_stream_name]).astype(np.float32, copy=False)
            primary_ts = np.array(sess.ts_stores[primary_stream_name])
            aligned_data = {
                name: np.array(sess.stores[name]).astype(np.float32, copy=False)
                for name in aligned_stream_names
            }
            aligned_ts = {name: np.array(sess.ts_stores[name]) for name in aligned_stream_names}

            # Resolve names once per file, before any window is produced, so a
            # recording that cannot support name-keyed targets says so up front
            # rather than part-way through a training run.
            aligned_names: dict[str, list[str]] = {}
            if with_names:
                for name in aligned_stream_names:
                    labels = sess.stream_info(name).channel_names
                    width = aligned_data[name].shape[1] if aligned_data[name].ndim > 1 else 1
                    if not labels:
                        raise ValueError(
                            f"{path}: stream {name!r} has no channel names, so "
                            f"with_names=True cannot key its values. Record it from a "
                            f"source that publishes names (see LSLOutlet's "
                            f"channel_names), or read it positionally."
                        )
                    if len(labels) != width:
                        raise ValueError(
                            f"{path}: stream {name!r} has {len(labels)} channel names "
                            f"but {width} channels. The recording's metadata does not "
                            f"describe its data."
                        )
                    aligned_names[name] = list(labels)

            if (
                len(primary_data) == 0
                or len(primary_ts) == 0
                or any(len(t) == 0 for t in aligned_ts.values())
            ):
                log.info("skipping %s: empty stream data", path)
                continue

            n = len(primary_data)
            if n < win_samples:
                continue

            for start in range(0, n - win_samples + 1, hop_samples):
                stop = start + win_samples
                mid_t = primary_ts[start + win_samples // 2]
                aligned_vals: dict[str, np.ndarray] = {}
                ok = True
                for name in aligned_stream_names:
                    a_ts = aligned_ts[name]
                    a_data = aligned_data[name]
                    idx = int(np.argmin(np.abs(a_ts - mid_t)))
                    lo = max(0, idx - n_left)
                    hi = min(len(a_data), idx + n_right)
                    if hi <= lo:
                        ok = False
                        break
                    aligned_vals[name] = np.mean(a_data[lo:hi], axis=0)
                if not ok:
                    continue
                if with_names:
                    keyed: dict[str, Any] = {
                        name: dict(zip(aligned_names[name], vec.tolist(), strict=True))
                        for name, vec in aligned_vals.items()
                    }
                    yield primary_data[start:stop].T, keyed, primary_ts[start:stop]
                else:
                    yield primary_data[start:stop].T, aligned_vals, primary_ts[start:stop]
        finally:
            sess.close()
