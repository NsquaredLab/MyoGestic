"""Standalone webcam bridge subprocess.

Captures frames from a webcam, writes them to zarr, and publishes
an LSL clock stream so the main process can align timestamps.

Usage:
    python -m myogestic.bridges.webcam --device 0 --zarr session/cam.zarr --lsl-name cam_clock
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description="Webcam bridge for myogestic")
    parser.add_argument("--device", type=int, default=0, help="Camera device index")
    parser.add_argument("--zarr", type=str, required=True, help="Path for zarr frame storage")
    parser.add_argument("--lsl-name", type=str, required=True, help="LSL stream name for clock")
    parser.add_argument("--fps", type=float, default=30.0, help="Target capture FPS")
    args = parser.parse_args()

    try:
        import cv2
    except ImportError:
        print(
            "opencv-python is required for webcam bridge: pip install opencv-python",
            file=sys.stderr,
        )
        sys.exit(1)

    import zarr
    from mne_lsl.lsl import StreamInfo, StreamOutlet, local_clock

    cap = cv2.VideoCapture(args.device)
    if not cap.isOpened():
        print(f"Cannot open camera device {args.device}", file=sys.stderr)
        sys.exit(1)

    # Read one frame to discover shape
    ret, frame = cap.read()
    if not ret:
        print("Cannot read from camera", file=sys.stderr)
        sys.exit(1)

    h, w, c = frame.shape

    # Create zarr store for frames — shape (0, H, W, C), append along axis 0
    store = zarr.open(
        args.zarr,
        mode="w",
        shape=(0, h, w, c),
        chunks=(1, h, w, c),
        dtype=np.uint8,
    )

    # LSL clock stream: 1 channel, publishes local_clock timestamp per frame
    lsl_info = StreamInfo(args.lsl_name, "Clock", 1, args.fps, "float64", "")
    outlet = StreamOutlet(lsl_info)

    interval = 1.0 / args.fps
    print(f"Webcam bridge started: device={args.device}, {w}x{h}, {args.fps} fps")

    try:
        while True:
            t_start = time.perf_counter()

            ret, frame = cap.read()
            if not ret:
                continue

            ts = local_clock()

            # Append frame to zarr
            store.append(frame[np.newaxis])

            # Publish timestamp on LSL
            outlet.push_sample([ts])

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
    main()
