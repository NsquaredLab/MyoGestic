"""Standalone LSL dummy streamer. Run as a subprocess.

Usage:
    python -m myogestic.tools.lsl_dummy --name FakeEMG --channels 8 --fs 256
"""

import time
from typing import Annotated

import numpy as np
import typer
from mne_lsl.lsl import StreamInfo, StreamOutlet


def main(
    name: Annotated[str, typer.Option(help="Stream name")] = "DummyEMG",
    channels: Annotated[int, typer.Option(help="Number of channels")] = 8,
    fs: Annotated[float, typer.Option(help="Sample rate (Hz)")] = 256,
    chunk: Annotated[int, typer.Option(help="Samples per push")] = 32,
) -> None:
    """Publish random float32 data on an LSL outlet for quick testing."""
    info = StreamInfo(name, "EMG", channels, fs, "float32", "")
    outlet = StreamOutlet(info)
    interval = chunk / fs

    print(f"LSL dummy: name={name}, {channels}ch, {fs}Hz, chunk={chunk}")

    try:
        while True:
            samples = (np.random.randn(chunk, channels) * 100).astype(np.float32)
            for sample in samples:
                outlet.push_sample(sample)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("LSL dummy stopped")


if __name__ == "__main__":
    typer.run(main)
