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
