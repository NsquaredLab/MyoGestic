"""Acquire EMG from an OTB Sessantaquattro(+) into a MyoGestic Stream.

Setup: join the device's WiFi access point from this PC, or set this PC's IP as
"Server IP address" on the sessantaquattro's internal web page. The PC acts as
the TCP server the device dials into.

The accessory-channel count is probed from the device's ramp counter rather
than configured, so the same script works on a Sessantaquattro and a
Sessantaquattro+ without changing anything.
"""
import time

from myogestic import Stream
from myogestic.sources.otb import SessantaquattroSource


def main() -> None:
    source = SessantaquattroSource(nch_mode=3, fs_mode=2)  # 64-ch monopolar @2000Hz
    stream = Stream("emg", source=source, window_ms=1000)
    # reconnect() reports failure by returning False -- it does not raise, so
    # printing "Connected" unconditionally would be a lie when nothing dialed in.
    if not stream.reconnect():  # nothing attaches a stream on its own
        print(f"Could not connect: {stream.last_error}")
        print(
            "The PC is the TCP server: the device must dial in. Join its access "
            "point, or set this PC's IP as 'Server IP address' on the device's "
            "web page, then start it."
        )
        return
    stream.start()
    print("Connected. Reading 5 windows...")

    for _ in range(5):
        time.sleep(1.0)
        # get_window() returns empty arrays -- never None -- when the ring has
        # nothing yet, so check the length rather than for None.
        data, ts = stream.get_window()
        if len(ts):
            print(f"window: {data.shape} (channels-first), last ts={ts[-1]:.3f}")
        else:
            # The acquire thread swallows source errors into stream.last_error
            # and keeps running, so an empty window is otherwise silent.
            print(f"no samples yet (status={stream.status}, error={stream.last_error})")
    stream.stop()

    # The device stamps every sample with a counter, so loss is measurable
    # rather than invisible. A session that silently dropped half its samples
    # looks entirely normal without this.
    if source.dropped_samples:
        print(
            f"WARNING: {source.dropped_samples} samples dropped in "
            f"{source.dropout_events} gaps -- the acquisition loop fell behind."
        )
    else:
        print("No samples dropped.")


if __name__ == "__main__":
    main()
