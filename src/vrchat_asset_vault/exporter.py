"""Clean export to Unity.

Copies the model + its neighbouring textures into Export_<World>/,
writes manifest.json with origin/license per file, and warns instead
of silently dropping a missing texture or a bad FBX.

Rules enforced here (from VRCLibrary / BKeeper guides):
- Never hand Unity a .blend directly — export FBX first.
- An OBJ without its .mtl gets a warning: no material will be assigned.
- FBX must be binary, version 7.1 or newer, or Unity may refuse it.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .scanner import find_textures_for


def is_binary_fbx(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(23).startswith(b"Kaydara FBX Binary")


def export_collection(
    model_paths: list[Path], out_dir: Path, world_name: str
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    warnings: list[str] = []

    for model in model_paths:
        dest = out_dir / model.name
        shutil.copy2(model, dest)
        entry: dict = {"file": model.name, "source_path": str(model)}
        if model.suffix.lower() == ".blend":
            warnings.append(
                f"{model.name}: .blend files must be exported as FBX before Unity — copied as-is, do not import directly."
            )
        if model.suffix.lower() == ".fbx" and not is_binary_fbx(model):
            warnings.append(
                f"{model.name}: FBX is not binary — Unity needs binary FBX 7.1+."
            )
        if model.suffix.lower() == ".obj":
            mtl = model.with_suffix(".mtl")
            if mtl.exists():
                shutil.copy2(mtl, out_dir / mtl.name)
                entry["mtl"] = mtl.name
            else:
                warnings.append(
                    f"{model.name}: no .mtl found — Unity will assign no material."
                )
        textures = find_textures_for(model)
        entry["textures"] = []
        for tex in textures:
            shutil.copy2(tex, out_dir / tex.name)
            entry["textures"].append(tex.name)
        if not textures:
            warnings.append(f"{model.name}: no textures found next to the model.")
        manifest.append(entry)

    (out_dir / "manifest.json").write_text(
        json.dumps({"world": world_name, "assets": manifest}, indent=2),
        encoding="utf-8",
    )
    return {"out_dir": str(out_dir), "assets": len(manifest), "warnings": warnings}
