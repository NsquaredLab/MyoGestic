from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import numpy as np

from myogestic.session._io import open_session_store

log = logging.getLogger("myogestic.session")


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
        if stream_name not in sess.stores:
            log.info("skipping %s: stream %r not present", path, stream_name)
            continue
        info = sess.stream_info(stream_name)
        fs = info.fs
        if fs <= 0:
            log.warning("skipping %s: bad fs=%s for stream %r", path, fs, stream_name)
            continue
        win_samples = int(window_ms / 1000 * fs)
        hop_samples = max(1, int(hop_ms / 1000 * fs))
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


def iter_aligned_windows(
    paths: list[str] | list[Path],
    primary_stream_name: str,
    aligned_stream_names: list[str],
    window_ms: float,
    hop_ms: float,
    n_alignment_samples: int = 1,
) -> Iterator[tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]]:
    """Yield ``(primary_window, aligned, ts)`` for regression training.

    ``primary_window`` is channels-first ``(n_channels, n_samples)``.
    For each primary window, find the nearest sample in every aligned
    stream at the window midpoint and average ``n_alignment_samples``
    around that index.
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
        win_samples = int(window_ms / 1000 * fs)
        hop_samples = max(1, int(hop_ms / 1000 * fs))
        if win_samples < 1:
            continue

        primary_data = np.array(sess.stores[primary_stream_name]).astype(np.float32, copy=False)
        primary_ts = np.array(sess.ts_stores[primary_stream_name])
        aligned_data = {
            name: np.array(sess.stores[name]).astype(np.float32, copy=False)
            for name in aligned_stream_names
        }
        aligned_ts = {name: np.array(sess.ts_stores[name]) for name in aligned_stream_names}

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
            yield primary_data[start:stop].T, aligned_vals, primary_ts[start:stop]
