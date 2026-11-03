"""
Media Samples
=============

Tiny, dependency-free image generators used by tests and evals (no Pillow needed).
"""

import struct
import zlib


def solid_color_png(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """A valid RGB PNG filled with one color."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    row = b"\x00" + bytes(rgb) * width  # filter byte + pixels
    raw = row * height
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def minimal_jpeg() -> bytes:
    """Bytes that start like a JPEG (SOI + APP0); enough for format sniffing in tests."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32 + b"\xff\xd9"


def minimal_webp() -> bytes:
    """Bytes that start like a WEBP (RIFF container); enough for format sniffing in tests."""
    payload = b"WEBPVP8 " + b"\x00" * 32
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def minimal_gif() -> bytes:
    return b"GIF89a" + b"\x00" * 32
