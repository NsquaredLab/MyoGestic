"""Golden config vectors — lock the Quattrocento 40-byte wire packet against drift.

The expected bytes are hand-derived from the OTB protocol layout, independent of
``quattro_config``'s code: byte 0 = ``0x80 | fs_mode<<3 | nch_mode<<1 | GO``, bytes
1-2 = 0 (AN_OUT unused), bytes 3-38 = 12 input slots of ``[CONF0=0, CONF1=0, CONF2]``,
byte 39 = CRC-8. The CRC in each vector was cross-checked with an independent
table-driven CRC-8/MAXIM (poly 0x31 reflected = 0x8C) — structurally different from the
repo's bit-serial ``crc8`` — so a refactor that changes the packing OR the CRC model
fails here. ⚠️ Still validate against the amplifier on the first hardware run
(design spec §10): these lock our encoding, not the manufacturer's acceptance.
"""
from myogestic.sources.otb import _constants as C
from myogestic.sources.otb.quattrocento import QuattrocentoSource

# fs_mode=3 (10240 Hz), nch_mode=0 (120 ch), conf2=0x1E (bipolar, HP 10, LP 4400), GO on.
_GOLDEN_10240_120_BIPOLAR = bytes.fromhex(
    "99000000001e00001e00001e00001e00001e00001e00001e00001e00001e00001e00001e00001e1e"
)
# fs_mode=1 (2048 Hz), nch_mode=3 (408 ch), conf2=0x14 (monopolar, HP 10, LP 500), GO on.
_GOLDEN_2048_408_MONO = bytes.fromhex(
    "8f000000001400001400001400001400001400001400001400001400001400001400001400001457"
)


def test_quattro_config_matches_golden_vectors():
    assert C.quattro_config(fs_mode=3, nch_mode=0, acq_on=True, conf2=0x1E) == _GOLDEN_10240_120_BIPOLAR
    assert C.quattro_config(fs_mode=1, nch_mode=3, acq_on=True, conf2=0x14) == _GOLDEN_2048_408_MONO


def test_source_start_packet_matches_golden_vector():
    # The sci target config: 10240 Hz, 120-ch wire, bipolar, 10-4400 Hz.
    src = QuattrocentoSource(fs_mode=3, nch_mode=0, detection="bipolar", hpf=10, lpf=4400)
    assert bytes.fromhex(src.config_dict()["start_packet_hex"]) == _GOLDEN_10240_120_BIPOLAR
