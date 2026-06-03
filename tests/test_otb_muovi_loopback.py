import socket
import threading
import time

import numpy as np

from myogestic.sources.otb._constants import muovi_control_byte, muovi_geometry
from myogestic.sources.otb.muovi import MuoviSource


def _be_int16_frame(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "big", signed=False)
    return bytes(out)


def test_muovi_loopback_emg_mode0():
    geo = muovi_geometry(plus=False, emg=True, mode=0)  # 38 ch, 2000 Hz, int16

    # MuoviSource is the server; the fake probe is the client that dials in.
    src = MuoviSource(host_ip="127.0.0.1", port=0, mode=0, emg=True)
    info = src.connect_listen()  # bind+listen, return the bound port (test hook)
    port = src._server.getsockname()[1]

    received_cmd = []

    def fake_probe():
        c = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        # one sample-instant: channels 0..37 valued 0..37
        frame = _be_int16_frame(list(range(geo.n_total)))
        # read the control byte the source sends on start
        c.settimeout(2.0)
        for _ in range(20):
            c.sendall(frame)
            time.sleep(0.005)
        try:
            received_cmd.append(c.recv(1))
        except Exception:
            pass
        time.sleep(0.2)
        c.close()

    t = threading.Thread(target=fake_probe, daemon=True)
    t.start()

    stream_info = src.accept_and_start()  # accept probe, send control byte
    assert stream_info.n_channels == 32   # biosignal-only by default
    assert stream_info.fs == 2000.0

    # pull a few times
    got = None
    for _ in range(50):
        data, ts = src.read()
        if data is not None:
            got = (data, ts)
            break
        time.sleep(0.02)
    src.disconnect()

    assert got is not None
    data, ts = got
    assert data.shape[1] == 32
    # channel 0 raw was 0 -> 0 mV; channel 5 raw was 5 -> 5*0.000286 mV
    np.testing.assert_allclose(data[0, 5], 5 * 0.000286, rtol=1e-5)


def test_muovi_source_importable_from_package():
    from myogestic.sources.otb import MuoviSource as M
    assert M is MuoviSource
