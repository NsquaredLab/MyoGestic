"""Per-frame scheduler for browser (Pyodide) mode.

Pyodide has no OS threads and `immapp.run()` blocks Python in
Emscripten's main loop, so asyncio tasks scheduled before it never get
a turn. The cooperative substitute: every long-lived loop (Stream
acquisition, Output sending, Pipeline predict) registers a step
function that the GUI callback ticks once per ImGui frame. Each step
returns the seconds it would like to wait before its next call; the
scheduler honours that with a wall-clock comparison rather than
sleeping (sleeping would freeze the frame).

This module is a no-op on desktop - the threaded loops there don't
touch it.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

# Pyodide reports sys.platform == "emscripten". Anything else uses the
# threaded code paths and never imports the scheduler at runtime.
IS_BROWSER = sys.platform == "emscripten"


class _BrowserScheduler:
    """Registry of step callbacks ticked once per ImGui frame.

    Each entry is `(step_fn, next_call_at)`. On `tick_all()`, every
    entry whose `next_call_at` has elapsed gets called; the returned
    delay (in seconds) becomes the new `next_call_at`. Step functions
    must be non-blocking and return quickly so we don't drop frames.
    """

    def __init__(self) -> None:
        self._entries: list[list] = []  # list of [step_fn, next_call_at]

    def register(self, step: Callable[[], float]) -> None:
        """Register a step function. First call happens on the next tick."""
        self._entries.append([step, 0.0])

    def tick_all(self) -> None:
        """Run every step whose scheduled time has arrived."""
        now = time.monotonic()
        for entry in self._entries:
            if now >= entry[1]:
                try:
                    delay = entry[0]()
                except Exception:
                    # Step callbacks own their own error logging; a
                    # crash here must not freeze the GUI.
                    import traceback

                    traceback.print_exc()
                    delay = 1.0
                entry[1] = now + max(0.0, float(delay))


_scheduler = _BrowserScheduler()


def register(step: Callable[[], float]) -> None:
    """Module-level shortcut so call sites don't reach for the singleton."""
    _scheduler.register(step)


def tick_all() -> None:
    """Call once per ImGui frame from the App's GUI callback."""
    _scheduler.tick_all()
