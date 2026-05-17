"""Public session API.

The implementation is split across small private modules so this file stays
easy to scan while preserving the original import path.
"""

from myogestic._session_core import LabelEvent, Recording, Session
from myogestic._session_io import open_session_store
from myogestic._session_windows import iter_aligned_windows, iter_labeled_windows

__all__ = [
    "LabelEvent",
    "Recording",
    "Session",
    "open_session_store",
    "iter_labeled_windows",
    "iter_aligned_windows",
]
