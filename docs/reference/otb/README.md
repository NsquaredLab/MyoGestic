# OT Bioelettronica reference code & protocol notes

Manufacturer reference material for the native OTB device sources
(`myogestic/sources/otb/`). **Reference only — not imported or shipped.** These
are OT Bioelettronica's own example scripts, kept here as the ground-truth decode
the Python implementation mirrors.

| File | Source | Role |
|------|--------|------|
| `Read_muovi.m` | OTB MATLAB example v3.0 | Direct single-Muovi connection (PC = TCP server :54321). Canonical control-byte + decode reference. |
| `Read_muoviAP.m` | OTB MATLAB example v2.0 | SyncStation path (PC = TCP client 192.168.76.1:54320), CRC8-framed multi-probe command strings. |
| `CRC8.m` | OTB MATLAB example | CRC-8 (poly `0x8C`, LSB-first, init 0) used by the SyncStation / Quattrocento framed commands. |

Protocol verified against (manufacturer PDFs, not committed):
- Muovi probe TCP Communication Protocol v2.4
- SyncStation TCP Communication Protocol v2.8
- MuoviPro User Manual v5.1
- MuoviLite User Manual v1.1

Design spec: `docs/superpowers/specs/2026-06-03-otb-device-sources-design.md`.

Key facts distilled from these references:
- Direct Muovi: PC is **TCP server** on **54321**; control byte
  `(EMG<<3) | (Mode<<1) | GO`; stop = `byte - 1`.
- Data is **big-endian**, 2's-complement; EMG = int16 (2000 Hz), EEG = int24
  (500 Hz). Conversion factor (gain 8) = **286.1 nV/LSB** (`0.000286` mV).
- Frame is Fortran-order `(n_channels, samples)`; `n_channels` depends on
  `(device, mode)` — Muovi `NumChanVsMode = [38 22 38 38]`.
- Channel map: 1–32 bio, 33–36 IMU quaternion W/X/Y/Z, 37 buffer+trigger,
  38 sample counter.
