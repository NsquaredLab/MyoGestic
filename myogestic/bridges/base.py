"""The [`Bridge`][] — a managed subprocess for heavy out-of-band data acquisition."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("myogestic.bridges")


class Bridge:
    """A subprocess MyoGestic spawns alongside the app and tears down on exit.

    The escape hatch for **heavy-data acquisition that doesn't fit the
    LSL pull model** - a webcam decoder that writes frames straight to
    Zarr, an ultrasound capture daemon, a custom script that owns its
    own buffer. The bridge subprocess runs whatever it wants; MyoGestic
    only cares that it stays alive and exits cleanly.

    There is no IPC contract beyond "the subprocess exists, is alive,
    and stops on terminate". Data flows back into the app the way it
    already travels: the subprocess publishes an LSL outlet, or writes
    a Zarr file the app reads.

    Registered via ``app.bridges(...)``. Registering does not spawn
    anything - you call [`start`][] when you want it up - and
    ``App.run()`` calls [`stop`][] on every registered bridge on cleanup.

    Parameters
    ----------
    name
        Human label, used in log messages about this bridge.
    command
        argv passed to ``subprocess.Popen``. Stdout and stderr go to
        ``DEVNULL``: a child that outgrows the pipe buffer blocks in
        ``write()`` forever while [`alive`][] still reports ``True``.
        To watch its output, run ``command`` in a terminal.

    Examples
    --------
    >>> import sys
    >>> from myogestic.bridges import Bridge
    >>> bridge = Bridge("capture", [sys.executable, "capture.py"])
    >>> bridge.start()
    >>> bridge.stop()
    """

    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        """Spawn the subprocess, unless one is already [`alive`][].

        Idempotent: overwriting a live handle drops the only reference to a running
        process, and the next call then stacks a second one on top of it.
        """
        if self.alive:
            return
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        """Terminate the subprocess - SIGTERM, then SIGKILL if it ignores that.

        Returns while **still holding the handle** if neither signal lands: a process
        parked in an uninterruptible kernel wait ignores SIGKILL too. [`alive`][] and
        [`status`][] then keep saying it is running and [`start`][] refuses. Call this
        again to retry.

        SIGTERM first, so a bridge script's own handler and cleanup get to run.
        """
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    # Short: a process that *can* take SIGKILL is reaped in single-digit
                    # milliseconds, so anything still here has an uninterruptible wait
                    # to finish first and no amount of waiting helps.
                    self.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    # Nothing renders a bridge, so there is no log panel to append to.
                    log.warning(
                        "bridge %r: PID %s ignored SIGKILL and is still held. start() "
                        "will refuse until it goes; call stop() again to retry.",
                        self.name,
                        self.process.pid,
                    )

    @property
    def status(self) -> str:
        """``"running"`` or ``"stopped"``, read from the subprocess on every read.

        Derived rather than assigned at each transition: a stored copy goes stale the
        moment the subprocess exits on its own.

        Two values only. A signalled child carries a non-zero return code, so any
        "``code != 0`` means crashed" rule would report every successful [`stop`][] as
        a failure. Whether an exit was clean is on ``process.returncode``, which
        [`stop`][] leaves in place.
        """
        return "running" if self.alive else "stopped"

    @property
    def alive(self) -> bool:
        """``True`` while the subprocess is running."""
        return self.process is not None and self.process.poll() is None
