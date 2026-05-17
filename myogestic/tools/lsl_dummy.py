"""Standalone LSL dummy streamer. Run as a subprocess.

Usage:
    python -m myogestic.tools.lsl_dummy --name FakeEMG --channels 8 --fs 256
"""

import argparse
import time

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet


def main() -> None:
    parser = argparse.ArgumentParser(description="LSL dummy streamer")
    parser.add_argument("--name", type=str, default="DummyEMG", help="Stream name")
    parser.add_argument("--channels", type=int, default=8, help="Number of channels")
    parser.add_argument("--fs", type=float, default=256, help="Sample rate (Hz)")
    parser.add_argument("--chunk", type=int, default=32, help="Samples per push")
    args = parser.parse_args()

    info = StreamInfo(args.name, "EMG", args.channels, args.fs, "float32", "")
    outlet = StreamOutlet(info)
    interval = args.chunk / args.fs

    print(f"LSL dummy: name={args.name}, {args.channels}ch, {args.fs}Hz, chunk={args.chunk}")

    try:
        while True:
            chunk = (np.random.randn(args.chunk, args.channels) * 100).astype(np.float32)
            for sample in chunk:
                outlet.push_sample(sample)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("LSL dummy stopped")


if __name__ == "__main__":
    main()
