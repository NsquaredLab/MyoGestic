"""Public data contracts for the myogestic pipeline.

Convention — every signal array shipped through this library is
**channels-first**: shape ``(n_channels, n_samples)``. That matches what
feature libraries (MyoVerse, scipy temporal transforms) expect, and is
what ``Stream.get_window()`` and the session iterators always return.

Recorded data on disk (zarr) is samples-first, by numpy convention, but
that's a storage detail — the iterators handle the transpose for you.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TrainingData:
    """Inputs delivered to the user's ``@pipeline.train`` callback.

    Built by ``session_manager()`` and assigned by the user to
    ``pipeline.training_data`` from inside ``@app.ui``::

        @app.ui
        def ui(ctx):
            pipeline.training_data = session_manager(...)

    Attributes:
        paths:
            Session locations (folders or ``.session.zip`` archives).
        class_names:
            Human-readable labels — same list passed to
            ``recording_controls`` / ``session_manager``.
        classes:
            Active class indices to include. Pass as the ``classes=`` arg
            to ``iter_labeled_windows`` / ``iter_aligned_windows``.
    """

    paths: list[str] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
    classes: set[int] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not self.paths
