"""COBS framing and CRC-16/CCITT-FALSE codec for T5-Link v1."""

from __future__ import annotations


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def cobs_encode(data: bytes) -> bytes:
    """Encode a byte string with Consistent Overhead Byte Stuffing."""
    if not data:
        return b"\x01"

    out = bytearray()
    block = bytearray()
    for byte in data:
        if byte == 0:
            out.append(len(block) + 1)
            out.extend(block)
            block.clear()
        else:
            block.append(byte)
            if len(block) == 254:
                out.append(255)
                out.extend(block)
                block.clear()
    out.append(len(block) + 1)
    out.extend(block)
    return bytes(out)


def cobs_decode(data: bytes) -> bytes:
    """Decode a COBS-encoded byte string.

    Raises ValueError on malformed input.
    """
    if not data:
        raise ValueError("empty COBS frame")

    out = bytearray()
    idx = 0
    while idx < len(data):
        length = data[idx]
        if length == 0:
            raise ValueError("unexpected zero byte in COBS frame")
        idx += 1
        end = idx + length - 1
        if end > len(data):
            raise ValueError("COBS length byte exceeds frame")
        out.extend(data[idx:end])
        if length < 255 and end < len(data):
            out.append(0)
        idx = end
    return bytes(out)


def stuff_frame(raw: bytes) -> bytes:
    """Add CRC and COBS-encode a raw frame, appending the frame delimiter."""
    crc = crc16_ccitt_false(raw)
    with_crc = raw + crc.to_bytes(2, "little")
    return cobs_encode(with_crc) + b"\x00"


def unstuff_frame(data: bytes) -> bytes:
    """Strip delimiter, COBS-decode and verify CRC.

    Returns the original raw frame (without CRC) or raises ValueError.
    """
    if data[-1:] != b"\x00":
        raise ValueError("frame missing delimiter")
    decoded = cobs_decode(data[:-1])
    if len(decoded) < 2:
        raise ValueError("decoded frame too short for CRC")
    raw, crc_bytes = decoded[:-2], decoded[-2:]
    expected = int.from_bytes(crc_bytes, "little")
    actual = crc16_ccitt_false(raw)
    if expected != actual:
        raise ValueError(f"CRC mismatch: expected {expected:04x}, got {actual:04x}")
    return raw
