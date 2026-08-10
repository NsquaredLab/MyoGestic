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
    """Muovi control byte: (EMG<<3) | (mode<<1) | GO, per the Read_muovi.m formula."""
    return (int(emg) << 3) | ((mode & 0x3) << 1) | int(go)


def muovi_channel_names(geo: MuoviGeometry) -> list[str]:
    """Per-channel labels: bio then the 6 named aux channels."""
    names = [f"bio{i}" for i in range(geo.n_bio)]
    names += ["imu_w", "imu_x", "imu_y", "imu_z", "buffer_trigger", "counter"]
    return names


# Sessantaquattro ----------------------------------------------------------

SESSANTAQUATTRO_PORT = 45454
# Gain-8 LSB in mV at 16-bit (286.1 nV), per TCP Communication Protocol bit 5-4.
SESSANTAQUATTRO_CONV_FACTOR_MV = 0.0002861
# The IMU quaternion is transmitted as int16 scaled by 2**14.
SESSANTAQUATTRO_QUATERNION_SCALE = 16384.0
SESSANTAQUATTRO_BIO_BY_NCH = {0: 8, 1: 16, 2: 32, 3: 64}
SESSANTAQUATTRO_FS_BY_MODE = {0: 500.0, 1: 1000.0, 2: 2000.0, 3: 4000.0}
# MODE=011 (accelerometer) quadruples the rate and pins the channel count.
SESSANTAQUATTRO_ACCEL_FS_BY_MODE = {0: 2000.0, 1: 4000.0, 2: 8000.0, 3: 16000.0}
SESSANTAQUATTRO_MODE_CODE = {
    "monopolar": 0b000,
    "bipolar": 0b001,
    "differential": 0b010,
    "accelerometer": 0b011,
    "impedance_advanced": 0b101,
    "impedance": 0b110,
    "test": 0b111,
}
# Candidate accessory-block widths, narrowest first. Docs say 4 for every NCH
# value; a Sessantaquattro+ sends 8 (2 AUX + quaternion + buffer/trigger +
# counter). Probed from the ramp counter, not trusted.
SESSANTAQUATTRO_ACCESSORY_CANDIDATES = (4, 6, 8)


@dataclass(frozen=True)
class SessantaquattroGeometry:
    n_total: int          # channels per sample-instant on the wire
    n_bio: int            # biosignal channels (first n_bio rows)
    n_accessory: int      # trailing non-bioelectrical channels
    fs: float
    bytes_per_sample: int  # 2 (16-bit) or 3 (24-bit)


def sessantaquattro_geometry(
    *, nch_mode: int, fs_mode: int, mode: str, n_accessory: int, high_res: bool
) -> SessantaquattroGeometry:
    """Channel/rate/width geometry for one (NCH, FSAMP, MODE) combination."""
    if mode == "accelerometer":
        # "Only 8 channels ... are acquired and transferred (even if NCH has a
        # different value) with increased sampling frequency."
        n_bio = 8
        fs = SESSANTAQUATTRO_ACCEL_FS_BY_MODE[fs_mode]
    else:
        n_bio = SESSANTAQUATTRO_BIO_BY_NCH[nch_mode]
        if mode == "bipolar":  # only MODE=001 halves; differential does not
            n_bio //= 2
        fs = SESSANTAQUATTRO_FS_BY_MODE[fs_mode]
    return SessantaquattroGeometry(
        n_total=n_bio + n_accessory,
        n_bio=n_bio,
        n_accessory=n_accessory,
        fs=fs,
        bytes_per_sample=3 if high_res else 2,
    )


def sessantaquattro_config_word(
    *,
    nch_mode: int,
    fs_mode: int,
    mode: str = "monopolar",
    high_res: bool = False,
    hpf: bool = True,
    gain: int = 0,
    trig: int = 0,
    rec: bool = False,
    go: bool,
) -> int:
    """Build the 16-bit configuration word (sent big-endian, CONTROL BYTE 0 first).

    CONTROL BYTE 0 = ``GETSET | FSAMP<1:0> | NCH<1:0> | MODE<2:0>``,
    CONTROL BYTE 1 = ``HRES | HPF | GAIN<1:0> | TRIG<1:0> | REC | GO``.
    ``go=False`` stops the transfer **and the device closes the socket** — verified
    on an SE004: sending it on a freshly accepted connection makes the device hang
    up without streaming a byte. It is therefore the stop command only, never a
    "apply settings" preamble.
    """
    return (
        (0 << 15)  # GETSET = 0 -> SET
        | ((fs_mode & 0x3) << 13)
        | ((nch_mode & 0x3) << 11)
        | (SESSANTAQUATTRO_MODE_CODE[mode] << 8)
        | (int(high_res) << 7)
        | (int(hpf) << 6)
        | ((gain & 0x3) << 4)
        | ((trig & 0x3) << 2)
        | (int(rec) << 1)
        | int(go)
    )


# GETSET=1, INFO=000: device replies with 13 bytes, the first two being the
# control bytes currently in force.
SESSANTAQUATTRO_GET_SETTINGS_WORD = 1 << 15
SESSANTAQUATTRO_SETTINGS_NBYTES = 13


def sessantaquattro_channel_names(geo: SessantaquattroGeometry) -> list[str]:
    """Per-channel labels: bio, then the accessory block ending in the counter.

    The 8-channel block on a Sessantaquattro+ is ``aux0, aux1`` then the Muovi
    accessory layout (quaternion, buffer/trigger, counter). Narrower blocks drop
    the leading AUX channels. Quaternion component order follows Muovi's
    ``w, x, y, z`` -- unverified against this device.
    """
    names = [f"bio{i}" for i in range(geo.n_bio)]
    tail = ["imu_w", "imu_x", "imu_y", "imu_z", "buffer_trigger", "counter"]
    tail = tail[-geo.n_accessory:] if geo.n_accessory < len(tail) else tail
    n_aux = geo.n_accessory - len(tail)
    names += [f"aux{i}" for i in range(n_aux)] + tail
    return names


# Quattrocento -------------------------------------------------------------

QUATTRO_IP = "169.254.1.10"
QUATTRO_PORT = 23456
QUATTRO_FS_BY_MODE = {0: 512.0, 1: 2048.0, 2: 5120.0, 3: 10240.0}
QUATTRO_NCH_BY_MODE = {0: 120, 1: 216, 2: 312, 3: 408}
# Biosignal grid channels per mode = streamed total minus 16 AUX IN minus 8
# accessory (Read_Quattrocento.m: NCHsel = IN.. + MULTIPLE IN.. + AUX IN).
QUATTRO_BIO_BY_MODE = {0: 96, 1: 192, 2: 288, 3: 384}
QUATTRO_N_AUX_IN = 16       # back-panel analog AUX IN (scaled to V)
QUATTRO_N_ACCESSORY = 8     # last 8: counter / trigger / buffer / reserved (raw)
# Read_Quattrocento.m: GainFactor = 5/2^16/150*1000 (mV); AuxGain = 5/2^16/0.5 (V)
QUATTRO_CONV_FACTOR_MV = 5 / 2 ** 16 / 150 * 1000
QUATTRO_AUX_FACTOR_V = 5 / 2 ** 16 / 0.5
# Per-input CONF2 byte = (side<<6) | (hpf<<4) | (lpf<<2) | detection. Codes per the
# OTB Communication Protocol / Read_Quattrocento.m. ⚠️ Verify against the manual on
# the first hardware run (design spec §10) — the encoding supersedes bdi's.
QUATTRO_DETECTION_CODE = {"monopolar": 0b00, "differential": 0b01, "bipolar": 0b10}
QUATTRO_HPF_CODE = {0.7: 0b00, 10: 0b01, 100: 0b10, 200: 0b11}  # Hz
QUATTRO_LPF_CODE = {130: 0b00, 500: 0b01, 900: 0b10, 4400: 0b11}  # Hz


def quattro_conf2(
    *,
    detection: str = "monopolar",
    hpf: float = 10,
    lpf: float = 500,
    side: int = 0,
) -> int:
    """Build a per-input CONF2 byte from named settings.

    ``detection`` in {monopolar, differential, bipolar}; ``hpf`` in {0.7, 10, 100,
    200} Hz; ``lpf`` in {130, 500, 900, 4400} Hz. Defaults reproduce ``0x14``
    (monopolar, HPF 10 Hz, LPF 500 Hz), the Read_Quattrocento.m default.
    """
    return (
        ((side & 0x1) << 6)
        | (QUATTRO_HPF_CODE[hpf] << 4)
        | (QUATTRO_LPF_CODE[lpf] << 2)
        | QUATTRO_DETECTION_CODE[detection]
    )


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
    """Build the 40-byte Quattrocento config string (with CRC-8 trailer).

    ``acq_on`` sets only bit 0 (the GO bit); the fs/nch/filter configuration is
    encoded identically whether starting or stopping, so a stop preserves the
    device's configured mode and flips only the acquisition bit.
    """
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
    # Layout: [n_bio biosignal][16 AUX IN][8 accessory]. The middle AUX block is
    # whatever is left between bio and the final 8 accessory channels.
    n_aux = max(0, nch_total - n_bio - QUATTRO_N_ACCESSORY)
    names = [f"bio{i}" for i in range(n_bio)]
    names += [f"aux{i}" for i in range(n_aux)]
    names += [f"acc{i}" for i in range(nch_total - n_bio - n_aux)]
    # The 8 accessory channels are the last 8 (0-indexed names[-8:]).
    # Read_Quattrocento.m: counter (RampChan) = nch-7 (1-indexed) -> names[-8];
    # buffer (BuffChan) = nch-4 (1-indexed) -> names[-5]; trigger is the
    # accessory channel between them (config protocol v1.7) -> names[-7].
    if nch_total >= QUATTRO_N_ACCESSORY:
        names[-8] = "counter"
        names[-7] = "trigger"
        names[-5] = "buffer"
    return names
