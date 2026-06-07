"""The :class:`Bridge` — a managed subprocess for heavy out-of-band data acquisition."""

from __future__ import annotations

import subprocess


class Bridge:
    """A subprocess MyoGestic spawns alongside the app and tears down on exit.

    The escape hatch for **heavy-data acquisition that doesn't fit the
    LSL pull model** - a webcam decoder that writes frames straight to
    Zarr, an ultrasound capture daemon, a custom script that owns its
    own buffer. The bridge subprocess runs whatever it wants; MyoGestic
    only cares that it stays alive and exits cleanly.

    The bridge pattern is intentionally minimal: no IPC contract beyond
    "the subprocess exists, is alive, and stops on terminate". For data
    flowing back into the app, the subprocess publishes an LSL outlet
    (or writes to a Zarr file the app reads) - the same machinery
    every other source uses.

    Registered via ``app.bridges(...)``; the app starts them after
    streams and tears them down on cleanup.

    Parameters
    ----------
    name
        Human label, used in the bridge panel and logs.
    command
        argv passed to ``subprocess.Popen``. Stdout and stderr
        are captured to PIPE; nothing reads them by default.
    """

    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process: subprocess.Popen | None = None
        self.status = "stopped"

    def start(self) -> None:
        """Spawn the subprocess. Idempotent only if you check :attr:`alive` first."""
        self.process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.status = "running"

    def stop(self) -> None:
        """Terminate the subprocess (SIGTERM, then SIGKILL after 5 s)."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.status = "stopped"

    @property
    def alive(self) -> bool:
        """``True`` while the subprocess is running."""
        return self.process is not None and self.process.poll() is None
