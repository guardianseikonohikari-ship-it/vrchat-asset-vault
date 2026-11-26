"""One-click Quest optimizer — make a model (or a whole world) Quest-ready.

Takes one asset or a collection and produces Quest-ready *copies*:
decimated meshes, downscaled textures, fixed FBX scale. The original
files are never modified — everything lands under ``Optimized_<World>/``,
with a before/after report so the creator can see exactly what changed.

Two engines, one interface (see the research plan):
- **Blender headless** (primary): the only path that reads and writes
  FBX, opens ``.blend`` natively, and keeps UVs exactly. Needs Blender
  installed; without it, FBX/``.blend`` are skipped with a clear reason.
- **trimesh + fast-simplification** (fallback, OBJ/GLB/GLTF only):
  quadric edge collapse, UVs remapped by nearest surviving vertex,
  materials preserved. trimesh cannot read or write FBX at all, so
  that format never goes through this engine.

Safety rules (the plan's §2, enforced here, not just documented):
- Originals are never touched; the fail-safe copies the original
  unchanged whenever a verification check fails.
- Collapse only, never remesh (a remesh throws UVs away entirely).
- Meshes with shape keys, armatures or animation are skipped, with a
  reason — decimation would destroy them.
- Favorites (hero assets) are skipped by the Aggressive preset and
  flagged for a visual check under Balanced.
- Atlasing, LODs and avatars are out of v1 scope.

Verification gate (before/after, measured with the Vault's own code):
triangle count within tolerance of the target, texture size within the
preset, format checks, bounding box within 1%, no NaN vertices, and a
thumbnail diff that flags (not fails) a changed silhouette.
"""
from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .budget import (
    MIN_DECIMATE_TRIANGLES,
    QUEST_TRIANGLE_BUDGET,
    QUEST_WORLD_SIZE_BYTES,
    OptimizePreset,
    fmt_bytes,
)
from .exporter import fbx_version, is_binary_fbx, write_credits
from .preview import mesh_geometry, png_diff_fraction, render_png
from .scanner import MODEL_EXTS, analyze_mesh, find_textures_for
from .textures import downscale_texture, texture_stats_for

# A thumbnail that changed this much means the silhouette moved —
# the numbers pass, but the user is told to look at it.
VISUAL_DIFF_FLAG = 0.25
# Per-channel RGB difference that counts as "this pixel changed".
VISUAL_DIFF_THRESHOLD = 12


class OptimizeCancelled(Exception):
    """The user cancelled a collection run between assets."""


@dataclass
class AssetReport:
    """One asset's before/after story. Serializable via ``to_dict``."""

    source: Path
    output: Path | None = None
    status: str = "failed"  # optimized | unchanged | skipped | failed
    reason: str = ""
    engine: str = ""  # blender | trimesh | copy | ""
    triangles_before: int | None = None
    triangles_after: int | None = None
    target_triangles: int | None = None
    size_before: int = 0
    size_after: int = 0
    texture_bytes_before: int = 0
    texture_bytes_after: int = 0
    max_texture_px_before: int | None = None
    max_texture_px_after: int | None = None
    warnings: list[str] = field(default_factory=list)
    check_visually: bool = False
    scale_fixed: bool = False

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "output": str(self.output) if self.output else None,
            "status": self.status,
            "reason": self.reason,
            "engine": self.engine,
            "triangles_before": self.triangles_before,
            "triangles_after": self.triangles_after,
            "target_triangles": self.target_triangles,
            "size_before": self.size_before,
            "size_after": self.size_after,
            "texture_bytes_before": self.texture_bytes_before,
            "texture_bytes_after": self.texture_bytes_after,
            "max_texture_px_before": self.max_texture_px_before,
            "max_texture_px_after": self.max_texture_px_after,
            "warnings": list(self.warnings),
            "check_visually": self.check_visually,
            "scale_fixed": self.scale_fixed,
        }


@dataclass
class OptimizeReport:
    """The whole collection run: per-asset reports + world totals."""

    world: str
    preset: OptimizePreset
    out_dir: Path
    assets: list[AssetReport] = field(default_factory=list)

    @property
    def totals(self) -> dict:
        by_status: dict[str, int] = {}
        for rep in self.assets:
            by_status[rep.status] = by_status.get(rep.status, 0) + 1
        tris_before = sum(r.triangles_before or 0 for r in self.assets)
        tris_after = sum(r.triangles_after or 0 for r in self.assets)
        unknown_tris = sum(1 for r in self.assets if r.triangles_after is None)
        tex_before = sum(r.texture_bytes_before for r in self.assets)
        tex_after = sum(r.texture_bytes_after for r in self.assets)
        size_after = sum(r.size_after for r in self.assets)
        return {
            "assets": len(self.assets),
            "by_status": by_status,
            "triangles_before": tris_before,
            "triangles_after": tris_after,
            "unknown_triangle_counts": unknown_tris,
            "texture_bytes_before": tex_before,
            "texture_bytes_after": tex_after,
            "size_after": size_after,
            "quest_triangles_ok": tris_after <= QUEST_TRIANGLE_BUDGET,
            "quest_size_ok": size_after + tex_after <= QUEST_WORLD_SIZE_BYTES,
        }

    @property
    def world_warnings(self) -> list[str]:
        warnings: list[str] = []
        totals = self.totals
        if not totals["quest_triangles_ok"]:
            heaviest = sorted(
                (r for r in self.assets if r.triangles_after),
                key=lambda r: r.triangles_after or 0,
                reverse=True,
            )[:3]
            names = ", ".join(
                f"{r.source.name} ({r.triangles_after:,} tris)" for r in heaviest
            )
            warnings.append(
                f"Still over the {QUEST_TRIANGLE_BUDGET:,} Quest triangle "
                f"budget ({totals['triangles_after']:,}) — heaviest: {names}."
            )
        if not totals["quest_size_ok"]:
            warnings.append(
                f"Still over the 100 MB Quest size limit "
                f"({fmt_bytes(totals['size_after'] + totals['texture_bytes_after'])})."
            )
        if totals["unknown_triangle_counts"]:
            warnings.append(
                f"{totals['unknown_triangle_counts']} asset(s) have unknown "
                "triangle counts — totals are a lower bound."
            )
        return warnings

    def to_dict(self) -> dict:
        return {
            "world": self.world,
            "preset": {
                "name": self.preset.name,
                "keep_ratio": self.preset.keep_ratio,
                "max_texture_px": self.preset.max_texture_px,
                "per_asset_tri_cap": self.preset.per_asset_tri_cap,
            },
            "out_dir": str(self.out_dir),
            "assets": [r.to_dict() for r in self.assets],
            "totals": self.totals,
            "warnings": self.world_warnings,
        }


# ------------------------------------------------------------------ measure

def _measure(src: Path) -> dict:
    """What the Vault already knows about a model, without Blender.

    FBX / .blend triangle counts are None here on purpose: trimesh
    cannot read FBX, and .blend stats need a Blender run — the Blender
    engine measures those itself and reports them. Neighbouring
    textures and the FBX scale factor are readable without Blender.
    """
    suffix = src.suffix.lower()
    size = src.stat().st_size if src.is_file() else 0
    if suffix in {".obj", ".glb", ".gltf"}:
        info = analyze_mesh(src)
        tex = texture_stats_for(src)
        return {
            "triangles": info.triangles,
            "materials": info.materials,
            "scale_factor": None,
            "max_texture_px": tex["max_px"],
            "texture_bytes": tex["total_bytes"],
            "warnings": list(info.warnings),
        }
    if suffix == ".fbx":
        from .scanner import fbx_unit_scale_factor

        tex = texture_stats_for(src)
        return {
            "triangles": None,
            "materials": None,
            "scale_factor": fbx_unit_scale_factor(src),
            "max_texture_px": tex["max_px"],
            "texture_bytes": tex["total_bytes"],
            "warnings": [],
        }
    # .blend: neighbouring textures only; packed ones are measured
    # (and scaled) by the Blender script itself.
    tex = texture_stats_for(src)
    return {
        "triangles": None,
        "materials": None,
        "scale_factor": None,
        "max_texture_px": tex["max_px"],
        "texture_bytes": tex["total_bytes"],
        "warnings": [],
    }


def _bbox_of(verts) -> tuple | None:
    """(min, max) per axis for a vertex list, or None when empty."""
    if not verts:
        return None
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _bbox_preserved(before: tuple | None, after: tuple | None, tol: float = 0.01) -> bool:
    """True when every axis span survived within ``tol`` (1% default).

    Catches scale accidents and collapsed geometry. A flat axis
    (span 0, e.g. a plane) gets an absolute tolerance instead.
    """
    if before is None or after is None:
        return True  # nothing to compare — the caller reports it instead
    for axis in range(3):
        span_before = before[1][axis] - before[0][axis]
        span_after = after[1][axis] - after[0][axis]
        allowed = max(abs(span_before) * tol, 1e-6)
        if abs(span_after - span_before) > allowed:
            return False
    return True


def _has_nan(verts) -> bool:
    return any(
        math.isnan(float(c)) or math.isinf(float(c)) for v in verts for c in v
    )


def _thumbnail_diff(src: Path, out: Path) -> float | None:
    """Fraction of changed pixels between the before/after 3/4 views.

    None when either side cannot be rendered (FBX without Blender's
    snapshots, unparsable file) — the check is advisory, never fatal.
    """
    g0 = mesh_geometry(src)
    g1 = mesh_geometry(out)
    if g0 is None or g1 is None:
        return None
    try:
        png0 = render_png(g0[0], g0[1], size=96)
        png1 = render_png(g1[0], g1[1], size=96)
    except Exception:
        return None
    return png_diff_fraction(png0, png1, threshold=VISUAL_DIFF_THRESHOLD)


# ------------------------------------------------------- copy + textures

def _copy_original(src: Path, out_dir: Path, out_name: str) -> tuple[Path, list[Path]]:
    """Copy a model + its .mtl + neighbouring textures, unchanged.

    Used for "unchanged", "skipped" and fail-safe "failed" assets: the
    world still builds, with the original files.

    A copy keeps the ORIGINAL format: a .blend that was not converted
    must not wear the .fbx name ``_unique_out_name`` reserved for a
    real conversion (a .blend file named .fbx would fail to import).
    The .blend name is derived from the (deduped) out_name, so
    same-stem collisions stay deduped.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".blend" and Path(out_name).suffix.lower() != ".blend":
        out_name = str(Path(out_name).with_suffix(".blend"))
    out_model = out_dir / out_name
    shutil.copy2(src, out_model)
    if src.suffix.lower() == ".obj":
        mtl = src.with_suffix(".mtl")
        if mtl.exists():
            shutil.copy2(mtl, out_dir / mtl.name)
    copied: list[Path] = []
    for tex in find_textures_for(src):
        dst = out_dir / tex.name
        shutil.copy2(tex, dst)
        copied.append(dst)
    return out_model, copied


def _downscale_textures(
    src: Path, out_dir: Path, preset: OptimizePreset, report: AssetReport
) -> None:
    """Downscale the asset's textures inside ``out_dir``, in place.

    Textures already there (written by the Blender export) are scaled
    where they sit; missing ones are copied from the source folder
    first. Same filenames, so .mtl / material references stay valid.
    """
    for tex in find_textures_for(src):
        dst = out_dir / tex.name
        try:
            if not dst.exists():
                shutil.copy2(tex, dst)
        except OSError as exc:
            report.warnings.append(f"could not copy texture {tex.name}: {exc}")
            continue
        result = downscale_texture(dst, dst, preset.max_texture_px)
        if result["warning"]:
            report.warnings.append(result["warning"])
        if result["status"] == "downscaled":
            report.warnings.append(
                f"texture {tex.name}: "
                f"{result['size_before'][0]}x{result['size_before'][1]} → "
                f"{result['size_after'][0]}x{result['size_after'][1]}"
            )


def _measure_output(out_model: Path, report: AssetReport) -> dict:
    """Triangle/texture facts about an optimized (or copied) output file."""
    tex = texture_stats_for(out_model)
    info = analyze_mesh(out_model)
    return {
        "triangles": info.triangles,
        "max_texture_px": tex["max_px"],
        "texture_bytes": tex["total_bytes"],
        "warnings": list(info.warnings),
    }


# ------------------------------------------------------- trimesh engine

def _nearest_vertex_map(src_points, query_points):
    """For each query point, the index of the nearest source point.

    Brute force for small inputs (exact); a uniform-grid search for
    large ones — no scipy dependency. The grid cell is ~1/64 of the
    bounding-box diagonal, and the search expands in rings until the
    best hit is closer than the next unsearched ring, so the result
    is the true nearest vertex, not just a nearby one.
    """
    import numpy as np

    src = np.asarray(src_points, dtype=np.float64)
    query = np.asarray(query_points, dtype=np.float64)
    n_src, n_q = len(src), len(query)
    out = np.zeros(n_q, dtype=np.int64)
    if n_src == 0 or n_q == 0:
        return out
    if n_src * n_q <= 4_000_000:
        for i in range(0, n_q, 512):
            diff = query[i : i + 512, None, :] - src[None, :, :]
            out[i : i + 512] = np.argmin((diff * diff).sum(-1), axis=1)
        return out

    mins = src.min(axis=0)
    span = src.max(axis=0) - mins
    diag = float(np.linalg.norm(span)) or 1.0
    cell = diag / 64.0
    src_cell = np.floor((src - mins) / cell).astype(np.int64)
    grid: dict[tuple, list] = {}
    for i, c in enumerate(src_cell):
        grid.setdefault((int(c[0]), int(c[1]), int(c[2])), []).append(i)
    q_cell = np.floor((query - mins) / cell).astype(np.int64)
    groups: dict[tuple, list] = {}
    for qi, c in enumerate(q_cell):
        groups.setdefault((int(c[0]), int(c[1]), int(c[2])), []).append(qi)

    for qc, qidxs in groups.items():
        qidxs = np.asarray(qidxs, dtype=np.int64)
        qpts = query[qidxs]
        best = np.full(len(qidxs), -1, dtype=np.int64)
        best_d2 = np.full(len(qidxs), np.inf)
        ring = 0
        while True:
            ring += 1
            cand: list[int] = []
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    for dz in range(-ring, ring + 1):
                        if max(abs(dx), abs(dy), abs(dz)) != ring:
                            continue
                        cand.extend(
                            grid.get((qc[0] + dx, qc[1] + dy, qc[2] + dz), ())
                        )
            if cand:
                cand_arr = np.asarray(sorted(set(cand)), dtype=np.int64)
                diff = qpts[:, None, :] - src[cand_arr][None, :, :]
                d2 = (diff * diff).sum(-1)
                j = np.argmin(d2, axis=1)
                row = np.arange(len(qidxs))
                better = d2[row, j] < best_d2
                best[better] = cand_arr[j[better]]
                best_d2[better] = d2[row, j][better]
            # Any point not yet searched is at least ring*cell away.
            if bool(np.all(best_d2 <= (ring * cell) ** 2)) or ring >= 8:
                break
        missing = np.where(best < 0)[0]
        for qi in missing:  # isolated queries: brute force this one
            diff = src - qpts[qi]
            best[qi] = int(np.argmin((diff * diff).sum(-1)))
        out[qidxs] = best
    return out


def _simplify_geometry_trimesh(geom, target_faces: int):
    """Clean + quadric-deimate one trimesh geometry, keeping UVs/material.

    Returns (geometry, changed). UVs are remapped through the nearest
    surviving vertex — the collapse moves vertices, so an exact UV
    carry-over is impossible without Blender; the remap is close
    (the survivor sits a fraction of an edge away) and the report
    says so plainly. Vertex colours are remapped the same way.
    """
    import numpy as np
    import trimesh
    from fast_simplification import simplify

    # Clean-first (plan §1a): degenerate faces feed the quadric
    # garbage normals; loose geometry is removed, small disconnected
    # components are NOT (a candle flame can be intentional).
    geom.merge_vertices()
    # trimesh 5.x dropped remove_degenerate_faces(); the equivalent
    # is update_faces(nondegenerate_faces()).
    geom.update_faces(geom.nondegenerate_faces())
    geom.remove_unreferenced_vertices()
    try:
        geom.fix_normals()
    except Exception:
        # fix_normals needs scipy (body_count); the simplifier's own
        # normals are already sane, so losing it is cosmetic.
        pass
    faces = len(geom.faces)
    if faces <= target_faces:
        return geom, False

    visual = getattr(geom, "visual", None)
    uv = None
    if visual is not None:
        raw_uv = getattr(visual, "uv", None)
        if raw_uv is not None:
            uv = np.asarray(raw_uv, dtype=np.float64)
    vertex_colors = None
    if visual is not None:
        raw_colors = getattr(visual, "vertex_colors", None)
        if raw_colors is not None:
            vertex_colors = np.asarray(raw_colors)

    verts, new_faces, _collapses = simplify(
        geom.vertices.view(np.ndarray),
        geom.faces.view(np.ndarray),
        target_count=int(target_faces),
        return_collapses=True,
    )
    new_visual = None
    material = getattr(visual, "material", None) if visual is not None else None
    if uv is not None and len(uv) == len(geom.vertices):
        idx = _nearest_vertex_map(geom.vertices.view(np.ndarray), verts)
        new_visual = trimesh.visual.TextureVisuals(uv=uv[idx], material=material)
    elif vertex_colors is not None and len(vertex_colors) == len(geom.vertices):
        idx = _nearest_vertex_map(geom.vertices.view(np.ndarray), verts)
        new_visual = trimesh.visual.ColorVisuals(
            mesh=None, vertex_colors=vertex_colors[idx]
        )
    elif material is not None:
        new_visual = trimesh.visual.TextureVisuals(uv=None, material=material)
    new_geom = trimesh.Trimesh(
        vertices=verts, faces=new_faces, visual=new_visual, process=False
    )
    return new_geom, True


def _count_scene_materials(scene) -> int:
    """Distinct materials in a trimesh scene (same rule as the scanner)."""
    try:
        seen: set[int] = set()
        geoms = scene.geometry.values() if hasattr(scene, "geometry") else [scene]
        for geom in geoms:
            visual = getattr(geom, "visual", None)
            mat = getattr(visual, "material", None) if visual is not None else None
            if mat is not None:
                seen.add(id(mat))
        return len(seen)
    except Exception:
        return 0


def _optimize_with_trimesh(src: Path, out_path: Path, target_faces: int) -> dict:
    """Decimate an OBJ/GLB/GLTF with trimesh. Returns engine facts.

    Raises on any failure (the caller turns it into a "failed" report
    with the fail-safe copy). Never touches the source file.
    """
    import trimesh

    scene = trimesh.load(str(src), force="scene")
    geoms = scene.geometry if hasattr(scene, "geometry") else {"mesh": scene}
    total_faces = sum(len(g.faces) for g in geoms.values())
    changed_any = False
    for name, geom in list(geoms.items()):
        share = len(geom.faces) / total_faces if total_faces else 0
        geom_target = max(1, int(round(target_faces * share)))
        new_geom, changed = _simplify_geometry_trimesh(geom, geom_target)
        if changed:
            changed_any = True
            if hasattr(scene, "geometry"):
                scene.geometry[name] = new_geom
            else:
                scene = new_geom
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".obj":
        # Name the .mtl after the model, or every OBJ in one output
        # folder would overwrite the same "material.mtl".
        scene.export(str(out_path), mtl_name=f"{out_path.stem}.mtl")
    else:
        scene.export(str(out_path))
    after = analyze_mesh(out_path)
    return {
        "engine": "trimesh",
        "triangles_after": after.triangles,
        "materials_after": _count_scene_materials(
            trimesh.load(str(out_path), force="scene")
        ),
        "changed": changed_any,
        "warnings": (
            ["UVs approximated (nearest-vertex remap) — use Blender for exact UVs"]
            if changed_any
            else []
        ),
    }


# ------------------------------------------------------- verification gate

def _verify_trimesh_output(
    src: Path,
    out_path: Path,
    target: int | None,
    before_bbox,
    preset: OptimizePreset,
) -> tuple[list[str], float | None]:
    """Hard failures for a trimesh-path output (empty list = pass).

    Also returns the thumbnail-diff fraction (None when unrenderable).
    """
    failures: list[str] = []
    info = analyze_mesh(out_path)
    if info.triangles is None:
        failures.append("optimized file could not be re-read (triangle count unknown)")
    else:
        if info.triangles <= 0:
            failures.append("optimized mesh has no triangles")
        elif target is not None and info.triangles > int(target * 1.05):
            failures.append(
                f"decimator overshot: {info.triangles:,} triangles, target {target:,}"
            )
    geom = mesh_geometry(out_path)
    if geom is None:
        failures.append("optimized file could not be re-read (no geometry)")
    else:
        verts, _faces = geom
        if _has_nan(verts):
            failures.append("optimized mesh contains NaN vertices")
        elif not _bbox_preserved(before_bbox, _bbox_of(verts)):
            failures.append(
                "bounding box changed by more than 1% — the model may have "
                "been scaled or collapsed"
            )
    tex = texture_stats_for(out_path)
    if tex["max_px"] is not None and tex["max_px"] > preset.max_texture_px:
        failures.append(
            f"texture still {tex['max_px']}px after downscale "
            f"(limit {preset.max_texture_px}px)"
        )
    if out_path.suffix.lower() == ".obj" and not out_path.is_file():
        failures.append("optimized OBJ was not written")
    return failures, _thumbnail_diff(src, out_path)


def _verify_blender_output(
    src: Path,
    out_path: Path,
    result: dict,
    preset: OptimizePreset,
) -> list[str]:
    """Hard failures for a Blender-path output (empty list = pass)."""
    failures: list[str] = []
    if not out_path.is_file():
        return ["Blender reported success but wrote no output file"]
    if out_path.suffix.lower() == ".fbx":
        if not is_binary_fbx(out_path):
            failures.append("optimized FBX is not binary")
        else:
            version = fbx_version(out_path)
            if version is not None and version < 7100:
                failures.append(f"optimized FBX version {version} is below 7.1")
        # The scale fix is the point of the re-export: verify it landed.
        # The expected factor is the metre-to-centimetre factor for the
        # scene's units (100.0 for a metre scene) — NOT 1.0. Blender's
        # FBX exporter writes 100 x the scene unit scale into
        # GlobalSettings.UnitScaleFactor with FBX_SCALE_ALL, and Unity
        # (Scale Factor 1 + Convert Units) reads that as the authored
        # size with scale 1 on every transform. A 1.0 factor with
        # metre vertices would import 100x too small.
        from .scanner import fbx_unit_scale_factor

        scale = fbx_unit_scale_factor(out_path)
        expected = result.get("unit_scale_factor")
        if expected is not None:
            if scale is None:
                failures.append("optimized FBX has no UnitScaleFactor")
            elif abs(scale - expected) / expected > 0.01:
                failures.append(
                    f"optimized FBX UnitScaleFactor is {scale}, expected "
                    f"{expected} (metre-to-centimetre factor for the scene)"
                )
    tris_after = result.get("triangles_after")
    target = result.get("target_triangles")
    if tris_after is not None:
        if tris_after <= 0:
            failures.append("optimized mesh has no triangles")
        elif target is not None and tris_after > int(target * 1.05):
            failures.append(
                f"decimator overshot: {tris_after:,} triangles, target {target:,}"
            )
    if not _bbox_preserved(result.get("bbox_before"), result.get("bbox_after")):
        failures.append(
            "bounding box changed by more than 1% — the model may have "
            "been scaled or collapsed"
        )
    tex = texture_stats_for(out_path)
    if tex["max_px"] is not None and tex["max_px"] > preset.max_texture_px:
        failures.append(
            f"texture still {tex['max_px']}px after downscale "
            f"(limit {preset.max_texture_px}px)"
        )
    return failures


# ------------------------------------------------------- optimize one asset

def _fail_safe_copy(src: Path, out_dir: Path, out_name: str, report: AssetReport) -> None:
    """Replace a bad optimization with the untouched originals."""
    out_model = out_dir / out_name
    try:
        if out_model.exists():
            out_model.unlink()
    except OSError:
        pass
    copied_model, _copied = _copy_original(src, out_dir, out_name)
    report.output = copied_model
    report.engine = "copy"
    try:
        report.size_after = copied_model.stat().st_size
    except OSError:
        report.size_after = 0
    tex = texture_stats_for(copied_model)
    report.texture_bytes_after = tex["total_bytes"]
    report.max_texture_px_after = tex["max_px"]


def _unique_out_name(src: Path, used_names: dict) -> str:
    """Output filename, de-duplicated within one run.

    Two models with the same filename in different folders must not
    overwrite each other in the shared output folder.
    """
    suffix = ".fbx" if src.suffix.lower() == ".blend" else src.suffix.lower()
    name = src.stem + suffix
    n = 1
    while name.lower() in used_names:
        n += 1
        name = f"{src.stem}_{n}{suffix}"
    used_names[name.lower()] = str(src)
    return name


def optimize_asset(
    src: Path,
    out_dir: Path,
    preset: OptimizePreset,
    *,
    favorite: bool = False,
    engine: str = "auto",
    out_name: str | None = None,
    cancel_event=None,
) -> AssetReport:
    """Optimize one model into ``out_dir``. Never modifies the source.

    ``engine``: "auto" (Blender when available, else trimesh),
    "blender" or "trimesh". FBX / .blend always need Blender; without
    it they are skipped with a reason, never silently converted.
    """
    from .blend import blender_available

    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_name is None:
        out_name = _unique_out_name(src, {})
    report = AssetReport(source=src)
    report.size_before = src.stat().st_size if src.is_file() else 0

    if not src.is_file():
        report.status = "failed"
        report.reason = f"file not found: {src}"
        return report
    suffix = src.suffix.lower()
    if suffix not in MODEL_EXTS:
        report.status = "failed"
        report.reason = f"unsupported format: {suffix}"
        return report

    before = _measure(src)
    report.triangles_before = before["triangles"]
    report.max_texture_px_before = before["max_texture_px"]
    report.texture_bytes_before = before["texture_bytes"]
    report.warnings.extend(before["warnings"])

    # Hero rule: a favourite is exactly the prop whose silhouette
    # matters. Aggressive never touches one; Balanced flags it.
    if favorite and preset.name == "Aggressive":
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.status = "skipped"
        report.reason = "favorite (hero asset) — Aggressive skips favorites"
        report.output = copied_model
        report.triangles_after = before["triangles"]
        report.size_after = report.size_before
        report.texture_bytes_after = before["texture_bytes"]
        report.max_texture_px_after = before["max_texture_px"]
        return report
    if favorite and preset.name == "Balanced":
        report.warnings.append("favorite (hero asset) — check the result visually")
        report.check_visually = True

    target = preset.target_triangles(before["triangles"])
    report.target_triangles = target
    needs_decimation = target is not None
    needs_textures = (
        before["max_texture_px"] is not None
        and before["max_texture_px"] > preset.max_texture_px
    )
    needs_scale_fix = before["scale_factor"] not in (None, 1.0)

    # The Blender path measures FBX / .blend triangles itself, so it
    # cannot take this early exit — it runs and decides there. And an
    # unknown triangle count (GLB without trimesh) is not "within
    # budget": the engine branch below reports it honestly instead.
    needs_blender_measure = suffix in {".fbx", ".blend"}
    if (
        before["triangles"] is not None
        and not needs_decimation
        and not needs_textures
        and not needs_scale_fix
        and not needs_blender_measure
    ):
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.status = "unchanged"
        report.reason = "already within budget"
        report.output = copied_model
        report.triangles_after = before["triangles"]
        report.size_after = report.size_before
        report.texture_bytes_after = before["texture_bytes"]
        report.max_texture_px_after = before["max_texture_px"]
        return report

    # --- engine selection -------------------------------------------
    want_blender = False
    if suffix in {".fbx", ".blend"}:
        want_blender = True  # only Blender reads/writes these
    elif engine == "blender":
        want_blender = True
    elif engine == "auto" and blender_available():
        want_blender = True

    out_model = out_dir / out_name
    if want_blender:
        if not blender_available():
            copied_model, _ = _copy_original(src, out_dir, out_name)
            report.status = "skipped"
            report.reason = (
                f"{suffix} needs Blender — install Blender to optimize "
                f"{suffix} files (OBJ/GLB work without it)"
            )
            report.output = copied_model
            report.triangles_after = before["triangles"]
            report.size_after = report.size_before
            report.texture_bytes_after = before["texture_bytes"]
            report.max_texture_px_after = before["max_texture_px"]
            return report
        return _optimize_with_blender(
            src, out_dir, out_name, preset, before, report, cancel_event
        )

    # --- trimesh path (OBJ / GLB / GLTF only) -----------------------
    if suffix in {".fbx", ".blend"}:
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.status = "skipped"
        report.reason = "trimesh cannot read or write FBX — use the Blender engine"
        report.output = copied_model
        report.triangles_after = before["triangles"]
        report.size_after = report.size_before
        report.texture_bytes_after = before["texture_bytes"]
        report.max_texture_px_after = before["max_texture_px"]
        return report
    try:
        import trimesh  # noqa: F401  (checked for the error message)
    except ImportError:
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.status = "skipped"
        report.reason = (
            "trimesh is not installed — install vrchat-asset-vault[mesh] "
            "to optimize OBJ/GLB without Blender"
        )
        report.output = copied_model
        report.triangles_after = before["triangles"]
        report.size_after = report.size_before
        report.texture_bytes_after = before["texture_bytes"]
        report.max_texture_px_after = before["max_texture_px"]
        return report

    geom_before = mesh_geometry(src)
    before_bbox = _bbox_of(geom_before[0]) if geom_before else None

    if not needs_decimation:
        # Texture-only: copy the model as-is, never re-export a mesh
        # that does not need decimation.
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.output = copied_model
        report.engine = "copy"
    else:
        try:
            result = _optimize_with_trimesh(src, out_model, target)
        except OptimizeCancelled:
            raise
        except Exception as exc:
            report.status = "failed"
            report.reason = f"trimesh optimization failed: {exc}"
            _fail_safe_copy(src, out_dir, out_name, report)
            return report
        report.engine = "trimesh"
        report.warnings.extend(result.get("warnings", []))

    _downscale_textures(src, out_dir, preset, report)
    failures, diff = _verify_trimesh_output(
        src, out_model, target, before_bbox, preset
    )
    if diff is not None and diff > VISUAL_DIFF_FLAG:
        report.check_visually = True
        report.warnings.append(
            f"silhouette changed in {diff:.0%} of the preview pixels — "
            "check the model visually before using it"
        )
    if failures:
        report.status = "failed"
        report.reason = "; ".join(failures)
        report.warnings.extend(failures)
        _fail_safe_copy(src, out_dir, out_name, report)
        return report

    after = _measure_output(out_model, report)
    report.status = "optimized"
    report.output = out_model
    report.triangles_after = after["triangles"]
    report.max_texture_px_after = after["max_texture_px"]
    report.texture_bytes_after = after["texture_bytes"]
    report.size_after = out_model.stat().st_size if out_model.is_file() else 0
    return report


def _optimize_with_blender(
    src: Path,
    out_dir: Path,
    out_name: str,
    preset: OptimizePreset,
    before: dict,
    report: AssetReport,
    cancel_event=None,
) -> AssetReport:
    """The Blender engine branch of :func:`optimize_asset`."""
    from .blend import blender_optimize, unavailable_reason

    out_model = out_dir / out_name
    result = blender_optimize(
        src,
        out_model,
        keep_ratio=preset.keep_ratio,
        cap=preset.per_asset_tri_cap,
        max_texture_px=preset.max_texture_px,
        source_scale=before["scale_factor"],
        # One floor for both engines: the script must not decimate a
        # mesh Python would have left alone (FBX triangles are only
        # known inside Blender, so the script enforces it too).
        min_triangles=MIN_DECIMATE_TRIANGLES,
        cancel_event=cancel_event,
        snapshots=True,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise OptimizeCancelled()
    if result is None:
        report.status = "failed"
        report.reason = unavailable_reason() or "Blender optimization failed"
        _fail_safe_copy(src, out_dir, out_name, report)
        return report
    if result.get("status") == "skipped":
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.status = "skipped"
        report.reason = result.get("reason", "skipped by Blender")
        report.output = copied_model
        report.triangles_after = result.get("triangles_before")
        report.size_after = report.size_before
        report.texture_bytes_after = before["texture_bytes"]
        report.max_texture_px_after = before["max_texture_px"]
        return report
    if result.get("status") == "failed" or result.get("error"):
        report.status = "failed"
        report.reason = result.get("error") or result.get("reason") or "Blender failed"
        _fail_safe_copy(src, out_dir, out_name, report)
        return report

    report.engine = "blender"
    report.triangles_before = result.get("triangles_before")
    report.triangles_after = result.get("triangles_after")
    report.target_triangles = result.get("target_triangles")
    report.scale_fixed = bool(result.get("scale_fixed"))
    report.warnings.extend(result.get("warnings", []))
    if result.get("images_scaled"):
        report.warnings.append(
            "packed textures scaled inside the file: "
            + ", ".join(result["images_scaled"])
        )
    # Packed-texture bytes (inside a .blend) are measured by the
    # script; neighbouring files are measured below.
    packed_before = result.get("texture_bytes_before") or 0
    packed_after = result.get("texture_bytes_after") or 0
    report.texture_bytes_before = before["texture_bytes"] + packed_before

    if not result.get("decimated") and not result.get("scale_fixed"):
        # The script found nothing to do: keep the original bytes.
        # (The copied file still holds the ORIGINAL packed textures —
        # the script only scaled them in memory — so "after" uses the
        # packed *before* figure, not the scaled one.)
        copied_model, _ = _copy_original(src, out_dir, out_name)
        report.output = copied_model
        report.engine = "copy"
        _downscale_textures(src, out_dir, preset, report)
        after = _measure_output(copied_model, report)
        report.triangles_after = after["triangles"]
        report.max_texture_px_after = after["max_texture_px"]
        report.texture_bytes_after = after["texture_bytes"] + packed_before
        report.size_after = (
            copied_model.stat().st_size if copied_model.is_file() else 0
        )
        report.status = (
            "optimized" if report.texture_bytes_after < report.texture_bytes_before
            else "unchanged"
        )
        report.reason = (
            "textures downscaled" if report.status == "optimized"
            else "already within budget"
        )
        return report

    _downscale_textures(src, out_dir, preset, report)
    failures = _verify_blender_output(src, out_model, result, preset)
    diff = result.get("thumbnail_diff")
    if diff is not None and diff > VISUAL_DIFF_FLAG:
        report.check_visually = True
        report.warnings.append(
            f"silhouette changed in {diff:.0%} of the preview pixels — "
            "check the model visually before using it"
        )
    if failures:
        report.status = "failed"
        report.reason = "; ".join(failures)
        report.warnings.extend(failures)
        _fail_safe_copy(src, out_dir, out_name, report)
        return report

    after = _measure_output(out_model, report)
    report.status = "optimized"
    report.output = out_model
    if report.triangles_after is None:
        report.triangles_after = after["triangles"]
    report.max_texture_px_after = after["max_texture_px"]
    report.texture_bytes_after = after["texture_bytes"] + packed_after
    report.size_after = out_model.stat().st_size if out_model.is_file() else 0
    return report


# ------------------------------------------------------- whole collection

def optimize_collection(
    model_paths,
    out_dir: Path,
    world: str,
    preset: OptimizePreset,
    meta_by_path: dict | None = None,
    favorites=None,
    engine: str = "auto",
    cancel_event=None,
):
    """Optimize a collection, yielding one :class:`AssetReport` per asset.

    The generator writes ``optimization_report.json``, ``manifest.json``
    and (when metadata was given) ``CREDITS.md`` into ``out_dir`` when
    it finishes — or when it is cancelled or closed early, with the
    assets completed so far. A failed asset never blocks the rest.
    Optimized copies are NOT added to the library index (they live in
    the export folder; indexing them would double-count world budgets).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_by_path = meta_by_path or {}
    favorites = set(favorites or [])
    used_names: dict = {}
    reports: list[AssetReport] = []
    try:
        for src in model_paths:
            if cancel_event is not None and cancel_event.is_set():
                raise OptimizeCancelled()
            src = Path(src)
            out_name = _unique_out_name(src, used_names)
            try:
                rep = optimize_asset(
                    src,
                    out_dir,
                    preset,
                    favorite=str(src) in favorites,
                    engine=engine,
                    out_name=out_name,
                    cancel_event=cancel_event,
                )
            except OptimizeCancelled:
                raise
            except Exception as exc:  # one bad asset never kills the run
                rep = AssetReport(source=src, status="failed",
                                  reason=f"unexpected error: {exc}")
                try:
                    _fail_safe_copy(src, out_dir, out_name, rep)
                except Exception:
                    rep.output = None
            reports.append(rep)
            yield rep
    finally:
        summary = OptimizeReport(
            world=world, preset=preset, out_dir=out_dir, assets=reports
        )
        _write_outputs(summary, meta_by_path)


def _write_outputs(summary: OptimizeReport, meta_by_path: dict) -> None:
    """optimization_report.json + manifest.json + CREDITS.md."""
    out_dir = summary.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "optimization_report.json").write_text(
        json.dumps(summary.to_dict(), indent=2), encoding="utf-8"
    )
    manifest = {"world": summary.world, "preset": summary.preset.name, "assets": []}
    for rep in summary.assets:
        entry: dict = {
            "file": rep.output.name if rep.output else rep.source.name,
            "source_path": str(rep.source),
            "optimized_from": str(rep.source),
            "status": rep.status,
            "reason": rep.reason,
            "triangles_before": rep.triangles_before,
            "triangles_after": rep.triangles_after,
            "textures": [t.name for t in find_textures_for(rep.source)],
        }
        m = meta_by_path.get(str(rep.source), {}) or {}
        for key in ("source", "author", "url", "license", "tags"):
            entry[key] = m.get(key, "")
        manifest["assets"].append(entry)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    if meta_by_path:
        optimized_paths = [
            rep.output for rep in summary.assets if rep.output is not None
        ]
        remapped_meta = {
            str(rep.output): meta_by_path.get(str(rep.source), {})
            for rep in summary.assets
            if rep.output is not None
        }
        write_credits(optimized_paths, remapped_meta, out_dir / "CREDITS.md")
