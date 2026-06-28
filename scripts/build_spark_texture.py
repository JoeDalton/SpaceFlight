"""
Generates textures/spark.png — a soft radial glow sprite.
No dependencies beyond the Python standard library.
Run once: python generate_spark.py
"""

import math
import os
import struct
import zlib


def write_png(path: str, pixels: list[list[tuple]], size: int):
    """Write a minimal RGBA PNG from a 2-D list of (r,g,b,a) tuples."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    # IHDR
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)

    # Raw scanlines: filter byte 0x00 + RGBA per pixel
    raw = b""
    for row in pixels:
        raw += b"\x00"
        for r, g, b, a in row:
            raw += bytes([r, g, b, a])

    idat = chunk(b"IDAT", zlib.compress(raw, 9))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(idat)
        f.write(chunk(b"IEND", b""))


def make_spark(size=64) -> list[list[tuple]]:
    cx = cy = (size - 1) / 2.0
    pixels = []
    for y in range(size):
        row = []
        for x in range(size):
            # Normalised distance from centre (0=centre, 1=edge)
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / (size / 2.0)
            d = min(d, 1.0)

            # Soft quadratic falloff + bright spike at the core
            glow = (1.0 - d) ** 2.2
            core = max(0.0, 1.0 - d / 0.18) ** 0.5  # tight bright centre

            v = min(glow + core * 0.6, 1.0)
            b = int(v * 255)
            row.append((255, 255, 255, b))  # white, alpha = brightness
        pixels.append(row)
    return pixels


if __name__ == "__main__":
    os.makedirs("textures", exist_ok=True)
    path = "textures/spark_2.png"
    write_png(path, make_spark(64), 64)
    print(f"Saved {path}")
