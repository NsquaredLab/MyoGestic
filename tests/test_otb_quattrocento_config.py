"""Quattrocento config/decoding unit tests (no socket): channel selection vs
wire scaling boundary, CONF2 filter/detection encoding, start/stop packets, and
the provenance config_dict."""
import numpy as np

from myogestic.sources.otb import _constants as C
from myogestic.sources.otb.quattrocento import QuattrocentoSource


def _le_int16_frame(values):
    return np.asarray(values, dtype="<i2").tobytes()


# --- A1: scaling follows the WIRE layout, not the output selection -----------

def test_scaling_uses_wire_boundary_independent_of_selection():
    # 120-wire (mode 0): bio [0,96), AUX IN [96,112), accessory [112,120).
    # Pick one channel from each region; each must be scaled by its wire region,
    # not by where it lands in the output.
    src = QuattrocentoSource(nch_mode=0, select=[10, 100, 115])
    frame = _le_int16_frame(range(120))  # one sample-instant, value == channel idx
    out = src._decode(frame)
    assert out.shape == (1, 3)
    np.testing.assert_allclose(out[0, 0], 10 * C.QUATTRO_CONV_FACTOR_MV, rtol=1e-6)   # bio -> mV
    np.testing.assert_allclose(out[0, 1], 100 * C.QUATTRO_AUX_FACTOR_V, rtol=1e-6)    # AUX IN -> V
    np.testing.assert_allclose(out[0, 2], 115.0, rtol=0)                             # accessory raw


def test_select_below_wire_bio_still_scales_as_mv():
    # Regression: asking for fewer bio channels than the wire's bio count must
    # NOT reclassify the tail as AUX (the old n_bio conflation bug).
    src = QuattrocentoSource(nch_mode=0, select=range(16))  # first 16 of 96 bio
    frame = _le_int16_frame(range(120))
    out = src._decode(frame)
    assert out.shape == (1, 16)
    np.testing.assert_allclose(out[0, 15], 15 * C.QUATTRO_CONV_FACTOR_MV, rtol=1e-6)


def test_select_out_of_range_rejected():
    import pytest
    with pytest.raises(ValueError):
        QuattrocentoSource(nch_mode=0, select=[0, 120])  # 120 == nch_total, invalid


# --- A2: CONF2 filter/detection encoding ------------------------------------

def test_conf2_defaults_match_read_quattrocento_default():
    assert C.quattro_conf2() == 0x14  # monopolar, HPF 10, LPF 500


def test_conf2_bipolar_10_4400():
    # (side0<<6)|(hpf 10=01<<4)|(lpf 4400=11<<2)|(bipolar=10) = 0x10|0x0C|0x02
    assert C.quattro_conf2(detection="bipolar", hpf=10, lpf=4400) == 0x1E


def test_source_embeds_conf2_in_every_input_slot():
    src = QuattrocentoSource(nch_mode=0, detection="bipolar", hpf=10, lpf=4400)
    pkt = bytes.fromhex(src.config_dict()["start_packet_hex"])
    # 12 input slots at bytes 3+3i..; CONF2 is the third byte of each slot.
    for i in range(12):
        assert pkt[3 + i * 3 + 2] == 0x1E


# --- A3: stop preserves config, flips only the GO bit -----------------------

def test_stop_packet_differs_from_start_only_in_go_bit():
    start = C.quattro_config(fs_mode=3, nch_mode=0, acq_on=True, conf2=0x1E)
    stop = C.quattro_config(fs_mode=3, nch_mode=0, acq_on=False, conf2=0x1E)
    assert start[0] & 0x01 == 1 and stop[0] & 0x01 == 0
    assert start[0] & ~0x01 == stop[0] & ~0x01     # everything but bit 0 identical
    assert start[1:39] == stop[1:39]               # config body identical
    assert start[39] != stop[39]                   # CRC differs (byte 0 changed)
    assert stop[39] == C.crc8(stop[:39])


# --- A7: provenance config_dict ---------------------------------------------

def test_config_dict_round_trips_and_packet_is_valid():
    src = QuattrocentoSource(
        device_ip="169.254.1.10", fs_mode=3, nch_mode=0,
        select=range(16), detection="bipolar", hpf=10, lpf=4400,
    )
    d = src.config_dict()
    assert d["device"] == "quattrocento"
    assert d["fs_hz"] == 10240.0 and d["fs_mode"] == 3
    assert d["nch_wire_total"] == 120 and d["wire_bio"] == 96
    assert d["select"] == list(range(16))
    assert d["detection"] == "bipolar" and d["hpf_hz"] == 10 and d["lpf_hz"] == 4400
    assert d["conf2_byte"] == 0x1E
    pkt = bytes.fromhex(d["start_packet_hex"])
    assert len(pkt) == 40 and pkt[39] == C.crc8(pkt[:39])
