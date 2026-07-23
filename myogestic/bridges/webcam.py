"""The webcam bridge — both halves in one place.

[`WebCamBridge`][] is the parent-side launcher you register with
``app.bridges(...)``; `main` is the child-side subprocess it spawns,
which captures frames from a webcam, writes them to zarr, and publishes an LSL
clock stream so the main process can align timestamps.

Usage (subprocess, normally launched by ``WebCamBridge``):
    python -m myogestic.bridges.webcam --device 0 --zarr session/cam.zarr --lsl-name cam_clock
"""

from __future__ import annotations

import sys
import time
from typing import Annotated

import numpy as np
import typer

from myogestic.bridges.base import Bridge


class WebCamBridge(Bridge):
    """Bridge that runs the built-in webcam decoder subprocess.

    Wraps ``python -m myogestic.bridges.webcam`` (the `main` below):
    captures frames from an OpenCV device, writes them to a Zarr array, and
    publishes the per-frame LSL clock so the rest of the app can align webcam
    time with EMG time.

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

    Examples
    --------
    >>> from myogestic.bridges import WebCamBridge
    >>> camera = WebCamBridge("cam", device=0, zarr_path="session/cam.zarr")
    >>> camera.start()
    >>> camera.stop()
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


def main(
    zarr: Annotated[str, typer.Option(help="Path for zarr frame storage")],
    lsl_name: Annotated[str, typer.Option(help="LSL stream name for clock")],
    device: Annotated[int, typer.Option(help="Camera device index")] = 0,
    fps: Annotated[float, typer.Option(help="Target capture FPS")] = 30.0,
) -> None:
    """Capture webcam frames to a zarr store and publish a per-frame LSL clock."""
    try:
        import cv2  # type: ignore
    except ImportError:
        print(
            "opencv-python is required for webcam bridge: pip install opencv-python",
            file=sys.stderr,
        )
        sys.exit(1)

    import zarr as _zarr
    from mne_lsl.lsl import StreamInfo, StreamOutlet, local_clock

    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        print(f"Cannot open camera device {device}", file=sys.stderr)
        sys.exit(1)

    # Read one frame to discover shape
    ret, frame = cap.read()
    if not ret:
        print("Cannot read from camera", file=sys.stderr)
        sys.exit(1)

    h, w, c = frame.shape

    # Create zarr store for frames — shape (0, H, W, C), append along axis 0
    store = _zarr.open(
        zarr,
        mode="w",
        shape=(0, h, w, c),
        chunks=(1, h, w, c),
        dtype=np.uint8,
    )

    # LSL clock stream: 1 channel, publishes local_clock timestamp per frame
    lsl_info = StreamInfo(lsl_name, "Clock", 1, fps, "float64", "")
    outlet = StreamOutlet(lsl_info)

    interval = 1.0 / fps
    print(f"Webcam bridge started: device={device}, {w}x{h}, {fps} fps")

    try:
        while True:
            t_start = time.perf_counter()

            ret, frame = cap.read()
            if not ret:
                continue

            ts = local_clock()

            # Append frame to zarr
            store.append(frame[np.newaxis])  # type: ignore

            # Publish timestamp on LSL
            outlet.push_sample([ts])  # type: ignore

            elapsed = time.perf_counter() - t_start
            sleep_time = interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        print("Webcam bridge stopped")


if __name__ == "__main__":
    typer.run(main)
