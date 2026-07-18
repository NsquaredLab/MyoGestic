# tests/test_otb_quattrocento_loopback.py
import socket
import threading
import time

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb.quattrocento import QuattrocentoSource


def _le_int16_frame(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "little", signed=False)
    return bytes(out)


def test_quattrocento_loopback_validates_config_and_streams():
    nch = C.QUATTRO_NCH_BY_MODE[0]  # 120 channels (smallest)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    seen = {}

    def fake_device():
        conn, _ = srv.accept()
        cfg = conn.recv(40)
        seen["cfg_len"] = len(cfg)
        seen["crc_ok"] = (cfg[39] == C.crc8(cfg[:39]))
        frame = _le_int16_frame(list(range(nch)))
        try:
            for _ in range(50):
                conn.sendall(frame)
                time.sleep(0.005)
            time.sleep(0.2)
        except (BrokenPipeError, OSError):
            pass  # source disconnected first — expected in this teardown race
        finally:
            conn.close()

    t = threading.Thread(target=fake_device, daemon=True)
    t.start()

    src = QuattrocentoSource(device_ip="127.0.0.1", port=port,
                             fs_mode=0, nch_mode=0, select=range(64))
    info = src.connect()
    assert info.n_channels == 64       # biosignal-only by default
    assert info.fs == 512.0

    got = None
    for _ in range(50):
        data, ts = src.read()
        if data is not None:
            got = data
            break
        time.sleep(0.02)
    src.disconnect()
    srv.close()

    assert seen["cfg_len"] == 40
    assert seen["crc_ok"] is True
    assert got is not None and got.shape[1] == 64
    # channel 10 raw=10 -> 10 * bio factor (mV)
    np.testing.assert_allclose(got[0, 10], 10 * C.QUATTRO_CONV_FACTOR_MV, rtol=1e-5)


# Task 10: export
def test_quattrocento_importable_from_package():
    from myogestic.sources.otb import QuattrocentoSource as Q
    assert Q is QuattrocentoSource
