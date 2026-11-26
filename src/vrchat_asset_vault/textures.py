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

import shutil
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


# Formats Pillow can read AND write (so a downscale is a real file,
# not a renamed one). EXR / HDR / DDS are read by nothing in pure
# Python and are copied as-is by the optimizer, with a warning.
DOWNSCALABLE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff"}


def downscale_texture(src: Path, dst: Path, max_px: int) -> dict:
    """Downscale one texture so its longest side is at most ``max_px``.

    Returns {"status", "size_before", "size_after", "bytes_before",
    "bytes_after", "warning"} where status is one of:
    - "downscaled": resized with LANCZOS, aspect kept, alpha kept.
    - "unchanged": already within the limit — copied byte-identical.
    - "copied": format Pillow cannot downscale (EXR/HDR/DDS) or
      Pillow is not installed — copied as-is, with a warning.
    - "failed": the file could not be read or written at all.

    Never raises for a bad file: the optimizer must keep going and
    report, not crash the whole collection over one texture.
    """
    result = {
        "status": "failed",
        "size_before": None,
        "size_after": None,
        "bytes_before": 0,
        "bytes_after": 0,
        "warning": None,
    }
    try:
        result["bytes_before"] = src.stat().st_size
    except OSError as exc:
        result["warning"] = f"could not read {src.name}: {exc}"
        return result
    result["size_before"] = probe_image_size(src)

    if src.suffix.lower() not in DOWNSCALABLE_EXTS:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as exc:
            result["warning"] = f"could not copy {src.name}: {exc}"
            return result
        result["status"] = "copied"
        result["size_after"] = result["size_before"]
        result["bytes_after"] = result["bytes_before"]
        result["warning"] = (
            f"{src.name} left at full size — {src.suffix} cannot be "
            "downscaled without Blender."
        )
        return result

    try:
        from PIL import Image
    except ImportError:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError as exc:
            result["warning"] = f"could not copy {src.name}: {exc}"
            return result
        result["status"] = "copied"
        result["size_after"] = result["size_before"]
        result["bytes_after"] = result["bytes_before"]
        result["warning"] = (
            f"{src.name} left at full size — Pillow is not installed "
            "(install vrchat-asset-vault[optimize])."
        )
        return result

    try:
        with Image.open(src) as img:
            width, height = img.size
            result["size_before"] = (width, height)
            longest = max(width, height)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if longest <= max_px:
                shutil.copy2(src, dst)
                result["status"] = "unchanged"
                result["size_after"] = (width, height)
                result["bytes_after"] = result["bytes_before"]
                return result
            scale = max_px / longest
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            # JPEG has no alpha; RGBA/P images must become RGB first.
            if src.suffix.lower() in {".jpg", ".jpeg"} and img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGB")
            resized = img.resize(new_size, Image.LANCZOS)
            fmt = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "bmp": "BMP",
                   "tga": "TGA", "tiff": "TIFF"}[src.suffix.lower().lstrip(".")]
            save_kw: dict = {}
            if fmt == "PNG":
                save_kw["optimize"] = True
            elif fmt == "JPEG":
                save_kw["quality"] = 90
            resized.save(dst, fmt, **save_kw)
            result["status"] = "downscaled"
            result["size_after"] = new_size
            result["bytes_after"] = dst.stat().st_size
            return result
    except Exception as exc:  # corrupt image, unsupported mode, disk error
        result["warning"] = f"could not downscale {src.name}: {exc}"
        return result
