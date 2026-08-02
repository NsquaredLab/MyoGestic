"""Public session API.

The implementation is split across small private modules so this file stays
easy to scan while preserving the original import path.
"""

from myogestic.session._core import LabelEvent, Recording, Session
from myogestic.session._io import open_session_store
from myogestic.session._windows import (
    SessionSplit,
    iter_aligned_windows,
    iter_labeled_windows,
    split_sessions_by_stream,
)

__all__ = [
    "LabelEvent",
    "Recording",
    "Session",
    "SessionSplit",
    "open_session_store",
    "iter_labeled_windows",
    "iter_aligned_windows",
    "split_sessions_by_stream",
]
