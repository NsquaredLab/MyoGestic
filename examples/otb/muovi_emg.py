"""Acquire EMG from an OTB Muovi probe into a MyoGestic Stream.

Setup: hold the Muovi power button ~5 s to start it as a WiFi access point,
join its "MVxxx-ID" network from this PC, then run this script. The PC acts as
the TCP server the probe dials into.
"""
from myogestic import Stream
from myogestic.sources.otb import MuoviSource


def main() -> None:
    stream = Stream(
        "emg",
        source=MuoviSource(plus=False, emg=True, mode=0),  # 32-ch gain-8 @2000Hz
        window_seconds=1.0,
    )
    stream.start()
    print("Connected. Reading 5 windows...")
    import time

    for _ in range(5):
        time.sleep(1.0)
        data, ts = stream.get_window()
        if data is not None:
            print(f"window: {data.shape} (channels-first), last ts={ts[-1]:.3f}")
    stream.stop()


if __name__ == "__main__":
    main()
