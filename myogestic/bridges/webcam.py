"""Standalone webcam bridge subprocess.

Captures frames from a webcam, writes them to zarr, and publishes
an LSL clock stream so the main process can align timestamps.

Usage:
    python -m myogestic.bridges.webcam --device 0 --zarr session/cam.zarr --lsl-name cam_clock
"""

from __future__ import annotations

import sys
import time
from typing import Annotated

import numpy as np
import typer


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
