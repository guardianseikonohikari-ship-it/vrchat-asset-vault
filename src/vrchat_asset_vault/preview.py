"""Model thumbnails without opening Blender — standard library only.

The central promise of the Vault is "preview without opening Blender",
and v0.1 shipped none of it: cards were text, the detail panel showed
"?". This module renders a small flat-shaded 3/4 view of a mesh with a
pure-Python scanline rasterizer and writes a PNG with zlib — no Pillow,
no OpenGL, no new dependency. OBJ is parsed directly; FBX/GLB/GLTF go
through trimesh when installed (the same optional extra the scanner
already uses). .blend thumbnails go through blend.py: Blender headless
exports the mesh to a temporary OBJ and the same rasterizer draws it.

Thumbnails are cached by content hash, so a rescan never re-renders
an unchanged model.
"""
from __future__ import annotations

import hashlib
import math
import struct
import zlib
from pathlib import Path

# Above this many faces the preview samples the mesh down: a thumbnail
# only has to be recognisable, and a pure-Python rasterizer should not
# spend seconds on a 10k-triangle bookshelf.
_MAX_PREVIEW_FACES = 3000

_BG = (238, 242, 246)          # light grey, matches the GUI
_BASE = (148, 168, 196)        # slate blue-grey for the mesh
_LIGHT = (0.45, 0.65, 0.62)    # light direction, normalised below


def _load_obj(path: Path):
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                parts = line.split()
                try:
                    verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
                except (IndexError, ValueError):
                    continue
            elif line.startswith("f "):
                idx: list[int] = []
                for tok in line.split()[1:]:
                    try:
                        idx.append(int(tok.split("/")[0]) - 1)
                    except ValueError:
                        continue
                # Fan-triangulate n-gons, skip degenerate faces.
                for i in range(1, len(idx) - 1):
                    a, b, c = idx[0], idx[i], idx[i + 1]
                    if len({a, b, c}) == 3 and all(0 <= j < len(verts) for j in (a, b, c)):
                        faces.append((a, b, c))
    return verts, faces


def _load_trimesh(path: Path):
    try:
        import trimesh  # type: ignore
    except ImportError:
        return None
    try:
        scene = trimesh.load(str(path), force="scene")
        if hasattr(scene, "to_geometry"):
            mesh = scene.to_geometry()
        elif hasattr(scene, "dump"):
            mesh = scene.dump(concatenate=True)
        else:
            geoms = list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
            mesh = trimesh.util.concatenate(geoms)
        verts = [tuple(map(float, v)) for v in mesh.vertices]
        faces = [tuple(map(int, f)) for f in mesh.faces]
        return verts, faces
    except Exception:
        return None


def mesh_geometry(path: Path):
    """(vertices, faces) for a model, or None when it cannot be read.

    .blend is not read here — blend.py exports it to a temporary OBJ
    first and calls this on the export (see thumbnail_for).
    """
    suffix = path.suffix.lower()
    if suffix == ".obj":
        verts, faces = _load_obj(path)
        return (verts, faces) if verts and faces else None
    if suffix in {".fbx", ".glb", ".gltf"}:
        return _load_trimesh(path)
    return None  # .blend: see blend_thumbnail in blend.py


def _rotate(v, cos_y, sin_y, cos_x, sin_x):
    x, y, z = v
    x1 = x * cos_y + z * sin_y
    z1 = -x * sin_y + z * cos_y
    y1 = y * cos_x - z1 * sin_x
    z2 = y * sin_x + z1 * cos_x
    return (x1, y1, z2)


def _write_png(pixels: bytearray, size: int) -> bytes:
    raw = bytearray()
    stride = size * 3
    for y in range(size):
        raw.append(0)  # filter: none
        raw += pixels[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
    png += chunk(b"IEND", b"")
    return png


def render_png(verts, faces, size: int = 192) -> bytes:
    """Flat-shaded 3/4 view of a mesh as PNG bytes (deterministic).

    Rendered at 2x and downsampled: the box average closes the 1px
    pinholes a scanline rasterizer leaves between adjacent triangles
    and smooths the faceted edges.
    """
    if not verts or not faces:
        raise ValueError("nothing to render")
    big = size * 2
    pixels = _render_buffer(verts, faces, big)
    # 2x2 box average down to the requested size.
    small = bytearray(size * size * 3)
    for y in range(size):
        for x in range(size):
            for c in range(3):
                total = 0
                for dy in (0, 1):
                    row = (y * 2 + dy) * big * 3
                    for dx in (0, 1):
                        total += pixels[row + (x * 2 + dx) * 3 + c]
                small[(y * size + x) * 3 + c] = total // 4
    return _write_png(small, size)


def _render_buffer(verts, faces, size: int) -> bytearray:
    """The raw RGB buffer of the flat-shaded view at the given size."""
    # Sample dense meshes down (deterministic stride) — a thumbnail
    # only needs the silhouette and the shading.
    if len(faces) > _MAX_PREVIEW_FACES:
        step = len(faces) / _MAX_PREVIEW_FACES
        faces = [faces[int(i * step)] for i in range(_MAX_PREVIEW_FACES)]

    cos_y, sin_y = math.cos(math.radians(30)), math.sin(math.radians(30))
    cos_x, sin_x = math.cos(math.radians(20)), math.sin(math.radians(20))
    rotated = [_rotate(v, cos_y, sin_y, cos_x, sin_x) for v in verts]

    xs = [v[0] for v in rotated]
    ys = [v[1] for v in rotated]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y, 1e-9)
    margin = size * 0.08
    scale = (size - 2 * margin) / span
    cx = (min_x + max_x) / 2
    cy = (min_y + max_y) / 2

    def project(v):
        return (
            margin + (v[0] - cx) * scale + (size - 2 * margin) / 2,
            margin + (cy - v[1]) * scale + (size - 2 * margin) / 2,
        )

    light_len = math.sqrt(sum(c * c for c in _LIGHT))
    light = tuple(c / light_len for c in _LIGHT)

    # Visible faces (normal toward the viewer), farthest first.
    drawn = []
    for a, b, c in faces:
        va, vb, vc = rotated[a], rotated[b], rotated[c]
        ux, uy, uz = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
        vx, vy, vz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        n_len = math.sqrt(nx * nx + ny * ny + nz * nz)
        if n_len < 1e-12 or nz <= 0:
            continue  # degenerate or back-facing
        nx, ny, nz = nx / n_len, ny / n_len, nz / n_len
        shade = 0.45 + 0.55 * max(0.0, nx * light[0] + ny * light[1] + nz * light[2])
        depth = (va[2] + vb[2] + vc[2]) / 3
        drawn.append((depth, project(va), project(vb), project(vc), shade))
    drawn.sort(key=lambda d: d[0])

    pixels = bytearray(size * size * 3)
    for i in range(0, len(pixels), 3):
        pixels[i] = _BG[0]
        pixels[i + 1] = _BG[1]
        pixels[i + 2] = _BG[2]

    for _depth, pa, pb, pc, shade in drawn:
        r = min(255, int(_BASE[0] * shade))
        g = min(255, int(_BASE[1] * shade))
        b = min(255, int(_BASE[2] * shade))
        _fill_triangle(pixels, size, pa, pb, pc, (r, g, b))

    return pixels


def _fill_triangle(pixels: bytearray, size: int, pa, pb, pc, colour) -> None:
    """Scanline fill of one screen-space triangle into the RGB buffer."""
    pts = sorted((pa, pb, pc), key=lambda p: p[1])
    (x0, y0), (x1, y1), (x2, y2) = pts
    if y2 - y0 < 1:
        return

    def edge_x(y, p, q):
        if q[1] == p[1]:
            return None
        # Only edges that actually span this row: without this check
        # the intersection is extrapolated past the edge's endpoints
        # and the fill streaks across the whole image.
        if not (min(p[1], q[1]) <= y <= max(p[1], q[1])):
            return None
        t = (y - p[1]) / (q[1] - p[1])
        return p[0] + t * (q[0] - p[0])

    y_start = max(0, math.ceil(y0))
    y_end = min(size - 1, math.floor(y2))
    for y in range(y_start, y_end + 1):
        xs = []
        for p, q in ((pts[0], pts[1]), (pts[1], pts[2]), (pts[0], pts[2])):
            x = edge_x(y + 0.5, p, q)
            if x is not None:
                xs.append(x)
        if len(xs) < 2:
            continue
        # Floor/ceil (not ceil/floor): neighbouring triangles share
        # edges, and rounding inward leaves 1px gaps between them.
        xa, xb = int(math.floor(min(xs))), int(math.ceil(max(xs)))
        xa = max(0, xa)
        xb = min(size - 1, xb)
        row = y * size * 3
        for x in range(xa, xb + 1):
            i = row + x * 3
            pixels[i] = colour[0]
            pixels[i + 1] = colour[1]
            pixels[i + 2] = colour[2]


def png_diff_fraction(png_a: bytes, png_b: bytes, threshold: int = 12) -> float | None:
    """Fraction of pixels that differ between two ``render_png`` images.

    The optimizer renders the same 3/4 view before and after
    decimation; a big silhouette change means the decimator hurt the
    model even if the triangle numbers look fine. Returns None when
    either image cannot be decoded (the caller then skips the check
    instead of failing the asset over a thumbnail).
    """
    a = _decode_render_png(png_a)
    b = _decode_render_png(png_b)
    if a is None or b is None or a[0] != b[0]:
        return None
    (size, px_a), (_, px_b) = a, b
    changed = 0
    total = size * size
    for i in range(0, len(px_a), 3):
        if (
            abs(px_a[i] - px_b[i]) > threshold
            or abs(px_a[i + 1] - px_b[i + 1]) > threshold
            or abs(px_a[i + 2] - px_b[i + 2]) > threshold
        ):
            changed += 1
    return changed / total if total else 0.0


def _decode_render_png(data: bytes):
    """(size, RGB bytearray) for a PNG written by ``render_png``.

    Only the writer's own layout is supported: 8-bit RGB, filter 0
    on every row. Anything else returns None — the diff is advisory,
    never a reason to crash.
    """
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            if length < 13:
                return None
            width, height, depth, colour = struct.unpack(">IIBB", chunk[:10])
            if depth != 8 or colour != 2 or width != height:
                return None
        elif tag == b"IDAT":
            idat += chunk
        elif tag == b"IEND":
            break
        pos += 8 + length + 4
    if not width or not idat:
        return None
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    stride = width * 3
    if len(raw) < height * (stride + 1):
        return None
    pixels = bytearray(height * stride)
    for y in range(height):
        row = raw[y * (stride + 1) : (y + 1) * (stride + 1)]
        if not row or row[0] != 0:  # render_png writes filter 0 only
            return None
        pixels[y * stride : (y + 1) * stride] = row[1 : stride + 1]
    return width, pixels


def thumbnail_for(model_path: Path, cache_dir: Path, size: int = 192) -> Path | None:
    """Cached PNG thumbnail for a model (generated once, by sha256).

    Returns the thumbnail path, or None when the model cannot be
    previewed yet (.blend without Blender, unparsable, trimesh missing
    for FBX/GLB).
    """
    if model_path.suffix.lower() == ".blend":
        from .blend import blend_thumbnail

        return blend_thumbnail(model_path, cache_dir, size=size)
    try:
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    except OSError:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{digest}.png"
    if out.exists():
        return out
    geom = mesh_geometry(model_path)
    if geom is None:
        return None
    verts, faces = geom
    try:
        out.write_bytes(render_png(verts, faces, size=size))
    except Exception:
        return None
    return out
