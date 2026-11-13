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
from dataclasses import dataclass, field
from pathlib import Path

MODEL_EXTS = {".fbx", ".obj", ".glb", ".gltf", ".blend"}
TEXTURE_EXTS = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".hdr", ".bmp", ".tiff"}


@dataclass
class FoundAsset:
    path: Path
    size_bytes: int
    sha256: str
    triangles: int | None = None
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


def count_triangles(path: Path) -> tuple[int | None, list[str]]:
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return count_obj_triangles(path), []
    if suffix in {".fbx", ".glb", ".gltf"}:
        try:
            import trimesh  # type: ignore

            scene = trimesh.load(str(path), force="scene")
            total = 0
            geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
            for geom in geoms:
                faces = getattr(geom, "faces", None)
                if faces is not None:
                    total += len(faces)
            return total, []
        except ImportError:
            return None, ["trimesh not installed — triangle count unknown"]
        except Exception as exc:  # corrupt / unsupported file: report, don't crash
            return None, [f"could not parse mesh: {exc}"]
    if suffix == ".blend":
        return None, ["blend stats need Blender headless (planned)"]
    return None, []


def scan(root: Path) -> list[FoundAsset]:
    found: list[FoundAsset] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in MODEL_EXTS:
                continue
            triangles, warnings = count_triangles(path)
            found.append(
                FoundAsset(
                    path=path,
                    size_bytes=path.stat().st_size,
                    sha256=sha256_of(path),
                    triangles=triangles,
                    warnings=warnings,
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
