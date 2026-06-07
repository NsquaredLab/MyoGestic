"""myogestic — real-time biosignal experiment GUI builder.

Convention — signal arrays passed to user code are channels-first
``(n_channels, n_samples)``. ``Stream.get_window()`` and the session
iterators always yield that layout; on-disk zarr storage is samples-first
and the iterators handle the transpose.
"""

from myogestic.contracts import TrainingData
from myogestic.core import App, AppState, Context
from myogestic.grid import Fr, Grid, Px
from myogestic.ml import Pipeline
from myogestic.outputs.edge_trigger import EdgeTrigger
from myogestic.stream import Source, Stream, StreamInfo

__all__ = [
    "App",
    "AppState",
    "Context",
    "EdgeTrigger",
    "Fr",
    "Grid",
    "Px",
    "Pipeline",
    "Source",
    "Stream",
    "StreamInfo",
    "TrainingData",
]
