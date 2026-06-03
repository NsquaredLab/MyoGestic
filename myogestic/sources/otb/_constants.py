"""OTB device geometry, conversion factors, and command builders.

Manufacturer-verified (Muovi TCP Protocol v2.4, MuoviLite manual v1.1,
Read_muovi.m v3.0). See docs/reference/otb/.
"""
from __future__ import annotations

from dataclasses import dataclass

from myogestic.sources.otb._crc import crc8  # re-exported for callers/tests

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
    if acq_on:
        acq_sett = (
            0x80
            | (int(decim) << 6)
            | (int(rec_on) << 5)
            | ((fs_mode & 0x3) << 3)
            | ((nch_mode & 0x3) << 1)
            | 1
        )
    else:
        acq_sett = 0x80
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
