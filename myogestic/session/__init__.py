"""Public session API.

Private modules implement the session lifecycle and storage helpers.
"""

from myogestic.session._core import (
    LabelEvent,
    RecordedTime,
    Recording,
    Session,
    class_codes,
    labelled_path,
    model_path,
    participant_dir,
    recorded_time,
)
from myogestic.session._io import open_session_store, recover_session
from myogestic.session._windows import (
    SessionSplit,
    iter_aligned_windows,
    iter_labeled_windows,
    iter_target_windows,
    split_sessions_by_stream,
)

__all__ = [
    "LabelEvent",
    "RecordedTime",
    "Recording",
    "Session",
    "SessionSplit",
    "class_codes",
    "labelled_path",
    "model_path",
    "participant_dir",
    "recorded_time",
    "open_session_store",
    "recover_session",
    "iter_labeled_windows",
    "iter_aligned_windows",
    "iter_target_windows",
    "split_sessions_by_stream",
]
