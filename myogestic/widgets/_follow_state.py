"""Per-card recording state and saved-take scoring for FollowRun."""

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock, Thread

import numpy as np

from myogestic.session import Session, open_session_store
from myogestic.tracking import Sinusoid, score_tracking


@dataclass
class FollowState:
    """State owned by one widget instance, never by the gesture names."""

    trajectory: Sinusoid
    gesture: int = 0
    phase: str = "idle"
    started: float = 0.0
    ended: float | None = None
    elapsed: float = 0.0
    session: Session | None = None
    source_path: Path | None = None
    target: tuple[int, float] | None = None
    score: dict[str, float | None] | None = None
    last_timestamp: float = -float("inf")
    stop_event: Event = field(default_factory=Event)
    worker: Thread | None = None
    lock: RLock = field(default_factory=RLock)


def score_take(path: Path) -> dict[str, float | None]:
    """Read the recorded target and configured prediction channel from disk."""
    with open_session_store(path) as take:
        meta = take.extras["follow"]
        target, tt = take.get_continuous("follow.target")
        stream, channel = meta["prediction_stream"], meta["prediction_channel"]
        if stream in take.stores:
            predictions, tp = take.get_continuous(stream)
            if isinstance(channel, str):
                names = take.stream_info(stream).channel_names or []
                if channel not in names:
                    raise ValueError(f"Prediction channel {channel!r} is missing from {stream!r}")
                channel = names.index(channel)
            pred = predictions[:, channel]
        else:
            tp, pred = np.array([]), np.array([])
        start = meta["started"] + meta["trajectory"]["lead_s"]
        end = meta["ended"]
        if end < start:
            return {"rmse": None, "r": None, "lag_s": None}
        return score_tracking(
            tt,
            target[:, 1],
            tp,
            pred,
            start_s=start,
            end_s=end,
            max_lag_s=meta["max_lag_s"],
        )
