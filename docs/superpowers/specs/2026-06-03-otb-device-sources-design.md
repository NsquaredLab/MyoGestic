# Design: Native OT Bioelettronica (OTB) Device Sources for MyoGestic 2.0

- **Date:** 2026-06-03
- **Author:** Raul C. Sîmpetru (with Claude)
- **Status:** Draft — pending review
- **Topic:** Re-add the ability to connect to OT Bioelettronica devices (Muovi/Muovi+, Quattrocento, later Sessantaquattro) that existed before the MyoGestic 2.0 rewrite.

## 1. Background

Pre-2.0, MyoGestic connected to OTB hardware through the external Qt library
`biosignal-device-interface` ("bdi", `github.com/NsquaredLab/Biosignal-Device-Interface`).
The Qt GUI embedded an `OTBDevicesWidget` that owned device selection, socket
connection, configuration, and streaming; MyoGestic subscribed to its Qt signals
(`biosignal_data_arrived`, `connect_toggled`, `stream_toggled`, …) and read
`get_device_information()` for `{sampling_frequency, samples_per_frame,
number_of_biosignal_channels}`.

The 2.0 rewrite replaced the **Qt** GUI with **Dear ImGui** and replaced the
signal-based device widget with a pull-based **`Source` Protocol**
(`myogestic/stream.py`):

```python
class Source(Protocol):
    def connect(self) -> StreamInfo: ...
    def read(self) -> tuple[np.ndarray | None, np.ndarray | None]: ...
    def disconnect(self) -> None: ...
    # optional: discover() -> list[dict[str,str]], reconnect(target) -> StreamInfo
```

bdi is fundamentally Qt-coupled (its device classes subclass `QObject`, use
`PySide6.QtNetwork` sockets, deliver data via Qt `Signal`s, and need a running
Qt event loop), so it cannot be cleanly reused in the deliberately Qt-free 2.0
app. `pyproject.toml` still carries an unused `bdi` optional extra (line 57).

**Decision (approved):** Approach **C** — reimplement the OTB devices as native,
pure-Python `Source`s using the stdlib `socket` module, borrowing the wire-
protocol constants from bdi. No Qt, no new runtime dependency.

## 2. Goals / Non-goals

**Goals**
- Connect to Muovi/Muovi+ and Quattrocento from inside MyoGestic 2.0 as `Source`s.
- Stay Qt-free and single-process; no new runtime dependencies (stdlib `socket` + `numpy`).
- Restore the "connect from MyoGestic" feel; get GUI status/scan/reconnect for free.
- Structure so Sessantaquattro (Muovi-family protocol) drops in later on the same base.

**Non-goals (v1)**
- Sessantaquattro implementation now (no test hardware available yet).
- Reusing bdi at runtime / reintroducing PySide6.

In-scope (added after review): an in-GUI device-configuration panel (working
mode, gain/detection, grids, fs) — see §7. Constructor kwargs remain the
underlying config; the GUI edits the same fields.

## 3. Architecture & file layout

Self-contained `myogestic/sources/otb/` package; thin device subclasses over a
shared base.

```
myogestic/sources/otb/
  __init__.py          # exports MuoviSource, QuattrocentoSource
  _base.py             # _OTBSource: socket lifecycle, frame buffering, Source Protocol
  _decode.py           # pure functions: bytes -> (n_samples, n_channels) float32
  _constants.py        # channel dicts, fs, conversion factors, command builders (from bdi)
  muovi.py             # MuoviSource(plus=False, ...)  — TCP SERVER role
  quattrocento.py      # QuattrocentoSource(...)        — TCP CLIENT role + CRC-8
```

`_base.py` owns everything common: socket open/close, the `read()` byte-buffer
accumulation + complete-frame slicing, float32 conversion, per-frame timestamp
generation, and the `connect/read/disconnect/discover/reconnect` surface. Each
device file supplies: config-command bytes, frame geometry, endianness,
conversion factors, socket role.

No new dependencies — `socket` (stdlib) + `numpy` (already core). The sources
need no `pyserial`/Qt/bdi, so they can ship in `sources/__init__.py` directly
(unlike `SerialSource`, which is opt-in for `pyserial`).

## 4. Source API & data contract

- `connect() -> StreamInfo`
  - **Muovi**: bind/listen on `(host_ip, 54321)`, `accept()` the device (it dials
    in), send idle config byte then start byte. Blocking is acceptable (matches
    `LSLSource.connect`, which blocks up to 10 s).
  - **Quattrocento**: `connect((device_ip, 23456))`, send the 40-byte config
    (with CRC) + start.
  - Returns `StreamInfo(n_channels, fs, dtype=np.float32, channel_names)`.
- `read() -> (data, ts)`: non-blocking poll. Drain socket into a `bytearray`,
  slice **complete** frames, decode to **`(n_samples, n_channels)` sample-major
  float32**. Return `(None, None)` when no full frame is ready.
- `disconnect()`: send stop (config byte `-1`; for Quattrocento recompute CRC),
  close sockets.
- **Channels**: biosignal-only by default; `include_aux=True` appends aux
  channels. `channel_names` labels biosignal (and aux, if included).
- **Timestamps**: device sends none. Per decoded frame of `N` samples, stamp with
  `t_end = mne_lsl.lsl.local_clock()` and back-date: `ts[i] = t_end - (N-1-i)/fs`,
  giving monotonic, `1/fs`-spaced timestamps in LSL clock units.

## 5. Wire protocol

Muovi/Muovi+ (§5.1) is verified against the **OTB Muovi probe TCP Protocol v2.4**,
**SyncStation TCP Protocol v2.8**, **MuoviPro User Manual v5.1**, and **MuoviLite
User Manual v1.1** (manufacturer PDFs); the control-byte layout, conversion
factors, big-endian byte order, and channel map here are authoritative and
supersede bdi where they differ. OTB also ships **MATLAB demo code** (linked from
the manuals) as the canonical decode reference. Quattrocento (§5.2) is still
**bdi-sourced only** (no manufacturer PDF yet) — provisional, verify before
phase 2.

### 5.1 Muovi / Muovi+
- **Socket role:** host (PC) is the **TCP server** on port **54321**; the Muovi
  dials in as client. *Confirmed by OTB Muovi TCP Protocol v2.4 + MuoviPro manual
  §8.1.5.* Two direct sub-cases: (a) **AP mode** — hold the probe button ~5 s; the
  probe becomes a WiFi access point and DHCP-assigns the PC an IP, then connects
  to the PC's server socket; (b) **infrastructure mode** — probe joins an existing
  network (set via its web page at `192.168.14.X`), PC still server on 54321.
  Data arrives in **~1400-byte TCP chunks** (not aligned to logical frames →
  partial-recv buffering is mandatory).
- **Handshake:** none; `accept()` then send config. Device streams only after a
  config byte with the acquisition LSB set.
- **Config — OFFICIAL single CONTROL BYTE** (Muovi TCP Protocol v2.4; this
  *supersedes* bdi's formula, which encodes the byte differently):
  ```
  bit7..4 = 0   bit3 = EMG/EEG   bits2-1 = MODE   bit0 = GO/STOP
  control = (emg_eeg << 3) | (mode << 1) | go
  ```
  - `EMG/EEG`: **1 = EMG** (2000 Hz, firmware HPF ~10 Hz, **16-bit**),
    **0 = EEG** (500 Hz, DC-coupled, **24-bit**).
  - `MODE` (bits 2-1): `00` = monopolar gain 8; `01` = monopolar gain 4
    (EMG only, fw ≥ 3.2.0; else treated as `00`); `10` = impedance check;
    `11` = test (ramps on all channels — ideal for validating decode/endianness).
  - `GO` (bit0): `1` = start streaming; `0` = stop **and the device closes the
    socket**.
  - Worked bytes: EMG+gain8 stream = `0x09`, stop `0x08`; EMG+gain4 = `0x0B`;
    EEG+gain8 = `0x01`.
  - Note: ⚠️ bdi's `(working_mode<<2)+detection_mode (+1)` produces *different*
    bytes (e.g. `0x0A` for EMG+gain8). **We follow the PDF, not bdi.**
- **Geometry:** Muovi = 32 biosignal + 6 aux = 38 total; Muovi+ = 64 + 6 = 70.

  | Device | Mode | total | bio | aux | Fs | bytes/sample | samples/frame | frame bytes |
  |---|---|---|---|---|---|---|---|---|
  | Muovi  | EMG | 38 | 32 | 6 | 2000 | 2 (int16) | 18 | 1368 |
  | Muovi  | EEG | 38 | 32 | 6 |  500 | 3 (int24) | 12 | 1368 |
  | Muovi+ | EMG | 70 | 64 | 6 | 2000 | 2 (int16) | 10 | 1400 |
  | Muovi+ | EEG | 70 | 64 | 6 |  500 | 3 (int24) |  6 | 1260 |

- **Sample format:** **big-endian, signed** — *explicitly confirmed* (MuoviLite
  manual §8.1.2: "the data format in both cases, 24 bit and 16 bit, is big
  endian"). EMG = int16 (high 16 bits, LSB still 286.1 nV → ±9.375 mV range);
  EEG = int24 (manual sign-extend). **All 38 channels — biosignal AND the 6 aux —
  share the active resolution**: 16-bit in EMG, 24-bit in EEG. So the decoder
  reads one uniform width per frame. Frame is Fortran-order
  `(n_channels, samples_per_frame)`: contiguous values are
  `[ch0_t0, ch1_t0, …, chN_t0, ch0_t1, …]`.
- **Conversion factor — MANUFACTURER-CONFIRMED** (Muovi TCP Protocol v2.4, ×
  raw → mV; same for bio & aux): gain 8 → **286.1 nV/LSB** (`286.1e-6` mV), range
  **±9.375 mV**; gain 4 → **572.2 nV/LSB** (`572.2e-6` mV), range **±18.75 mV**.
  Higher gain = finer resolution, as expected.
  ⚠️ bdi's *dict* has these two values **swapped** (a latent bug; bdi's docstrings
  are correct). We use the manufacturer values, so our µV output differs by 2×
  from the old bdi-based MyoGestic for a given gain — by being correct. A code
  comment will record the bdi swap. Pre-HPF analog input range ±300 mV (gain 8) /
  ±600 mV (gain 4). EMG mode applies a firmware high-pass (EMA subtraction,
  α=1/25 → cutoff Fsamp/190 ≈ 10.5 Hz at 2000 Hz) — EMG is not raw DC; document it.
- **Aux:** 6 channels appended after biosignal (Muovi rows 32..37 / Muovi+
  64..69). **Direct-mode channel map** (Muovi TCP Protocol v2.4 + MuoviLite
  §8.1.2):
  - ch 33–36 = **IMU quaternion W / X / Y / Z** (Bosch BNO055, Fusion NDOF;
    native 14-bit sign-extended to 16/24; updated at **100 Hz**, so values repeat
    ~20× per quaternion at 2000 Hz — the IMU is held, not interpolated).
  - ch 37 = **buffer usage + trigger state** (bit-packed); ch 38 = **sample
    counter** (incrementing; gaps reveal dropped samples).

  Use these as `channel_names`. The IMU/counter are integer/status channels — the
  bio conversion factor is not physically meaningful for them; when
  `include_aux=True`, emit them **unscaled** (raw int) and label clearly. (Via the
  SyncStation the accessory channels are bit-packed differently — TRIG / 7-bit
  trigger code / buffer — see §11.)
- **Stop/disconnect:** resend `cfg - 1`, drain, close.

### 5.2 Quattrocento
- **Socket role:** host is **TCP client**; dials the device. Default
  **169.254.1.10:23456** (link-local — host NIC needs a 169.254.x.x address).
- **Handshake:** none; after connect, send the 40-byte config; start toggles the
  acquisition bit.
- **Config:** 40-byte packet.
  - Byte 0 = `ACQ_SETT`:
    ```
    acq  = 1 << 7
    acq |= decim_active        << 6
    acq |= recording_active    << 5
    acq |= fs_mode(0..3)       << 3
    acq |= n_channels_mode(0..3) << 1
    acq |= acquisition_active        # bit0 (start/stop)
    ```
  - Byte 1,2 = 0 (analog-out selectors, unused).
  - Bytes 3–14 = IN1–IN4 (4×3-byte per-input config); 15–26 = IN5–IN8;
    27–38 = MULTIPLE IN 1–4 (4×3 bytes). Each 3-byte input config:
    `byte3 = (side<<6)|(hp<<4)|(lp<<2)|detection`, bytes 1–2 = 0.
  - Byte 39 = **CRC-8** over bytes 0..38 (poly `0x8C`, init 0, LSB-first):
    ```python
    def crc8(data, length):
        crc = 0
        for j in range(length):
            b = data[j]
            for _ in range(8):
                s = (crc & 1) ^ (b & 1)
                crc >>= 1
                if s: crc ^= 0x8C
                b >>= 1
        return crc
    ```
    Start = `cfg[0] += 1`, recompute CRC, resend; stop = `cfg[0] -= 1`,
    recompute CRC, resend.
- **Modes:** fs LOW=512 / MEDIUM=2048 / HIGH=5120 / ULTRA=10240 Hz;
  streamed-channel count LOW=120 / MEDIUM=216 / HIGH=312 / ULTRA=408 (independent
  of fs). Per-sample always int16 / 2 bytes; samples/frame = 64.
  - Channel accounting: `streamed` = 120/216/312/408 (used for reshape);
    `bio = len(grids)*64`; aux = 16; supplementary = 8.
- **Sample format:** **little-endian, signed int16** (`<i2`). Frame Fortran-order
  `(streamed, 64)`. Within streamed block: grid biosignal channels first
  (`[i*64+j for i in grids for j in range(64)]`), then 16 aux
  (`streamed-24 .. streamed-9`), then the last 8 supplementary.
  Frame bytes = `streamed * 2 * 64` (e.g. MEDIUM 216ch → 27648).
- **Conversion factors:** bio = `5/2**16/150*1000` ≈ `5.086e-4` (mV);
  aux = `5/2**16/0.5` ≈ `1.526e-4` (V); supplementary = raw (no scaling).
- **Stop/disconnect:** send stop packet (recompute CRC), close.

### 5.3 Reimplementation gotchas
- Endianness flips: Muovi **big-endian**, Quattrocento **little-endian**.
- int24 (Muovi EEG): no native numpy dtype — read 3 bytes big-endian, sign-extend
  (`int.from_bytes(b, "big", signed=True)`), or pad to int32. (bdi's
  `_bytes_to_integers` loops `len//2` regardless of width — a latent EEG bug we
  must NOT copy; iterate `len // bytes_per_sample`.)
- Reshape **must** be Fortran order, then transpose to sample-major for the contract.
- Partial recv is mandatory: accumulate bytes, only emit complete frames.
- Quattrocento CRC must be recomputed for every start/stop packet (device rejects bad CRC).
- Reshape on `streamed` channel count, not the assembled `number_of_channels`.

## 6. Configuration surface (constructor kwargs)

```python
MuoviSource(plus=False, mode="EMG", detection="monopolar_gain_8",
            host_ip=None, port=54321, include_aux=False)

QuattrocentoSource(device_ip="169.254.1.10", port=23456,
                   fs_mode="MEDIUM", channels_mode="MEDIUM", grids=(0,),
                   high_pass="none", low_pass="medium", detection="monopolar",
                   include_aux=False)
```

Enums exposed as plain strings. Defaults: Muovi EMG @ 2000 Hz, 32ch monopolar
gain-8; Quattrocento MEDIUM/MEDIUM, grid 0.

## 7. GUI integration

**Status + scan/reconnect (free):** existing `myogestic/widgets/stream_panel.py`
+ `_signal_scan.py` render status + Scan/Reconnect for any source implementing
`discover()`/`reconnect()`. Wrinkle: Muovi inverts the scan model (device dials
us), so Muovi `discover()` lists local NIC IPs to bind and the panel shows
"waiting for device on :54321"; Quattrocento `discover()` does a reachability
check on the device IP. `reconnect(target)` sets the bind IP (Muovi) / device IP
(Quattrocento).

**Device-config panel (in scope):** add a generic, source-agnostic config
mechanism so device settings are editable in the ImGui app — not just via
constructor kwargs.

- **Optional Protocol extension** (mirrors the `discover()`/`reconnect()`
  opt-in style): a source may expose
  - `config_spec() -> list[ConfigField]` — each field has `key`, `label`,
    `kind` (`enum` | `bool` | `int` | `str`), `options` (for enum), and current
    `value`.
  - `set_config(**kwargs) -> None` — validates and stores; takes effect on the
    next `connect()`/`reconnect()`. Raises if called while connected.
- **`device_config` widget** (`myogestic/widgets/device_config.py`): renders the
  spec generically — combos for enums, checkboxes for bools, input fields for
  int/str — with an **Apply & Connect** button that calls `set_config(...)` then
  `reconnect()`. Sources without `config_spec()` simply don't show the panel
  (LSL/Replay unaffected).
- **Lifecycle:** OTB sources start **unconnected**; the acquire loop must not
  auto-connect until the user applies config and connects (a per-stream
  "manual connect" flag, or the source's `connect()` blocking on a
  user-triggered event). This is the one acquire-loop change required; detailed
  in the implementation plan.

This keeps config source-agnostic and reusable, while constructor kwargs remain
the programmatic path (the GUI edits the same underlying fields).

## 8. Testing strategy

- **Unit tests (`_decode.py`)** — hand-built byte buffers → exact expected arrays;
  cover int16 BE, int24 BE sign-extend, int16 LE, Fortran reshape, conversion
  factors. No hardware.
- **CRC-8 unit test** against a known vector.
- **Loopback integration tests** — fake device:
  - Muovi: a client that connects to our server socket and streams synthetic
    frames; assert full `connect→read→disconnect` and decoded values.
  - Quattrocento: a fake server that validates our 40-byte+CRC config and streams
    frames; assert the same.
- **Manual hardware validation** on Muovi/Muovi+ and Quattrocento — final gate.

## 9. Scope & phasing

1. `_base` + `_decode` + `_constants` + **MuoviSource** (Muovi & Muovi+),
   unit + loopback tests → hardware-validate.
2. **QuattrocentoSource** (client + CRC), unit + loopback tests → hardware-validate.
3. **GUI device-config** (`config_spec`/`set_config` + `device_config` widget +
   manual-connect acquire-loop change), wired for both devices.
4. **SessantaquattroSource** later on the same base (Muovi-family protocol),
   validated when hardware available.
5. `examples/otb/` script + a short docs page.

## 10. Open questions / risks

- Muovi server-role vs the scan-oriented GUI model — handled via the `discover()`
  semantics above, but UX may want iteration after hardware testing.
- Conversion-factor gain swap — **resolved & manufacturer-confirmed** (Muovi TCP
  Protocol v2.4): gain-8 = 286.1 nV (finer), gain-4 = 572.2 nV. Differs 2× from
  the old bdi-dict output, which was buggy.
- **Muovi control byte — corrected to the official v2.4 layout** (§5.1);
  supersedes bdi's encoding. Validate on first hardware run using TEST mode
  (`MODE=11`, ramps) — monotonic decoded ramps confirm byte layout + endianness
  in one shot.
- **Byte order** — **resolved & explicitly confirmed**: big-endian, 2's-complement
  (MuoviLite manual §8.1.2). TEST-mode ramps remain a cheap first-connect sanity
  check, but this is no longer an open question.
- **Quattrocento details are bdi-sourced only** — the user-provided PDFs cover
  Muovi/SyncStation, not Quattrocento. Treat §5.2 as provisional and verify
  against the OTB Quattrocento communication-protocol PDF before/while
  implementing phase 2.
- Manual-connect acquire-loop change (§7) is the one cross-cutting change to
  existing code; keep it minimal and behind a per-stream flag so LSL/Replay
  behaviour is unchanged.
- Quattrocento link-local networking (169.254.x.x) is an environment/setup
  concern, not a code one; document NIC setup in the examples/docs.

## 11. Future: SyncStation multi-probe path (out of scope v1)

Verified against SyncStation TCP Protocol v2.8 + MuoviPro manual. The SyncStation
is a **separate connection path** from direct single-probe connect:

- PC is a **TCP client** to the SyncStation at fixed IP **192.168.76.1**, port
  **54320** (direct single Muovi is PC-server on 54321 — different role & port).
- Commands are **framed message strings**: `START BYTE` (StartStop vs OptSettings
  via MSB) + N `CONTROL BYTE`s (one per device slot; `SIZE<4:0>` field counts
  them) + a terminating **CRC-8**. Each CONTROL BYTE adds a 4-bit `DEV` probe
  selector above the same EMG/EEG·MODE·EN bits.
- The SyncStation multiplexes all active probes + 4 SyncStation aux + 2 accessory
  channels into one stream; missing-probe samples are zero-filled.

This aggregates up to 4 Muovi + 2 Muovi+/Sessantaquattro + 8 due+ + 2 Quattro+.
A `SyncStationSource` is a natural future addition on the same `_OTBSource` base
(client role + CRC-framed command builder), but not needed for the direct-connect
goal. Captured here so the base design leaves room for it.
