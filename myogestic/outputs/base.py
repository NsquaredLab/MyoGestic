"""The :class:`Output` base class — the send-side counterpart to ``Source``.

Concrete outputs (``LSLOutlet``, ``UDPOutput``, ``SerialOutput``) subclass this;
they live in their own modules and are re-exported from :mod:`myogestic.outputs`.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

import numpy as np

log = logging.getLogger("myogestic.outputs")

# Pyodide reports sys.platform == "emscripten" and forbids OS threads.
# When detected, the send loop runs as an asyncio task on the browser
# event loop instead of a daemon thread.
_IS_BROWSER = sys.platform == "emscripten"


class Output:
    """Base class for "send the latest pushed vector at ``hz``" outputs.

    Subclass to define a new transport: override :meth:`_send` with the
    actual write (LSL `push_sample`, UDP `sendto`, serial `write`, gRPC
    RPC, ...). The base class handles everything else:

    - A daemon **output thread** is started in ``__init__`` and runs
      for the lifetime of the Output. Each tick it reads the latest
      pushed vector and calls :meth:`_send`.
    - :meth:`push` is the caller-facing API: write the latest value to
      an atomic slot (CPython's GIL guarantees atomic reference
      assignment). It is **latest-wins, not queued** - if you push
      faster than ``hz``, intermediate values are overwritten and
      never sent. That's the contract.
    - Exceptions raised by :meth:`_send` are caught, deduplicated per
      ``(error class, message)`` pair, and logged once. A flapping
      destination logs one line per failure mode and the send thread
      keeps running.

    Subclassing checklist:

    1. Call ``super().__init__(hz=...)`` from your ``__init__`` (after
       opening the underlying socket / serial port / channel - the
       send thread starts immediately).
    2. Implement ``_send(self, data: np.ndarray) -> None``. Treat
       ``data`` as read-only; validate shape; raise on misuse rather
       than silently mis-sending.
    3. Override :meth:`stop` if you need to close a resource (see
       :class:`~myogestic.outputs.UDPOutput` for an example).

    Outputs are **user-owned**: instantiate them at module scope, call
    ``.push(data)`` from inside ``@pipeline.predict``. Do not register
    them with ``App``; the framework does not track them.

    Parameters
    ----------
    hz
        Send rate of the daemon thread in Hz. Default 50. Tune to
        match your destination's appetite - LSL subscribers handle
        high rates well, a serial UART or a gRPC server may not.

    Examples
    --------
    >>> from myogestic.outputs import Output
    >>> import socket, numpy as np
    >>>
    >>> class MyOutput(Output):
    ...     def __init__(self, addr, hz=50):
    ...         self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ...         self._addr = addr
    ...         super().__init__(hz=hz)
    ...     def _send(self, data):
    ...         self._sock.sendto(data.astype(np.float32).tobytes(),
    ...                           self._addr)
    """

    def __init__(self, hz: float = 50):
        self._latest: np.ndarray | None = None
        self._hz = hz
        self._running = True
        # Dedup key per (exception class name, str(exception)) - log the
        # first occurrence per kind, suppress subsequent ones so a noisy
        # disconnect does not spam the log.
        self._seen_send_errors: set[tuple[str, str]] = set()
        if _IS_BROWSER:
            # Pyodide: no threads, and asyncio tasks don't dispatch while
            # immapp.run blocks Python. Register one step with the
            # per-frame scheduler that the App's GUI callback ticks.
            from myogestic._browser import register
            register(lambda: self._send_step() if self._running else 1.0)
        else:
            self._thread = threading.Thread(target=self._send_loop, daemon=True)
            self._thread.start()

    def push(self, data: np.ndarray) -> None:
        """Set the latest-value slot. Atomic; latest-wins; non-blocking.

        Call from inside ``@pipeline.predict``. The send thread picks
        the value up on its next tick. If you push faster than ``hz``,
        intermediate values are dropped.
        """
        self._latest = data  # GIL guarantees atomic ref assignment

    def _send_step(self) -> float:
        """Run one send-loop iteration. Returns seconds-to-sleep.

        Shared between the threaded and async loop variants so the
        send logic stays in one place; only the pacing primitive
        (time.sleep vs await asyncio.sleep) differs at the call site.
        """
        t_start = time.perf_counter()
        if self._latest is not None:
            try:
                self._send(self._latest)
            except Exception as e:
                # Never crash the send loop; log first occurrence per
                # (error class, message) pair so a noisy disconnect
                # does not flood the log.
                key = (type(e).__name__, str(e))
                if key not in self._seen_send_errors:
                    self._seen_send_errors.add(key)
                    log.warning(
                        "%s.send failed: %s: %s",
                        type(self).__name__, type(e).__name__, e,
                    )
        elapsed = time.perf_counter() - t_start
        return max(0.0, (1.0 / self._hz) - elapsed)

    def _send_loop(self) -> None:
        """Daemon-thread variant."""
        while self._running:
            delay = self._send_step()
            if delay > 0:
                time.sleep(delay)

    async def _send_loop_async(self) -> None:
        """Browser variant - asyncio.sleep yields to the frame loop."""
        while self._running:
            delay = self._send_step()
            await asyncio.sleep(delay)

    def _send(self, data: np.ndarray) -> None:
        """Transport-specific write. Override in subclass.

        Called by the send thread every ``1/hz`` seconds with the
        latest pushed vector. Raise on misuse (wrong shape, wrong
        dtype) - the base class will log the first occurrence per
        ``(error class, message)`` pair and keep the thread running.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the send thread. Subclasses that hold resources (sockets,
        serial ports) should override and call ``super().stop()`` first."""
        self._running = False
