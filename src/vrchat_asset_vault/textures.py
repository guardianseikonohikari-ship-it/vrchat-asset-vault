"""Texture probing with the standard library only.

VRChat's biggest world-size driver is textures: the official Android
guidance caps them at 1024x1024, and a single 4K texture can matter
more than a thousand triangles. This module reads image dimensions
straight from file headers (PNG / JPEG / BMP / TGA) — no Pillow, no
new dependency — so the VRChat card can show a real texture size
instead of "?".

EXR / HDR / DDS are not probed here (rare as neighbouring textures);
they return None and the card says so honestly.
"""
from __future__ import annotations

import struct
from pathlib import Path

from .scanner import TEXTURE_EXTS, find_textures_for


def probe_image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) from the image header, or None if unknown."""
    suffix = path.suffix.lower()
    try:
        with path.open("rb") as f:
            head = f.read(64 * 1024)
    except OSError:
        return None
    if suffix == ".png":
        return _png_size(head)
    if suffix in {".jpg", ".jpeg"}:
        return _jpeg_size(head)
    if suffix == ".bmp":
        return _bmp_size(head)
    if suffix == ".tga":
        return _tga_size(head)
    return None


def _png_size(head: bytes) -> tuple[int, int] | None:
    # PNG signature (8) + IHDR length (4) + "IHDR" (4) + width (4) + height (4)
    if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return (width, height) if width and height else None


def _jpeg_size(head: bytes) -> tuple[int, int] | None:
    # Walk JPEG markers until a Start-Of-Frame (C0/C1/C2) gives the size.
    if len(head) < 4 or head[0:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 1 < len(head):
        if head[i] != 0xFF:
            i += 1
            continue
        marker = head[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > len(head):
            return None
        length = struct.unpack(">H", head[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            # length(2) precision(1) height(2) width(2)
            if i + 9 > len(head):
                return None
            height, width = struct.unpack(">HH", head[i + 5 : i + 9])
            return (width, height) if width and height else None
        i += 2 + length
    return None


def _bmp_size(head: bytes) -> tuple[int, int] | None:
    if len(head) < 26 or head[0:2] != b"BM":
        return None
    width, height = struct.unpack("<ii", head[18:26])
    return (abs(width), abs(height)) if width and height else None


def _tga_size(head: bytes) -> tuple[int, int] | None:
    if len(head) < 16:
        return None
    width, height = struct.unpack("<HH", head[12:16])
    return (width, height) if width and height else None


def texture_stats_for(model_path: Path) -> dict:
    """Neighbouring textures for one model: count, biggest side, bytes.

    Returns {"count", "max_px", "total_bytes"}; max_px is None when no
    texture could be measured (or there are no textures at all).
    """
    textures = find_textures_for(model_path)
    max_px: int | None = None
    total = 0
    for tex in textures:
        try:
            total += tex.stat().st_size
        except OSError:
            continue
        size = probe_image_size(tex)
        if size is not None:
            max_px = max(max_px or 0, size[0], size[1])
    return {"count": len(textures), "max_px": max_px, "total_bytes": total}
