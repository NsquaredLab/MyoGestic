from myogestic.sources.otb._crc import crc8


def test_crc8_empty_is_zero():
    assert crc8(b"") == 0


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
