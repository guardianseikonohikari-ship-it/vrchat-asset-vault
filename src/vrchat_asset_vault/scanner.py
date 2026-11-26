"""Recursive indexer: find 3D models + textures without moving anything.

Supported model extensions: .fbx .obj .glb .gltf .blend
Supported texture extensions: .png .jpg .jpeg .tga .exr .hdr .bmp .tiff

Triangle counting:
- .obj: counted directly from faces (no dependency).
- .fbx / .glb / .gltf: counted with trimesh when installed, else None.
- .blend: None here — thumbnails/stats for .blend come from Blender
  headless in a later step, never by guessing.
"""
from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

MODEL_EXTS = {".fbx", ".obj", ".glb", ".gltf", ".blend"}
TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".hdr", ".bmp", ".tiff"}


@dataclass
class MeshInfo:
    triangles: int | None = None
    materials: int | None = None
    scale_factor: float | None = None
    # Packed-texture stats from inside a .blend (probe); neighbouring
    # files are measured separately in scan() and merged there.
    max_texture_px: int | None = None
    texture_count: int = 0
    texture_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class FoundAsset:
    path: Path
    size_bytes: int
    sha256: str
    triangles: int | None = None
    materials: int | None = None
    scale_factor: float | None = None
    max_texture_px: int | None = None
    texture_count: int = 0
    texture_bytes: int = 0
    warnings: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def count_obj_triangles(path: Path) -> int:
    """Count triangles in a Wavefront OBJ by triangulating n-gon faces."""
    tris = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("f "):
                verts = len(line.split()) - 1
                if verts >= 3:
                    tris += verts - 2
    return tris


def analyze_obj(path: Path) -> MeshInfo:
    """One pass over an OBJ: triangles + distinct materials (usemtl)."""
    tris = 0
    materials: set[str] = set()
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("f "):
                verts = len(line.split()) - 1
                if verts >= 3:
                    tris += verts - 2
            elif line.startswith("usemtl "):
                name = line[7:].strip()
                if name:
                    materials.add(name)
    return MeshInfo(triangles=tris, materials=len(materials))


def fbx_unit_scale_factor(path: Path) -> float | None:
    """UnitScaleFactor from a binary FBX GlobalSettings node, or None.

    Binary FBX stores it as a P-record inside Properties70:
    P: "UnitScaleFactor", "double", "", "", <double>. The name is a
    string property ('S' + uint32 length + bytes), so we anchor on the
    exact bytes b'\\x53\\x0f\\x00\\x00\\x00UnitScaleFactor' (15 =
    len("UnitScaleFactor")) — that also avoids matching
    "OriginalUnitScaleFactor". After the name come two empty string
    properties and then 'D' + 8-byte little-endian double.

    Blender's default export writes 0.01, which is why Blender models
    famously arrive 100x too small in Unity unless the import Scale
    Factor is fixed. A missing node means "no opinion" (None), never a
    guessed 1.0.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    anchor = b"\x53\x0f\x00\x00\x00UnitScaleFactor"
    i = data.find(anchor)
    if i < 0:
        return None
    pos = i + len(anchor)
    # Walk the next few properties (two empty strings, then the double).
    for _ in range(4):
        if pos >= len(data):
            return None
        code = data[pos]
        pos += 1
        if code == 0x53:  # 'S' string: uint32 length + bytes
            if pos + 4 > len(data):
                return None
            (length,) = struct.unpack("<I", data[pos : pos + 4])
            pos += 4 + length
        elif code == 0x44:  # 'D' double
            if pos + 8 > len(data):
                return None
            (value,) = struct.unpack("<d", data[pos : pos + 8])
            return value if value > 0 else None
        elif code == 0x49:  # 'I' int32
            pos += 4
        elif code == 0x46:  # 'F' float
            pos += 4
        elif code == 0x4C:  # 'L' int64
            pos += 8
        elif code == 0x59:  # 'Y' int16
            pos += 2
        elif code in (0x43, 0x42):  # 'C' bool, 'B' byte
            pos += 1
        else:
            return None
    return None


def _trimesh_materials(scene) -> int | None:
    """Distinct materials in a trimesh scene, or None if unknowable.

    A mesh with no material at all counts as 0 — Unity assigns its
    default in that case, and 0 is what the file actually says.
    """
    try:
        mats = getattr(scene, "materials", None)
        if mats:
            return len(mats)
        seen: set[int] = set()
        geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
        for geom in geoms:
            visual = getattr(geom, "visual", None)
            mat = getattr(visual, "material", None) if visual is not None else None
            if mat is not None:
                seen.add(id(mat))
        return len(seen)
    except Exception:
        return None


def analyze_mesh(path: Path) -> MeshInfo:
    """Triangles + material count for one model file.

    - .obj: counted directly (no dependency).
    - .fbx / .glb / .gltf: counted with trimesh when installed, else None.
    - .blend: None here — stats for .blend come from Blender headless
      in a later step, never by guessing.
    """
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return analyze_obj(path)
    if suffix in {".fbx", ".glb", ".gltf"}:
        # Scale lives in the file itself, independent of trimesh:
        # even an FBX trimesh cannot parse still tells us its scale.
        scale = fbx_unit_scale_factor(path) if suffix == ".fbx" else None
        try:
            import trimesh  # type: ignore

            scene = trimesh.load(str(path), force="scene")
            total = 0
            geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
            for geom in geoms:
                faces = getattr(geom, "faces", None)
                if faces is not None:
                    total += len(faces)
            return MeshInfo(
                triangles=total,
                materials=_trimesh_materials(scene),
                scale_factor=scale,
            )
        except ImportError:
            return MeshInfo(
                warnings=["trimesh not installed — triangle count unknown"],
                scale_factor=scale,
            )
        except Exception as exc:  # corrupt / unsupported file: report, don't crash
            return MeshInfo(
                warnings=[f"could not parse mesh: {exc}"], scale_factor=scale
            )
    if suffix == ".blend":
        # Real stats from Blender headless — never guessed. When
        # Blender is missing, the card says so honestly instead of
        # showing invented numbers. One Blender start per file (~1-2 s);
        # libraries with many .blend files scan slower, by design.
        from .blend import blend_stats, unavailable_reason

        stats = blend_stats(path, timeout=60)
        if stats is None:
            return MeshInfo(
                warnings=[unavailable_reason() or "blend stats unavailable"]
            )
        return MeshInfo(
            triangles=stats["triangles"],
            materials=stats["materials"],
            max_texture_px=stats["max_texture_px"] or None,
            texture_count=stats["texture_count"],
            texture_bytes=stats["texture_bytes"],
            warnings=list(stats["warnings"]),
        )
    return MeshInfo()


def count_triangles(path: Path) -> tuple[int | None, list[str]]:
    """Backwards-compatible wrapper: (triangles, warnings)."""
    info = analyze_mesh(path)
    return info.triangles, info.warnings


def scan(root: Path) -> list[FoundAsset]:
    from .textures import texture_stats_for

    found: list[FoundAsset] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in MODEL_EXTS:
                continue
            info = analyze_mesh(path)
            tex = texture_stats_for(path)
            # .blend probe stats (packed textures) merge with the
            # neighbouring-file stats: biggest side wins, counts add.
            max_px = tex["max_px"]
            if info.max_texture_px:
                max_px = max(max_px or 0, info.max_texture_px)
            found.append(
                FoundAsset(
                    path=path,
                    size_bytes=path.stat().st_size,
                    sha256=sha256_of(path),
                    triangles=info.triangles,
                    materials=info.materials,
                    scale_factor=info.scale_factor,
                    max_texture_px=max_px,
                    texture_count=tex["count"] + info.texture_count,
                    texture_bytes=tex["total_bytes"] + info.texture_bytes,
                    warnings=info.warnings,
                )
            )
    return found


def find_textures_for(model_path: Path) -> list[Path]:
    """Textures sitting next to the model (same stem or same folder)."""
    folder = model_path.parent
    stem = model_path.stem.lower()
    out: list[Path] = []
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in TEXTURE_EXTS:
            if p.stem.lower().startswith(stem) or p.stem.lower() in stem:
                out.append(p)
    return sorted(out)
