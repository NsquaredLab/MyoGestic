"""`mne_lsl.lsl` shim - only `local_clock` is real here.

Everything else raises NotImplementedError on use so the failure mode
is loud rather than silent if a code path that needs real LSL slips
into the browser build.
"""

import time as _time


def local_clock() -> float:
    """Browser substitute for LSL's monotonic clock.

    Real `mne_lsl.lsl.local_clock` returns seconds since some unspecified
    epoch, monotonically. `time.monotonic()` satisfies the same contract
    well enough for any logic that only does deltas (label timestamps,
    pacing, etc.).
    """
    return _time.monotonic()


class StreamInfo:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "mne_lsl.lsl.StreamInfo is not available in the browser build "
            "of MyoGestic - the playground only supports ReplaySource."
        )


class StreamInlet:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "mne_lsl.lsl.StreamInlet is not available in the browser build "
            "of MyoGestic - the playground only supports ReplaySource."
        )


class StreamOutlet:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "mne_lsl.lsl.StreamOutlet is not available in the browser build "
            "of MyoGestic - the playground only supports ReplaySource."
        )


def resolve_streams(*args, **kwargs):
    raise NotImplementedError(
        "mne_lsl.lsl.resolve_streams is not available in the browser "
        "build of MyoGestic - the playground only supports ReplaySource."
    )
