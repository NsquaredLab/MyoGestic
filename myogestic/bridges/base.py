from __future__ import annotations

import subprocess
import sys


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


class WebCamBridge(Bridge):
    """Bridge that runs the built-in webcam decoder subprocess.

    Wraps ``python -m myogestic.bridges.webcam``: captures frames from an
    OpenCV device, writes them to a Zarr array, and publishes the
    per-frame LSL clock so the rest of the app can align webcam time
    with EMG time.

    Parameters
    ----------
    name
        Bridge label. The published LSL clock outlet is named
        ``"{name}_clock"`` (e.g. ``WebCamBridge("cam")`` publishes
        ``"cam_clock"``).
    device
        OpenCV device index. ``0`` is the system default
        camera; secondary cameras get ``1``, ``2``, ... in the
        order the OS enumerates them.
    zarr_path
        Where to write the frame array. Created if missing.
    """

    def __init__(self, name: str, device: int = 0, zarr_path: str = "session/cam.zarr"):
        super().__init__(
            name=name,
            command=[
                sys.executable,
                "-m",
                "myogestic.bridges.webcam",
                "--device",
                str(device),
                "--zarr",
                zarr_path,
                "--lsl-name",
                f"{name}_clock",
            ],
        )


class CustomBridge(Bridge):
    """Bridge that runs an arbitrary user Python script as a subprocess.

    The unstructured escape hatch: when the heavy-data source you want
    doesn't fit :class:`WebCamBridge` and you'd rather write the
    decoder yourself than subclass :class:`Bridge`. The script runs
    with the same Python interpreter as the app
    (``sys.executable``); the rest is up to you (publish LSL, write
    Zarr, talk to a custom message bus, ...).

    Parameters
    ----------
    name
        Bridge label.
    script
        Path to the Python script to spawn (e.g.
        ``"capture/ultrasound.py"``).
    """

    def __init__(self, name: str, script: str):
        super().__init__(
            name=name,
            command=[sys.executable, script],
        )
