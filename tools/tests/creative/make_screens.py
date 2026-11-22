#!/usr/bin/env python3
"""書き出しの確かめに使う、6.9 inch の大きさの仮の画面（PNG）を作る（Pillow を使わない）。

    python3 tools/tests/creative/make_screens.py <出力のフォルダ> ja,en 01_home,02_detail,03_settings
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

WIDTH, HEIGHT = 1320, 2868


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def screen(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    rows = bytearray()
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = bytes(round(a + (b - a) * t) for a, b in zip(top, bottom))
        rows += b"\x00" + color * WIDTH
    header = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


def main() -> int:
    out, languages, names = Path(sys.argv[1]), sys.argv[2].split(","), sys.argv[3].split(",")
    palette = [((240, 244, 255), (180, 196, 255)), ((255, 244, 230), (255, 200, 150)), ((230, 255, 240), (150, 220, 180))]
    for language in languages:
        (out / language).mkdir(parents=True, exist_ok=True)
        for index, name in enumerate(names):
            top, bottom = palette[index % len(palette)]
            (out / language / f"{name}.png").write_bytes(screen(top, bottom))
    return 0


if __name__ == "__main__":
    sys.exit(main())
