"""Tests for `split_sessions_by_stream` — the sort every mixed training callback did.

Two shipped examples opened every session, tested for a kinematics stream, closed it
again and sorted the paths. The close was the load-bearing part: an open `ZipStore`
locks the ``.session.zip``, so a leaked handle blocks deleting or moving the file
afterwards on Windows.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from myogestic.session import Session, SessionSplit, split_sessions_by_stream
from myogestic.stream import StreamInfo


def _write_session(base: str, name: str, streams: list[str]) -> str:
    """A packed ``.session.zip`` carrying exactly ``streams``."""
    session = Session(base_path=base)
    info = StreamInfo(n_channels=2, fs=64.0, dtype=np.dtype("float32"))
    for stream in streams:
        session.init_stream(stream, info)
        session.append(stream, np.zeros((8, 2), dtype=np.float32), np.arange(8, dtype=np.float64))
    session.save_meta(name)
    return str(session.pack_to_zip())


def test_split_sorts_three_ways():
    """With the stream, without it, and would not open at all — all three, in order."""
    with tempfile.TemporaryDirectory() as tmp:
        kin = _write_session(tmp, "kin", ["emg", "vhi_control"])
        labels_only = _write_session(tmp, "labels", ["emg"])
        missing = str(Path(tmp) / "not-a-session")

        split = split_sessions_by_stream([kin, labels_only, missing], "vhi_control")

        assert isinstance(split, SessionSplit)
        assert split.with_stream == [kin]
        assert split.without_stream == [labels_only]
        assert [path for path, _ in split.unreadable] == [missing]
        assert isinstance(split.unreadable[0][1], Exception)


def test_split_releases_every_session_it_opened(monkeypatch):
    """The reason the loop closes a store it only opened to read `.stores`.

    Asserted by counting rather than by deleting the file: POSIX happily unlinks an open
    file, so the leak this guards against is invisible on the machine most likely to run
    the test.
    """
    from myogestic.session import _windows

    closed: list[Path] = []
    real_open = _windows.open_session_store

    def spy(path):
        session = real_open(path)
        real_close = session.close

        def close_and_record():
            closed.append(session.path)
            real_close()

        session.close = close_and_record  # type: ignore[method-assign]
        return session

    monkeypatch.setattr(_windows, "open_session_store", spy)

    with tempfile.TemporaryDirectory() as tmp:
        kin = _write_session(tmp, "kin", ["emg", "vhi_control"])
        labels_only = _write_session(tmp, "labels", ["emg"])

        split_sessions_by_stream([kin, labels_only], "vhi_control")

        assert [str(p) for p in closed] == [kin, labels_only]


def test_split_of_nothing_is_three_empty_lists():
    """No sessions ticked is not an error — the caller's own check reports that."""
    assert split_sessions_by_stream([], "vhi_control") == ([], [], [])
