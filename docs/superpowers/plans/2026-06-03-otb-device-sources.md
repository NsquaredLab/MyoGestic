# OTB Device Sources (Muovi + Quattrocento) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native, pure-Python (no Qt) `Source` implementations for OT Bioelettronica Muovi/Muovi+ and Quattrocento devices, restoring pre-2.0 hardware connectivity to MyoGestic 2.0.

**Architecture:** A self-contained `myogestic/sources/otb/` package. Pure decode functions (`_decode.py`) and CRC (`_crc.py`) are unit-tested without hardware; a shared `_OTBSource` base (`_base.py`) owns socket lifecycle, frame buffering, timestamping, and the pull-based `Source` Protocol; thin per-device classes (`muovi.py`, `quattrocento.py`) supply socket role, config bytes, frame geometry, and conversion factors. Loopback tests stand up a fake device over a real TCP socket. Constants and the wire protocol are taken from manufacturer docs + OTB MATLAB reference (`docs/reference/otb/`).

**Tech Stack:** Python 3.12+, stdlib `socket`/`struct`, NumPy, `mne_lsl.lsl.local_clock` (already a dependency), pytest, `uv run`.

**Spec:** `docs/superpowers/specs/2026-06-03-otb-device-sources-design.md`

**Scope:** This plan covers the two device sources + tests + an example + a docs page. **Out of scope (separate follow-up plans):** the GUI device-config panel + manual-connect acquire-loop change (spec §7), and the SyncStation multi-probe path (spec §11).

**Conventions to follow (from the existing codebase):**
- A `Source` is a plain class (structural `typing.Protocol` — no base-class inheritance required by the framework). Methods: `connect() -> StreamInfo`, `read() -> tuple[np.ndarray | None, np.ndarray | None]`, `disconnect() -> None`; optional `discover() -> list[dict[str, str]]`, `reconnect(target: str | None = None) -> StreamInfo`.
- `read()` returns `(data, ts)` with `data` shape `(n_samples, n_channels)` float32 (sample-major) and `ts` shape `(n_samples,)` float64 in `mne_lsl.lsl.local_clock()` seconds; `(None, None)` when nothing is ready.
- `StreamInfo(n_channels: int, fs: float, dtype=np.dtype(np.float32), channel_names: list[str] | None = None)` from `myogestic.stream`.
- Tests live in `tests/`, pytest, run with `uv run pytest`.

---

## File Structure

```
myogestic/sources/otb/
  __init__.py          # exports MuoviSource, QuattrocentoSource
  _crc.py              # crc8() — poly 0x8C, LSB-first, init 0
  _decode.py           # pure bytes -> (n_samples, n_channels) float32 decoders
  _constants.py        # device geometry, conversion factors, command builders
  _base.py             # _OTBSource: socket lifecycle + buffering + Source protocol
  muovi.py             # MuoviSource (TCP server role)
  quattrocento.py      # QuattrocentoSource (TCP client role)
tests/
  test_otb_crc.py
  test_otb_decode.py
  test_otb_muovi_loopback.py
  test_otb_quattrocento_loopback.py
examples/otb/
  muovi_emg.py
docs/how-to/
  connect-otb-devices.md
```

---

## Task 1: CRC-8 (`_crc.py`)

The SyncStation and Quattrocento framed commands end in a CRC-8 (poly 140 = `0x8C`, LSB-first, init 0). Ground truth: `docs/reference/otb/CRC8.m`.

**Files:**
- Create: `myogestic/sources/otb/__init__.py` (empty for now)
- Create: `myogestic/sources/otb/_crc.py`
- Test: `tests/test_otb_crc.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_otb_crc.py
from myogestic.sources.otb._crc import crc8


def test_crc8_empty_is_zero():
    assert crc8(bytes()) == 0


def test_crc8_matches_matlab_reference_algorithm():
    # Reimplement docs/reference/otb/CRC8.m exactly and compare on a
    # representative 39-byte Quattrocento config prefix.
    def matlab_crc8(data: bytes) -> int:
        crc = 0
        for byte in data:
            extract = byte
            for _ in range(8):
                s = (crc % 2) ^ (extract % 2)
                crc //= 2
                if s:
                    crc ^= 140  # 0x8C, matching the dec2bin(140,8) XOR in CRC8.m
                extract //= 2
            crc &= 0xFF
        return crc

    sample = bytes([0x80 | 8 | 6 | 1, 0, 0] + [0, 0, 0x14] * 12)  # 39 bytes
    assert len(sample) == 39
    assert crc8(sample) == matlab_crc8(sample)


def test_crc8_single_byte_known_value():
    # crc8 of a single zero byte stays 0 (no set bits to fold).
    assert crc8(bytes([0x00])) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_crc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'myogestic.sources.otb._crc'`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/__init__.py
# (intentionally empty for now; populated in Task 6 / Task 10)
```

```python
# myogestic/sources/otb/_crc.py
"""CRC-8 used by OTB framed commands (SyncStation, Quattrocento).

Polynomial 0x8C, init 0, LSB-first. Ported verbatim from OT Bioelettronica's
``CRC8.m`` (see docs/reference/otb/CRC8.m).
"""
from __future__ import annotations


def crc8(data: bytes) -> int:
    """Return the OTB CRC-8 over ``data`` (poly 0x8C, init 0, LSB-first)."""
    crc = 0
    for byte in data:
        extract = byte
        for _ in range(8):
            summ = (crc & 1) ^ (extract & 1)
            crc >>= 1
            if summ:
                crc ^= 0x8C
            extract >>= 1
    return crc & 0xFF
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_crc.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/__init__.py myogestic/sources/otb/_crc.py tests/test_otb_crc.py
git commit -m "feat(otb): add CRC-8 for OTB framed commands"
```

---

## Task 2: Muovi frame decode (`_decode.py`)

Pure functions: raw frame bytes → `(n_samples, n_channels)` float32. Muovi is **big-endian, 2's-complement**, channels-contiguous per sample-instant (Fortran layout). EMG = int16, EEG = int24. Ground truth: `docs/reference/otb/Read_muovi.m`.

**Files:**
- Create: `myogestic/sources/otb/_decode.py`
- Test: `tests/test_otb_decode.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_otb_decode.py
import numpy as np

from myogestic.sources.otb._decode import decode_be_int16, decode_be_int24


def _be_int16_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "big", signed=False)
    return bytes(out)


def _be_int24_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFFFF).to_bytes(3, "big", signed=False)
    return bytes(out)


def test_decode_be_int16_shape_and_order():
    # 3 channels, 2 samples. Wire order is channels-contiguous per sample:
    # [c0t0, c1t0, c2t0, c0t1, c1t1, c2t1]
    raw = _be_int16_bytes([10, 20, 30, 11, 21, 31])
    out = decode_be_int16(raw, n_channels=3)
    assert out.shape == (2, 3)              # sample-major
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out[0], [10, 20, 30])
    np.testing.assert_array_equal(out[1], [11, 21, 31])


def test_decode_be_int16_twos_complement():
    raw = _be_int16_bytes([-1, -32768, 32767])
    out = decode_be_int16(raw, n_channels=3)
    np.testing.assert_array_equal(out[0], [-1, -32768, 32767])


def test_decode_be_int24_twos_complement():
    raw = _be_int24_bytes([-1, 8388607, -8388608])
    out = decode_be_int24(raw, n_channels=3)
    assert out.shape == (1, 3)
    np.testing.assert_array_equal(out[0], [-1, 8388607, -8388608])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: FAIL with `ModuleNotFoundError` / `cannot import name 'decode_be_int16'`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/_decode.py
"""Pure decoders: raw OTB frame bytes -> (n_samples, n_channels) float32.

OTB streams are channels-contiguous per sample-instant (Fortran/column-major
when shaped (n_channels, n_samples)); we transpose to sample-major to match the
MyoGestic Source contract. Muovi is big-endian; Quattrocento is little-endian
(see decode_le_int16 in Task 7).
"""
from __future__ import annotations

import numpy as np


def decode_be_int16(raw: bytes, n_channels: int) -> np.ndarray:
    """Big-endian signed int16, channels-contiguous -> (n_samples, n_channels) f32."""
    flat = np.frombuffer(raw, dtype=">i2").astype(np.float32)
    return flat.reshape(n_channels, -1, order="F").T


def decode_be_int24(raw: bytes, n_channels: int) -> np.ndarray:
    """Big-endian signed int24, channels-contiguous -> (n_samples, n_channels) f32.

    NumPy has no int24 dtype: read 3-byte groups MSB-first and sign-extend.
    """
    b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
    vals = (b[:, 0] << 16) | (b[:, 1] << 8) | b[:, 2]
    neg = vals >= 0x800000
    vals[neg] -= 0x1000000
    return vals.astype(np.float32).reshape(n_channels, -1, order="F").T
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/_decode.py tests/test_otb_decode.py
git commit -m "feat(otb): add big-endian Muovi frame decoders"
```

---

## Task 3: Muovi constants & control byte (`_constants.py`)

Encode the manufacturer geometry and the control byte `(EMG<<3) | (Mode<<1) | GO`. Ground truth: Muovi TCP Protocol v2.4 + `Read_muovi.m` (`Command = EMG*8 + Mode*2 + 1`, `ConvFact = 0.000286`).

**Files:**
- Create: `myogestic/sources/otb/_constants.py`
- Test: add to `tests/test_otb_decode.py` (reuse the file for pure-unit tests)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_decode.py
from myogestic.sources.otb import _constants as C


def test_muovi_control_byte_matches_matlab():
    # Read_muovi.m: Command = EMG*8 + Mode*2 + 1
    assert C.muovi_control_byte(emg=True, mode=0, go=True) == 0x09
    assert C.muovi_control_byte(emg=True, mode=1, go=True) == 0x0B
    assert C.muovi_control_byte(emg=False, mode=0, go=True) == 0x01
    # stop = clear GO bit
    assert C.muovi_control_byte(emg=True, mode=0, go=False) == 0x08


def test_muovi_geometry_mode0():
    geo = C.muovi_geometry(plus=False, emg=True, mode=0)
    assert geo.n_total == 38        # 32 bio + 6 aux
    assert geo.n_bio == 32
    assert geo.fs == 2000.0
    assert geo.bytes_per_sample == 2


def test_muovi_geometry_plus_eeg():
    geo = C.muovi_geometry(plus=True, emg=False, mode=0)
    assert geo.n_total == 70        # 64 bio + 6 aux
    assert geo.n_bio == 64
    assert geo.fs == 500.0
    assert geo.bytes_per_sample == 3


def test_muovi_conversion_factor_gain8_mv():
    assert C.MUOVI_CONV_FACTOR_MV == 0.000286
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: FAIL with `cannot import name '_constants'` / `AttributeError`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/_constants.py
"""OTB device geometry, conversion factors, and command builders.

Manufacturer-verified (Muovi TCP Protocol v2.4, MuoviLite manual v1.1,
Read_muovi.m v3.0). See docs/reference/otb/.
"""
from __future__ import annotations

from dataclasses import dataclass

# Muovi --------------------------------------------------------------------

MUOVI_PORT = 54321
# Gain-8 LSB in mV (286.1 nV). Read_muovi.m uses 0.000286.
MUOVI_CONV_FACTOR_MV = 0.000286
MUOVI_N_AUX = 6  # IMU quaternion W/X/Y/Z, buffer+trigger, sample counter

# NumChanVsMode from Read_muovi.m: [38 22 38 38] (Muovi), Muovi+ adds 32 bio.
_MUOVI_BIO_BY_MODE = {0: 32, 1: 16, 2: 32, 3: 32}
_MUOVIPLUS_BIO_BY_MODE = {0: 64, 1: 32, 2: 64, 3: 64}


@dataclass(frozen=True)
class MuoviGeometry:
    n_total: int          # channels per sample-instant on the wire
    n_bio: int            # biosignal channels (first n_bio rows)
    n_aux: int            # auxiliary channels (always 6)
    fs: float             # 2000 (EMG) or 500 (EEG)
    bytes_per_sample: int  # 2 (EMG, int16) or 3 (EEG, int24)


def muovi_geometry(*, plus: bool, emg: bool, mode: int) -> MuoviGeometry:
    """Channel/rate/width geometry for a (device, working-mode, detection-mode)."""
    bio_table = _MUOVIPLUS_BIO_BY_MODE if plus else _MUOVI_BIO_BY_MODE
    n_bio = bio_table[mode]
    fs = 2000.0 if emg else 500.0
    bps = 2 if emg else 3
    return MuoviGeometry(
        n_total=n_bio + MUOVI_N_AUX,
        n_bio=n_bio,
        n_aux=MUOVI_N_AUX,
        fs=fs,
        bytes_per_sample=bps,
    )


def muovi_control_byte(*, emg: bool, mode: int, go: bool) -> int:
    """Muovi control byte: (EMG<<3) | (mode<<1) | GO. (Read_muovi.m formula.)"""
    return (int(emg) << 3) | ((mode & 0x3) << 1) | int(go)


def muovi_channel_names(geo: MuoviGeometry) -> list[str]:
    """Per-channel labels: bio then the 6 named aux channels."""
    names = [f"bio{i}" for i in range(geo.n_bio)]
    names += ["imu_w", "imu_x", "imu_y", "imu_z", "buffer_trigger", "counter"]
    return names
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/_constants.py tests/test_otb_decode.py
git commit -m "feat(otb): add Muovi geometry + control-byte constants"
```

---

## Task 4: `_OTBSource` base (`_base.py`)

Owns the read-side: a byte accumulator, complete-frame slicing, decode dispatch, and per-frame timestamp generation (`local_clock()` back-dated by `1/fs`). Subclasses provide socket setup (`_open`), start/stop commands (`_send_start`/`_send_stop`), `_frame_nbytes`, `_decode(frame) -> (n_samples_in_frame, n_channels)`, and the `StreamInfo`.

**Files:**
- Create: `myogestic/sources/otb/_base.py`
- Test: `tests/test_otb_decode.py` (drive the base with a tiny fake subclass — no socket)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_decode.py
from myogestic.sources.otb._base import _OTBSource
from myogestic.stream import StreamInfo


class _FakeOTB(_OTBSource):
    """Drives the base buffering/decoding without a real socket."""
    def __init__(self):
        super().__init__()
        self._info = StreamInfo(n_channels=2, fs=4.0)
        self._frame_nbytes = 2 * 2  # 2 channels x 1 sample x int16

    def _open(self):
        return self._info

    def _send_start(self):  # no-op for the fake
        pass

    def _send_stop(self):
        pass

    def _decode(self, frame: bytes):
        return decode_be_int16(frame, n_channels=2)

    # test helper: push bytes into the accumulator as if recv'd
    def feed(self, raw: bytes):
        self._buf.extend(raw)


def test_base_drain_returns_complete_frames_only():
    src = _FakeOTB()
    src.connect()
    # one and a half frames -> only the complete frame comes out
    src.feed(_be_int16_bytes([5, 6]) + _be_int16_bytes([7])[:2])
    data, ts = src._drain()
    assert data.shape == (1, 2)
    np.testing.assert_array_equal(data[0], [5, 6])
    assert ts.shape == (1,)
    # leftover (partial frame) stays buffered
    assert len(src._buf) == 2


def test_base_read_returns_none_when_empty():
    src = _FakeOTB()
    src.connect()
    assert src.read() == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: FAIL with `cannot import name '_OTBSource'`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/_base.py
"""Shared base for OTB socket sources.

Owns the pull-side machinery common to every OTB device: a byte accumulator
fed from the socket, complete-frame slicing, decode dispatch, and per-frame
timestamping. Subclasses implement the socket/protocol specifics.
"""
from __future__ import annotations

import socket

import numpy as np
from mne_lsl.lsl import local_clock

from myogestic.stream import StreamInfo


class _OTBSource:
    """Base class for OTB device sources (Muovi, Quattrocento).

    Subclasses must set ``self._info`` (StreamInfo) and ``self._frame_nbytes``
    in ``_open()``, and implement ``_open``/``_send_start``/``_send_stop``/
    ``_decode``. ``self._sock`` is the connected/accepted socket used by
    ``read`` for non-blocking recv.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._info: StreamInfo | None = None
        self._frame_nbytes: int = 0

    # --- subclass hooks -----------------------------------------------------
    def _open(self) -> StreamInfo:
        raise NotImplementedError

    def _send_start(self) -> None:
        raise NotImplementedError

    def _send_stop(self) -> None:
        raise NotImplementedError

    def _decode(self, frame: bytes) -> np.ndarray:
        raise NotImplementedError

    # --- Source protocol ----------------------------------------------------
    def connect(self) -> StreamInfo:
        self._buf.clear()
        info = self._open()
        self._info = info
        self._send_start()
        return info

    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        if self._sock is not None:
            try:
                chunk = self._sock.recv(65536)
                if chunk:
                    self._buf.extend(chunk)
            except BlockingIOError:
                pass
            except OSError:
                return None, None
        return self._drain()

    def disconnect(self) -> None:
        if self._sock is not None:
            try:
                self._send_stop()
            except OSError:
                pass
            try:
                self._sock.close()
            finally:
                self._sock = None
        self._buf.clear()

    # --- internals ----------------------------------------------------------
    def _drain(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """Slice all complete frames out of the buffer, decode, timestamp."""
        if self._frame_nbytes <= 0 or len(self._buf) < self._frame_nbytes:
            return None, None
        n_frames = len(self._buf) // self._frame_nbytes
        take = n_frames * self._frame_nbytes
        raw = bytes(self._buf[:take])
        del self._buf[:take]
        data = self._decode(raw)
        n = data.shape[0]
        fs = float(self._info.fs)
        end = local_clock()
        ts = end - (np.arange(n - 1, -1, -1, dtype=np.float64) / fs)
        return data, ts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/_base.py tests/test_otb_decode.py
git commit -m "feat(otb): add _OTBSource base (buffering, framing, timestamps)"
```

---

## Task 5: `MuoviSource` (`muovi.py`) + loopback test

Muovi = PC is **TCP server** on 54321; the probe dials in. `connect()` binds/listens/accepts, returns `StreamInfo`, then `_send_start()` writes the control byte. Conversion to mV applied to bio (and unscaled aux). Loopback test: a fake "probe" connects as client and streams synthetic frames.

**Files:**
- Create: `myogestic/sources/otb/muovi.py`
- Test: `tests/test_otb_muovi_loopback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_otb_muovi_loopback.py
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
```

> Note: the test uses two small test-only entry points (`connect_listen`, `accept_and_start`) so the bind and the blocking `accept` can be separated in a single-threaded test. In normal use `connect()` does both (bind+listen+accept+start).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_muovi_loopback.py -v`
Expected: FAIL with `ModuleNotFoundError: ...otb.muovi`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/muovi.py
"""MuoviSource — native pure-Python source for OTB Muovi / Muovi+.

PC is the TCP server on port 54321; the probe connects in as client (in AP
mode the probe is the WiFi access point and DHCP-assigns the PC). Big-endian
int16 (EMG) / int24 (EEG); see docs/reference/otb/Read_muovi.m.
"""
from __future__ import annotations

import socket

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_be_int16, decode_be_int24
from myogestic.stream import StreamInfo


class MuoviSource(_OTBSource):
    """Connect to an OTB Muovi / Muovi+ probe over TCP.

    Args:
        host_ip: Local interface to bind the server socket. ``""`` binds all.
        port: TCP port to listen on (default 54321). ``0`` picks a free port
            (used in tests).
        plus: ``True`` for Muovi+ (64 bio channels), ``False`` for Muovi (32).
        emg: ``True`` = EMG (2000 Hz, 16-bit), ``False`` = EEG (500 Hz, 24-bit).
        mode: Detection mode 0..3. ``0`` = monopolar gain 8 (default; the only
            unambiguous mode across firmware). Avoid mode 1 (firmware-dependent).
        include_aux: Append the 6 aux channels (IMU/buffer/counter) unscaled.
        accept_timeout: Seconds to wait for the probe to dial in.
    """

    def __init__(
        self,
        host_ip: str = "",
        port: int = C.MUOVI_PORT,
        *,
        plus: bool = False,
        emg: bool = True,
        mode: int = 0,
        include_aux: bool = False,
        accept_timeout: float = 30.0,
    ) -> None:
        super().__init__()
        self._host_ip = host_ip
        self._port = port
        self._plus = plus
        self._emg = emg
        self._mode = mode
        self._include_aux = include_aux
        self._accept_timeout = accept_timeout
        self._server: socket.socket | None = None
        self._geo = C.muovi_geometry(plus=plus, emg=emg, mode=mode)

    # --- normal entry point -------------------------------------------------
    def connect(self) -> StreamInfo:
        """Bind+listen, accept the probe, send the start command."""
        self.connect_listen()
        return self.accept_and_start()

    # --- split entry points (also used by tests) ----------------------------
    def connect_listen(self) -> None:
        """Bind and listen; returns immediately (does not block on accept)."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host_ip, self._port))
        self._server.listen(1)

    def accept_and_start(self) -> StreamInfo:
        """Block until the probe connects, then open + send the start command.

        Runs the base lifecycle inline (NOT via base ``connect()``) because the
        server socket / accept is Muovi-specific.
        """
        self._server.settimeout(self._accept_timeout)
        conn, _addr = self._server.accept()
        conn.setblocking(False)
        self._sock = conn
        info = self._open()
        self._info = info
        self._send_start()
        return info

    # --- base hooks ---------------------------------------------------------
    def _open(self) -> StreamInfo:
        self._buf.clear()
        n_out = self._geo.n_total if self._include_aux else self._geo.n_bio
        self._frame_nbytes = self._geo.n_total * self._geo.bytes_per_sample
        return StreamInfo(
            n_channels=n_out,
            fs=self._geo.fs,
            dtype=np.dtype(np.float32),
            channel_names=C.muovi_channel_names(self._geo)[:n_out],
        )

    def _send_start(self) -> None:
        cmd = C.muovi_control_byte(emg=self._emg, mode=self._mode, go=True)
        self._sock.sendall(bytes([cmd]))

    def _send_stop(self) -> None:
        cmd = C.muovi_control_byte(emg=self._emg, mode=self._mode, go=False)
        self._sock.sendall(bytes([cmd]))

    def _decode(self, frame: bytes) -> np.ndarray:
        if self._geo.bytes_per_sample == 2:
            full = decode_be_int16(frame, n_channels=self._geo.n_total)
        else:
            full = decode_be_int24(frame, n_channels=self._geo.n_total)
        bio = full[:, : self._geo.n_bio] * np.float32(C.MUOVI_CONV_FACTOR_MV)
        if not self._include_aux:
            return bio
        aux = full[:, self._geo.n_bio :]  # unscaled IMU/buffer/counter
        return np.concatenate([bio, aux], axis=1).astype(np.float32)

    def disconnect(self) -> None:
        super().disconnect()
        if self._server is not None:
            try:
                self._server.close()
            finally:
                self._server = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_muovi_loopback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/muovi.py tests/test_otb_muovi_loopback.py
git commit -m "feat(otb): add MuoviSource (TCP server, big-endian decode)"
```

---

## Task 6: Export `MuoviSource` + public-API test

**Files:**
- Modify: `myogestic/sources/otb/__init__.py`
- Test: `tests/test_otb_muovi_loopback.py` (add an import test)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_muovi_loopback.py
def test_muovi_source_importable_from_package():
    from myogestic.sources.otb import MuoviSource as M
    assert M is MuoviSource
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_muovi_loopback.py::test_muovi_source_importable_from_package -v`
Expected: FAIL with `ImportError: cannot import name 'MuoviSource'`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/__init__.py
from myogestic.sources.otb.muovi import MuoviSource

__all__ = ["MuoviSource"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_muovi_loopback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/__init__.py tests/test_otb_muovi_loopback.py
git commit -m "feat(otb): export MuoviSource from package"
```

---

## Task 7: Quattrocento decode (`_decode.py`)

Quattrocento is **little-endian int16**, channels-contiguous per sample-instant.

**Files:**
- Modify: `myogestic/sources/otb/_decode.py`
- Test: `tests/test_otb_decode.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_decode.py
from myogestic.sources.otb._decode import decode_le_int16


def _le_int16_bytes(values):
    out = bytearray()
    for v in values:
        out += int(v & 0xFFFF).to_bytes(2, "little", signed=False)
    return bytes(out)


def test_decode_le_int16_shape_order_and_sign():
    raw = _le_int16_bytes([1, 2, 3, -1, -2, -3])  # 3 ch, 2 samples
    out = decode_le_int16(raw, n_channels=3)
    assert out.shape == (2, 3)
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out[0], [1, 2, 3])
    np.testing.assert_array_equal(out[1], [-1, -2, -3])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: FAIL with `cannot import name 'decode_le_int16'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to myogestic/sources/otb/_decode.py
def decode_le_int16(raw: bytes, n_channels: int) -> np.ndarray:
    """Little-endian signed int16, channels-contiguous -> (n_samples, n_channels) f32."""
    flat = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    return flat.reshape(n_channels, -1, order="F").T
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/_decode.py tests/test_otb_decode.py
git commit -m "feat(otb): add little-endian Quattrocento decoder"
```

---

## Task 8: Quattrocento config builder (`_constants.py`)

Build the 40-byte config string with CRC-8. Ground truth: Quattrocento Configuration Protocol v1.7 + `Read_Quattrocento.m`.

**Files:**
- Modify: `myogestic/sources/otb/_constants.py`
- Test: `tests/test_otb_decode.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_decode.py
def test_quattro_channel_counts_and_factors():
    assert C.QUATTRO_NCH_BY_MODE == {0: 120, 1: 216, 2: 312, 3: 408}
    assert C.QUATTRO_FS_BY_MODE == {0: 512.0, 1: 2048.0, 2: 5120.0, 3: 10240.0}
    assert abs(C.QUATTRO_CONV_FACTOR_MV - (5 / 2 ** 16 / 150 * 1000)) < 1e-12


def test_quattro_config_is_40_bytes_with_valid_crc():
    cfg = C.quattro_config(fs_mode=1, nch_mode=3, acq_on=True)
    assert len(cfg) == 40
    # byte0 = 0x80 | fsamp(01<<3=8) | nch(11<<1=6) | acq_on(1) = 0x80|8|6|1
    assert cfg[0] == (0x80 | 8 | 6 | 1)
    # CRC trailer is valid over the first 39 bytes
    assert cfg[39] == C.crc8(cfg[:39])


def test_quattro_stop_config_byte0():
    cfg = C.quattro_config(fs_mode=1, nch_mode=3, acq_on=False)
    assert cfg[0] == 0x80
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: FAIL with `AttributeError: ... 'quattro_config'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to myogestic/sources/otb/_constants.py
from myogestic.sources.otb._crc import crc8  # re-exported for callers/tests

# Quattrocento -------------------------------------------------------------

QUATTRO_IP = "169.254.1.10"
QUATTRO_PORT = 23456
QUATTRO_FS_BY_MODE = {0: 512.0, 1: 2048.0, 2: 5120.0, 3: 10240.0}
QUATTRO_NCH_BY_MODE = {0: 120, 1: 216, 2: 312, 3: 408}
# Read_Quattrocento.m: GainFactor = 5/2^16/150*1000 (mV); AuxGain = 5/2^16/0.5 (V)
QUATTRO_CONV_FACTOR_MV = 5 / 2 ** 16 / 150 * 1000
QUATTRO_AUX_FACTOR_V = 5 / 2 ** 16 / 0.5
# Default per-input CONF2 (Read_Quattrocento.m = 0x14): monopolar, HPF 10Hz, LPF 500Hz
_QUATTRO_DEFAULT_CONF2 = 0x14


def quattro_config(
    *,
    fs_mode: int,
    nch_mode: int,
    acq_on: bool,
    decim: bool = False,
    rec_on: bool = False,
    conf2: int = _QUATTRO_DEFAULT_CONF2,
) -> bytes:
    """Build the 40-byte Quattrocento config string (with CRC-8 trailer)."""
    acq_sett = (
        0x80
        | (int(decim) << 6)
        | (int(rec_on) << 5)
        | ((fs_mode & 0x3) << 3)
        | ((nch_mode & 0x3) << 1)
        | int(acq_on)
    )
    cfg = bytearray(40)
    cfg[0] = acq_sett
    cfg[1] = 0  # AN_OUT_IN_SEL (analog out unused)
    cfg[2] = 0  # AN_OUT_CH_SEL
    for i in range(12):  # 8 IN + 4 MULTIPLE IN, 3 bytes each: CONF0/1/2
        base = 3 + i * 3
        cfg[base + 0] = 0          # CONF0 muscle
        cfg[base + 1] = 0          # CONF1 sensor+adapter
        cfg[base + 2] = conf2 & 0xFF
    cfg[39] = crc8(bytes(cfg[:39]))
    return bytes(cfg)


def quattro_channel_names(nch_total: int, n_bio: int) -> list[str]:
    names = [f"bio{i}" for i in range(n_bio)]
    names += [f"ch{i}" for i in range(n_bio, nch_total)]
    # last 8 accessory: counter @ -7, trigger @ -6, buffer @ -4
    names[-7] = "counter"
    names[-6] = "trigger"
    names[-4] = "buffer"
    return names
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_decode.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/_constants.py tests/test_otb_decode.py
git commit -m "feat(otb): add Quattrocento 40-byte config builder"
```

---

## Task 9: `QuattrocentoSource` (`quattrocento.py`) + loopback test

Quattrocento = PC is **TCP client** to `169.254.1.10:23456`. `connect()` dials the device, sends the 40-byte config with `ACQ_ON`. Loopback test: a fake server accepts, validates the 40-byte config length + CRC, and streams synthetic frames.

**Files:**
- Create: `myogestic/sources/otb/quattrocento.py`
- Test: `tests/test_otb_quattrocento_loopback.py`

- [ ] **Step 1: Write the failing test**

```python
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
        for _ in range(50):
            conn.sendall(frame)
            time.sleep(0.005)
        time.sleep(0.2)
        conn.close()

    t = threading.Thread(target=fake_device, daemon=True)
    t.start()

    src = QuattrocentoSource(device_ip="127.0.0.1", port=port,
                             fs_mode=0, nch_mode=0, n_bio=64)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_quattrocento_loopback.py -v`
Expected: FAIL with `ModuleNotFoundError: ...otb.quattrocento`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/quattrocento.py
"""QuattrocentoSource — native pure-Python source for the OTB Quattrocento.

PC is the TCP client to the amplifier (default 169.254.1.10:23456). Config is
a 40-byte CRC-8-terminated string; data is little-endian int16. See
docs/reference/otb/Read_Quattrocento.m.
"""
from __future__ import annotations

import socket

import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb._base import _OTBSource
from myogestic.sources.otb._decode import decode_le_int16
from myogestic.stream import StreamInfo


class QuattrocentoSource(_OTBSource):
    """Connect to an OTB Quattrocento amplifier over TCP.

    Args:
        device_ip: Amplifier IP (default link-local 169.254.1.10). The host NIC
            must have a 169.254.x.x address on that segment.
        port: TCP port (default 23456).
        fs_mode: 0..3 -> 512 / 2048 / 5120 / 10240 Hz.
        nch_mode: 0..3 -> 120 / 216 / 312 / 408 streamed channels.
        n_bio: Number of biosignal channels to expose (the grid channels at the
            front of the stream). Defaults to all non-accessory channels.
        include_aux: Append the AUX IN + accessory channels (unscaled).
        connect_timeout: Seconds to wait for the TCP connect.
    """

    def __init__(
        self,
        device_ip: str = C.QUATTRO_IP,
        port: int = C.QUATTRO_PORT,
        *,
        fs_mode: int = 1,
        nch_mode: int = 1,
        n_bio: int | None = None,
        include_aux: bool = False,
        connect_timeout: float = 10.0,
    ) -> None:
        super().__init__()
        self._device_ip = device_ip
        self._port = port
        self._fs_mode = fs_mode
        self._nch_mode = nch_mode
        self._include_aux = include_aux
        self._connect_timeout = connect_timeout
        self._nch_total = C.QUATTRO_NCH_BY_MODE[nch_mode]
        # default: everything except the 8 accessory channels is "bio"
        self._n_bio = n_bio if n_bio is not None else self._nch_total - 8

    # --- base hooks ---------------------------------------------------------
    def _open(self) -> StreamInfo:
        self._buf.clear()
        sock = socket.create_connection(
            (self._device_ip, self._port), timeout=self._connect_timeout
        )
        sock.setblocking(False)
        self._sock = sock
        self._frame_nbytes = self._nch_total * 2  # int16, one sample-instant
        n_out = self._nch_total if self._include_aux else self._n_bio
        return StreamInfo(
            n_channels=n_out,
            fs=C.QUATTRO_FS_BY_MODE[self._fs_mode],
            dtype=np.dtype(np.float32),
            channel_names=C.quattro_channel_names(self._nch_total, self._n_bio)[:n_out],
        )

    def _send_start(self) -> None:
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=True)
        self._sock.sendall(cfg)

    def _send_stop(self) -> None:
        cfg = C.quattro_config(fs_mode=self._fs_mode, nch_mode=self._nch_mode,
                               acq_on=False)
        self._sock.sendall(cfg)

    def _decode(self, frame: bytes) -> np.ndarray:
        full = decode_le_int16(frame, n_channels=self._nch_total)
        bio = full[:, : self._n_bio] * np.float32(C.QUATTRO_CONV_FACTOR_MV)
        if not self._include_aux:
            return bio
        rest = full[:, self._n_bio :]  # AUX IN + accessory, unscaled
        return np.concatenate([bio, rest], axis=1).astype(np.float32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_quattrocento_loopback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/quattrocento.py tests/test_otb_quattrocento_loopback.py
git commit -m "feat(otb): add QuattrocentoSource (TCP client, little-endian decode)"
```

---

## Task 10: Export `QuattrocentoSource`

**Files:**
- Modify: `myogestic/sources/otb/__init__.py`
- Test: `tests/test_otb_quattrocento_loopback.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_otb_quattrocento_loopback.py
def test_quattrocento_importable_from_package():
    from myogestic.sources.otb import QuattrocentoSource as Q
    assert Q is QuattrocentoSource
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_otb_quattrocento_loopback.py::test_quattrocento_importable_from_package -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# myogestic/sources/otb/__init__.py
from myogestic.sources.otb.muovi import MuoviSource
from myogestic.sources.otb.quattrocento import QuattrocentoSource

__all__ = ["MuoviSource", "QuattrocentoSource"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_otb_quattrocento_loopback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add myogestic/sources/otb/__init__.py tests/test_otb_quattrocento_loopback.py
git commit -m "feat(otb): export QuattrocentoSource from package"
```

---

## Task 11: Example + docs

**Files:**
- Create: `examples/otb/muovi_emg.py`
- Create: `docs/how-to/connect-otb-devices.md`

- [ ] **Step 1: Write the example**

```python
# examples/otb/muovi_emg.py
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
```

- [ ] **Step 2: Write the docs page**

```markdown
# Connect OT Bioelettronica devices

MyoGestic talks to OTB Muovi/Muovi+ and Quattrocento natively — no Qt, no
external bridge. Each device is a `Source` you drop into a `Stream`.

## Muovi / Muovi+ (Wi-Fi)

The PC is the TCP **server**; the probe connects to it.

1. Hold the probe button ~5 s → it becomes a Wi-Fi access point `MVxxx-ID`.
2. Join that network from the PC.
3. ```python
   from myogestic import Stream
   from myogestic.sources.otb import MuoviSource
   stream = Stream("emg", source=MuoviSource(plus=False, emg=True, mode=0),
                   window_seconds=1.0)
   stream.start()
   ```

Defaults: 32-ch (Muovi) monopolar gain-8 EMG @ 2000 Hz, biosignal-only
(286.1 nV/LSB → mV). Pass `plus=True` for 64-ch Muovi+, `emg=False` for EEG
(500 Hz, 24-bit), `include_aux=True` to also stream IMU/buffer/counter.

## Quattrocento (Ethernet)

The PC is the TCP **client** to the amplifier (default `169.254.1.10:23456`).
Give the PC NIC a `169.254.x.x` address on that segment.

```python
from myogestic.sources.otb import QuattrocentoSource
stream = Stream("emg", source=QuattrocentoSource(fs_mode=1, nch_mode=1),
                window_seconds=1.0)  # 2048 Hz, 216 streamed ch
stream.start()
```

`nch_mode` 0..3 → 120/216/312/408 streamed channels; `fs_mode` 0..3 →
512/2048/5120/10240 Hz. Always stop the stream before reconnecting.

> Protocol references: `docs/reference/otb/`.
```

- [ ] **Step 3: Smoke-check the example imports**

Run: `uv run python -c "import ast; ast.parse(open('examples/otb/muovi_emg.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run the full OTB test suite**

Run: `uv run pytest tests/test_otb_crc.py tests/test_otb_decode.py tests/test_otb_muovi_loopback.py tests/test_otb_quattrocento_loopback.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add examples/otb/muovi_emg.py docs/how-to/connect-otb-devices.md
git commit -m "docs(otb): add Muovi/Quattrocento example + how-to"
```

---

## Follow-up plans (out of scope here)

1. **GUI device-config panel** (spec §7): source-agnostic `config_spec()`/`set_config()` optional Protocol extension + a generic `device_config` ImGui widget (Apply & Connect via `reconnect()`), plus the minimal manual-connect acquire-loop change (per-stream flag so LSL/Replay are untouched).
2. **SyncStation multi-probe path** (spec §11): a `SyncStationSource` (TCP client to `192.168.76.1:54320`, CRC-framed `START + CONTROL BYTEs` command builder) on the same `_OTBSource` base; needs its own channel-map verification.
3. **SessantaquattroSource** on the same base (Muovi-family protocol), validated when hardware is available.
4. **Hardware validation pass:** run Muovi (TEST mode `mode=3` ramps to confirm decode/endianness) and Quattrocento against real devices; capture a short byte dump into `docs/reference/otb/` as a regression fixture.
