"""Sessantaquattro geometry, config word, and decode.

The golden fixture is 128 samples of real Sessantaquattro+ wire bytes,
reconstructed from a hardware recording (64 bioelectrical + 8 accessory
channels, 2000 Hz, 16-bit, monopolar) over a stretch with no dropouts.
"""
from pathlib import Path

import numpy as np
import pytest

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb.sessantaquattro import SessantaquattroSource

_FIXTURE = Path(__file__).parent / "fixtures" / "sessantaquattro_pro_plus_72ch.bin"
_N_SAMPLES = 128
_N_TOTAL = 72
_N_BIO = 64


@pytest.fixture(scope="module")
def wire_bytes() -> bytes:
    return _FIXTURE.read_bytes()


# --- config word ----------------------------------------------------------
# Hand-derived from CONTROL BYTE 0 = GETSET|FSAMP<1:0>|NCH<1:0>|MODE<2:0> and
# CONTROL BYTE 1 = HRES|HPF|GAIN<1:0>|TRIG<1:0>|REC|GO. 0x5841 is the word the
# recorded hardware session actually ran with: FSAMP=10 (2000 Hz), NCH=11
# (64 bio), MODE=000 (monopolar), HRES=0, HPF=1, GAIN=00, TRIG=00, REC=0, GO=1.
_GOLDEN_2000_64_MONO_GO = 0x5841


def test_config_word_matches_the_recorded_session():
    word = C.sessantaquattro_config_word(nch_mode=3, fs_mode=2, mode="monopolar", go=True)
    assert word == _GOLDEN_2000_64_MONO_GO
    assert word.to_bytes(2, "big") == bytes([0x58, 0x41])


def test_stop_word_differs_only_in_the_go_bit():
    kwargs = dict(nch_mode=3, fs_mode=2, mode="monopolar")
    start = C.sessantaquattro_config_word(**kwargs, go=True)
    stop = C.sessantaquattro_config_word(**kwargs, go=False)
    assert start ^ stop == 0b1


def test_source_start_word_matches_golden():
    src = SessantaquattroSource(nch_mode=3, fs_mode=2, mode="monopolar")
    assert src._config_word(go=True) == _GOLDEN_2000_64_MONO_GO


# --- geometry -------------------------------------------------------------
@pytest.mark.parametrize("nch_mode, n_bio", [(0, 8), (1, 16), (2, 32), (3, 64)])
def test_bio_count_follows_nch_mode(nch_mode, n_bio):
    geo = C.sessantaquattro_geometry(
        nch_mode=nch_mode, fs_mode=2, mode="monopolar", n_accessory=8, high_res=False
    )
    assert (geo.n_bio, geo.n_total) == (n_bio, n_bio + 8)


def test_only_bipolar_halves_the_channel_count():
    def bio(mode):
        return C.sessantaquattro_geometry(
            nch_mode=3, fs_mode=2, mode=mode, n_accessory=8, high_res=False
        ).n_bio

    assert bio("monopolar") == 64
    assert bio("differential") == 64  # differentiates within groups of 32
    assert bio("bipolar") == 32


def test_accelerometer_mode_pins_channels_and_raises_the_rate():
    geo = C.sessantaquattro_geometry(
        nch_mode=3, fs_mode=2, mode="accelerometer", n_accessory=8, high_res=False
    )
    assert geo.n_bio == 8  # "even if NCH has a different value"
    assert geo.fs == 8000.0  # 4x the standard-mode rate for the same FSAMP


def test_channel_names_end_in_the_counter():
    geo = C.sessantaquattro_geometry(
        nch_mode=3, fs_mode=2, mode="monopolar", n_accessory=8, high_res=False
    )
    names = C.sessantaquattro_channel_names(geo)
    assert len(names) == 72
    assert names[:2] == ["bio0", "bio1"]
    assert names[64:] == [
        "aux0", "aux1", "imu_w", "imu_x", "imu_y", "imu_z",
        "buffer_trigger", "counter",
    ]


# --- decode against real hardware bytes -----------------------------------
def test_decodes_real_wire_bytes(wire_bytes):
    src = SessantaquattroSource(include_aux=True)
    src._set_geometry(8)
    src._identified = True
    data = src._decode(wire_bytes)

    assert data.shape == (_N_SAMPLES, _N_TOTAL)
    # Bio channels are scaled to mV; accessory channels are passed through raw.
    assert np.isfinite(data).all()
    assert abs(data[:, :_N_BIO]).max() < 10.0  # mV, not raw ADC counts


def test_counter_channel_is_a_clean_ramp(wire_bytes):
    src = SessantaquattroSource(include_aux=True)
    src._set_geometry(8)
    src._identified = True
    counter = src._decode(wire_bytes)[:, -1].astype(np.int64)
    steps = np.diff(counter)
    assert np.all(np.where(steps < 0, steps + 65536, steps) == 1)
    assert src.dropped_samples == 0


def test_quaternion_norm_is_conserved(wire_bytes):
    """Channels 66-69 are a unit quaternion scaled by 2**14."""
    src = SessantaquattroSource(include_aux=True)
    src._set_geometry(8)
    src._identified = True
    quat = src._decode(wire_bytes)[:, 66:70].astype(np.float64)
    norm = np.sqrt((quat**2).sum(axis=1))
    assert norm.std() / norm.mean() < 0.01
    assert norm.mean() == pytest.approx(C.SESSANTAQUATTRO_QUATERNION_SCALE, rel=0.01)


# --- geometry probe -------------------------------------------------------
def test_probe_identifies_the_accessory_width(wire_bytes):
    """Candidates are tried narrowest-first; only 8 yields a clean ramp here."""
    src = SessantaquattroSource()
    src._set_geometry(max(C.SESSANTAQUATTRO_ACCESSORY_CANDIDATES))
    src._identify_geometry(wire_bytes)
    assert src._geo.n_accessory == 8
    assert src._geo.n_total == 72
    assert src._frame_nbytes == 72 * 2


def test_probe_rejects_a_mismatched_bio_count(wire_bytes):
    """A wrong nch_mode cannot be rescued by any accessory width."""
    src = SessantaquattroSource(nch_mode=2)  # 32 bio, but the wire carries 64
    src._set_geometry(8)
    with pytest.raises(ValueError, match="could not identify the channel count"):
        src._identify_geometry(wire_bytes)


def test_probe_runs_before_any_frame_is_sliced(wire_bytes):
    """_drain must not consume bytes while the width is still provisional."""
    src = SessantaquattroSource()
    src._info = src._open()  # as accept_and_start() does
    src._buf.extend(wire_bytes[: src._probe_nbytes - 1])
    assert src._drain() == (None, None)  # not enough to decide yet
    assert len(src._buf) == src._probe_nbytes - 1  # and nothing consumed

    src._buf.extend(wire_bytes[src._probe_nbytes - 1 :])
    data, ts = src._drain()
    assert src._identified
    assert data is not None and data.shape == (_N_SAMPLES, _N_BIO)
    assert ts is not None and len(ts) == _N_SAMPLES


# --- loss accounting ------------------------------------------------------
def test_dropped_samples_counted_from_the_counter():
    src = SessantaquattroSource()
    src._set_geometry(8)
    src._identified = True
    src._track_counter(np.array([10, 11, 12]))
    assert (src.dropped_samples, src.dropout_events) == (0, 0)

    src._track_counter(np.array([845, 846]))  # 832 missing since 12
    assert (src.dropped_samples, src.dropout_events) == (832, 1)


def test_counter_wrap_is_not_counted_as_loss():
    src = SessantaquattroSource()
    src._set_geometry(8)
    src._identified = True
    src._track_counter(np.array([32766, 32767, -32768, -32767]))
    assert src.dropped_samples == 0
