"""Acquire EMG from an OTB Quattrocento amplifier into a MyoGestic Stream.

Setup: connect the Quattrocento to this PC over Ethernet (a USB-C->LAN adapter on
a Mac). Give the PC a link-local address on the amplifier's segment (e.g.
169.254.1.1 / 255.255.0.0); the amplifier is the TCP server at 169.254.1.10:23456
and this PC connects in as the client.
"""

import time

from myogestic import Stream
from myogestic.sources.otb import QuattrocentoSource


def main() -> None:
    stream = Stream(
        "emg",
        # 2048 Hz, 120-channel wire -> 96 biosignal channels, monopolar 10-500 Hz.
        # Pass select=/detection=/hpf=/lpf= to pick channels and filters.
        source=QuattrocentoSource(fs_mode=1, nch_mode=0),
        window_ms=1000,
    )
    stream.start()
    print("Connected. Reading 5 windows...")

    for _ in range(5):
        time.sleep(1.0)
        data, ts = stream.get_window()
        if data is not None:
            print(f"window: {data.shape} (channels-first), last ts={ts[-1]:.3f}")
    stream.stop()


if __name__ == "__main__":
    main()
