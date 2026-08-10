import socket
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from myogestic.sources.otb.sessantaquattro import SessantaquattroSource

_FIXTURE = Path(__file__).parent / "fixtures" / "sessantaquattro_pro_plus_72ch.bin"


def _fake_device(port, payload, received_cmd, repeats=1):
    """Stand in for the device: dial in, read the config word, stream bytes."""

    def run():
        # Once the source disconnects mid-loop, sendall/recv raise -- swallow
        # those so the daemon thread exits without a spurious traceback.
        try:
            c = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            c.settimeout(2.0)
            # The source sends ONE 2-byte config word right after accepting,
            # before any data flows -- read it first so a mid-stream disconnect
            # cannot race it. One word, not two: a preceding GO=0 makes real
            # hardware hang up (see the assertion below).
            cmd = bytearray()
            while len(cmd) < 2:
                chunk = c.recv(2 - len(cmd))
                if not chunk:
                    break
                cmd.extend(chunk)
            received_cmd.append(bytes(cmd))
            for _ in range(repeats):
                c.sendall(payload)
                time.sleep(0.005)
            c.close()
        except OSError:
            pass

    return threading.Thread(target=run, daemon=True)


def _pull(src, attempts=50):
    for _ in range(attempts):
        data, ts = src.read()
        if data is not None:
            return data, ts
        time.sleep(0.02)
    return None, None


def test_loopback_streams_real_wire_bytes():
    payload = _FIXTURE.read_bytes()

    src = SessantaquattroSource(host_ip="127.0.0.1", port=0, nch_mode=3, fs_mode=2)
    src.connect_listen()
    port = src._server.getsockname()[1]

    received_cmd = []
    thread = _fake_device(port, payload, received_cmd)
    thread.start()

    info = src.accept_and_start()
    assert info.n_channels == 64  # biosignal-only by default
    assert info.fs == 2000.0

    data, ts = _pull(src)
    assert data is not None, "no frames decoded"
    assert data.shape[1] == 64
    assert ts is not None and np.all(np.diff(ts) > 0)

    # Exactly one word, with GO=1. 0x5841 is the golden config word for
    # 64ch/2000Hz/monopolar/16-bit.
    #
    # Not 0x5840 first. Measured on an SE004 (firmware 5.24): GO=1 alone streams
    # at 233.8 kB/s, while settings-then-GO makes the device close the connection
    # having sent nothing, with or without a gap between the writes. GO=0 is the
    # stop command and the device honours it by hanging up, so the driver used to
    # kill every connection with its own first write.
    assert received_cmd and received_cmd[0] == bytes([0x58, 0x41]), (
        f"expected one GO=1 word, got {received_cmd[0].hex(' ') if received_cmd else 'nothing'}"
    )

    # The accessory width was probed from the counter, not assumed.
    assert src._identified
    assert src._geo.n_accessory == 8
    assert src.dropped_samples == 0

    src.disconnect()
    thread.join(timeout=2.0)


def test_loopback_reports_dropped_samples():
    """Splicing out a chunk mid-stream is invisible except via the counter."""
    payload = bytearray(_FIXTURE.read_bytes())
    frame = 72 * 2
    # Drop samples 64..95 -- the stream stays byte-aligned, so only the ramp
    # counter reveals that 32 samples never arrived.
    del payload[64 * frame : 96 * frame]

    src = SessantaquattroSource(host_ip="127.0.0.1", port=0)
    src.connect_listen()
    port = src._server.getsockname()[1]

    thread = _fake_device(port, bytes(payload), [], repeats=1)
    thread.start()
    src.accept_and_start()

    data, _ = _pull(src)
    assert data is not None
    assert src.dropped_samples == 32
    assert src.dropout_events == 1

    src.disconnect()
    thread.join(timeout=2.0)


def test_exported_from_package_root():
    from myogestic.sources.otb import SessantaquattroSource as S

    assert S is SessantaquattroSource


def test_rejects_invalid_modes():
    with pytest.raises(ValueError, match="nch_mode"):
        SessantaquattroSource(nch_mode=9)
    with pytest.raises(ValueError, match="fs_mode"):
        SessantaquattroSource(fs_mode=9)
    with pytest.raises(ValueError, match="mode must be one of"):
        SessantaquattroSource(mode="quadripolar")
