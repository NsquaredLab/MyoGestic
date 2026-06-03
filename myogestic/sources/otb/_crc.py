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
