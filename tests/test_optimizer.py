"""Tests for the one-click Quest optimizer (optimizer.py + textures.py).

Tiers, like test_blend.py:
1. Always-run: presets, texture downscale, trimesh fallback, the
   verification gate, reports, cancel, CLI. These need trimesh +
   Pillow (the [mesh] and [optimize] extras) and skip cleanly
   without them.
2. Blender path: tests/test_blend_optimize.py (real Blender here).

The originals-untouched rule is tested by hash, not by trust.
"""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from vrchat_asset_vault.budget import (
    MIN_DECIMATE_TRIANGLES,
    PRESETS,
    custom_preset,
    preset_for,
)
from vrchat_asset_vault.optimizer import (
    OptimizeCancelled,
    OptimizeReport,
    _verify_trimesh_output,
    optimize_asset,
    optimize_collection,
)
from vrchat_asset_vault.preview import png_diff_fraction, render_png
from vrchat_asset_vault.scanner import sha256_of
from vrchat_asset_vault.textures import downscale_texture

from conftest import (
    write_image,
    write_subdivided_sphere_glb,
    write_subdivided_sphere_obj,
)

pytest.importorskip("trimesh", reason="optimizer tests need trimesh")
pytest.importorskip("PIL", reason="optimizer tests need Pillow")


def _hashes(paths) -> dict:
    return {str(p): sha256_of(p) for p in paths}


# ---------------------------------------------------------------- presets

def test_preset_targets_and_caps():
    balanced = PRESETS["Balanced"]
    assert balanced.target_triangles(300_000) == 50_000  # cap wins
    assert balanced.target_triangles(320) == 160
    assert PRESETS["Gentle"].target_triangles(320) == 240
    assert PRESETS["Aggressive"].target_triangles(320) == 80
    # At/below the floor the mesh is left alone, never "optimized"
    # from 12 triangles down to 6.
    assert balanced.target_triangles(12) is None
    assert balanced.target_triangles(MIN_DECIMATE_TRIANGLES) is None
    assert balanced.target_triangles(None) is None
    assert preset_for("Nope").name == "Balanced"  # unknown → default


def test_custom_preset_validation():
    assert custom_preset(0.5, 1024, 50_000).name == "Custom"
    with pytest.raises(ValueError):
        custom_preset(0.95, 1024, 50_000)  # ratio out of 10–90%
    with pytest.raises(ValueError):
        custom_preset(0.5, 999, 50_000)  # not a supported texture size
    with pytest.raises(ValueError):
        custom_preset(0.5, 1024, 0)


# ---------------------------------------------------------------- textures

def test_downscale_texture_shrinks_2048_to_1024(tmp_path):
    src = tmp_path / "big.png"
    write_image(src, 2048, 1024)
    dst = tmp_path / "out.png"
    result = downscale_texture(src, dst, 1024)
    assert result["status"] == "downscaled"
    assert result["size_before"] == (2048, 1024)
    assert result["size_after"] == (1024, 512)  # aspect kept
    assert result["bytes_after"] < result["bytes_before"]
    assert dst.is_file()


def test_downscale_texture_keeps_alpha(tmp_path):
    from PIL import Image

    src = tmp_path / "alpha.png"
    Image.new("RGBA", (2048, 2048), color=(200, 100, 50, 128)).save(src, "PNG")
    dst = tmp_path / "out.png"
    result = downscale_texture(src, dst, 1024)
    assert result["status"] == "downscaled"
    assert result["size_after"] == (1024, 1024)
    with Image.open(dst) as img:
        assert img.mode == "RGBA"


def test_downscale_texture_unchanged_when_small(tmp_path):
    src = tmp_path / "small.png"
    write_image(src, 512, 512)
    dst = tmp_path / "out.png"
    result = downscale_texture(src, dst, 1024)
    assert result["status"] == "unchanged"
    assert result["size_after"] == (512, 512)
    assert dst.read_bytes() == src.read_bytes()  # byte-identical copy


def test_downscale_texture_copies_hdr_with_warning(tmp_path):
    src = tmp_path / "sky.hdr"
    src.write_bytes(b"fake hdr data")
    dst = tmp_path / "out.hdr"
    result = downscale_texture(src, dst, 1024)
    assert result["status"] == "copied"
    assert dst.read_bytes() == b"fake hdr data"
    assert result["warning"] and "cannot be downscaled" in result["warning"]


def test_downscale_texture_in_place_same_file(tmp_path):
    """src == dst (the optimizer scales where the file sits) works."""
    src = tmp_path / "big.png"
    write_image(src, 2048, 1024)
    result = downscale_texture(src, src, 1024)
    assert result["status"] == "downscaled"
    assert result["size_after"] == (1024, 512)


def test_downscale_texture_missing_file(tmp_path):
    result = downscale_texture(tmp_path / "nope.png", tmp_path / "out.png", 1024)
    assert result["status"] == "failed"
    assert result["warning"]


# ---------------------------------------------------------------- trimesh engine

def test_optimize_obj_decimates_50_percent(tmp_path):
    src = tmp_path / "sphere.obj"
    faces = write_subdivided_sphere_obj(src, subdivisions=2)
    assert faces == 320
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"], engine="trimesh")
    assert rep.status == "optimized", rep
    assert rep.engine == "trimesh"
    assert rep.triangles_before == 320
    assert rep.triangles_after == 160, rep  # within ±5% of target
    assert rep.output is not None and rep.output.is_file()
    assert src.read_bytes()  # source still there (hash check is separate)


def test_optimize_obj_preserves_materials_and_uv(tmp_path):
    import numpy as np
    import trimesh
    from trimesh.visual.material import PBRMaterial

    mesh = trimesh.creation.icosphere(subdivisions=2)
    mesh.visual.material = PBRMaterial(
        name="sphere_mat", baseColorFactor=[1.0, 0.0, 0.0, 1.0]
    )
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.column_stack([mesh.vertices[:, 0], mesh.vertices[:, 1]]),
        material=mesh.visual.material,
    )
    src = tmp_path / "sphere.obj"
    trimesh.Scene(mesh).export(src)
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"], engine="trimesh")
    assert rep.status == "optimized", rep
    assert rep.triangles_after == 160
    # The optimized OBJ still has a material and UVs.
    from vrchat_asset_vault.scanner import analyze_mesh

    info = analyze_mesh(rep.output)
    assert info.materials == 1, info
    from vrchat_asset_vault.preview import mesh_geometry

    assert mesh_geometry(rep.output) is not None
    obj_text = rep.output.read_text(encoding="utf-8")
    assert "vt " in obj_text  # UV lines survived
    assert "usemtl " in obj_text


def test_optimize_glb_decimates_and_keeps_material(tmp_path):
    src = tmp_path / "sphere.glb"
    faces = write_subdivided_sphere_glb(src, subdivisions=2, with_material=True)
    assert faces == 320
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"], engine="trimesh")
    assert rep.status == "optimized", rep
    assert rep.triangles_after == 160
    from vrchat_asset_vault.scanner import analyze_mesh

    info = analyze_mesh(rep.output)
    assert info.triangles == 160
    assert info.materials == 1, info


def test_optimize_already_within_budget_copies_unchanged(library, tmp_path):
    book = library / "book.obj"  # 12 tris, 64px texture: nothing to do
    rep = optimize_asset(book, tmp_path / "out", PRESETS["Balanced"], engine="trimesh")
    assert rep.status == "unchanged", rep
    assert rep.reason == "already within budget"
    assert rep.output.read_bytes() == book.read_bytes()


def test_optimize_texture_only_downscales_mesh_untouched(library, tmp_path):
    """A tiny mesh with a big texture: the mesh is copied, the texture shrinks."""
    small = tmp_path / "lib"
    small.mkdir()
    (small / "prop.obj").write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3\nf 1 3 4\n",
        encoding="utf-8",
    )
    write_image(small / "prop_diffuse.png", 2048, 1024)
    src = small / "prop.obj"
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"], engine="trimesh")
    assert rep.status == "optimized", rep
    assert rep.triangles_after == 2  # mesh copied, not decimated
    assert rep.max_texture_px_after == 1024
    assert rep.texture_bytes_after < rep.texture_bytes_before


def test_optimize_broken_file_fails_but_others_complete(library, tmp_path):
    out = tmp_path / "out"
    reports = list(
        optimize_collection(
            [library / "broken.fbx", library / "book.obj"],
            out, "World", PRESETS["Balanced"], engine="trimesh",
        )
    )
    assert len(reports) == 2
    broken, book = reports
    assert broken.status in ("skipped", "failed"), broken
    assert book.status == "unchanged", book
    # The report JSON is still written for the whole run.
    assert (out / "optimization_report.json").is_file()


def test_originals_untouched_by_hash(library, tmp_path):
    files = [library / "cube.obj", library / "book.obj", library / "box.glb"]
    before = _hashes(files)
    list(
        optimize_collection(
            files, tmp_path / "out", "World", PRESETS["Balanced"], engine="trimesh"
        )
    )
    assert _hashes(files) == before


def test_report_json_schema_and_totals_reconcile(library, tmp_path):
    out = tmp_path / "out"
    list(
        optimize_collection(
            [library / "cube.obj", library / "book.obj", library / "box.glb"],
            out, "World", PRESETS["Balanced"], engine="trimesh",
        )
    )
    data = json.loads((out / "optimization_report.json").read_text(encoding="utf-8"))
    assert data["world"] == "World"
    assert data["preset"]["name"] == "Balanced"
    assert len(data["assets"]) == 3
    for entry in data["assets"]:
        assert set(entry) >= {
            "source", "output", "status", "triangles_before",
            "triangles_after", "texture_bytes_before", "texture_bytes_after",
            "warnings",
        }
    # The artifact-totals rule: sums of assets == reported totals.
    totals = data["totals"]
    assert totals["triangles_before"] == sum(
        a["triangles_before"] or 0 for a in data["assets"]
    )
    assert totals["triangles_after"] == sum(
        a["triangles_after"] or 0 for a in data["assets"]
    )
    assert totals["texture_bytes_before"] == sum(
        a["texture_bytes_before"] for a in data["assets"]
    )


def test_manifest_and_credits_written(tmp_path, library):
    out = tmp_path / "out"
    meta = {
        str(library / "cube.obj"): {
            "source": "Poly Haven",
            "author": "Ulan Cabanilla",
            "url": "https://polyhaven.com/a/wooden_bookshelf_worn",
            "license": "CC0",
            "tags": "furniture, wood",
        }
    }
    list(
        optimize_collection(
            [library / "cube.obj"], out, "World", PRESETS["Balanced"],
            meta_by_path=meta, engine="trimesh",
        )
    )
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["assets"][0]
    assert entry["optimized_from"] == str(library / "cube.obj")
    assert entry["source"] == "Poly Haven"
    assert entry["license"] == "CC0"
    credits = (out / "CREDITS.md").read_text(encoding="utf-8")
    assert "Poly Haven" in credits
    assert "CC0" in credits


def test_duplicate_filenames_deduped(tmp_path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    write_subdivided_sphere_obj(a_dir / "prop.obj", subdivisions=2)
    write_subdivided_sphere_obj(b_dir / "prop.obj", subdivisions=2)
    out = tmp_path / "out"
    reports = list(
        optimize_collection(
            [a_dir / "prop.obj", b_dir / "prop.obj"],
            out, "World", PRESETS["Balanced"], engine="trimesh",
        )
    )
    assert len({r.output.name for r in reports}) == 2
    assert all(r.output.is_file() for r in reports)
    assert all(r.status == "optimized" for r in reports)


def test_cancel_after_first_asset(tmp_path, library):
    import threading

    cancel = threading.Event()
    gen = optimize_collection(
        [library / "cube.obj", library / "book.obj", library / "box.glb"],
        tmp_path / "out", "World", PRESETS["Balanced"],
        engine="trimesh", cancel_event=cancel,
    )
    first = next(gen)
    assert first.status in ("optimized", "unchanged")
    cancel.set()
    with pytest.raises(OptimizeCancelled):
        list(gen)
    # The partial report is still written, with exactly one asset.
    data = json.loads(
        (tmp_path / "out" / "optimization_report.json").read_text(encoding="utf-8")
    )
    assert len(data["assets"]) == 1


def test_cancel_before_start_writes_empty_report(tmp_path, library):
    import threading

    cancel = threading.Event()
    cancel.set()
    gen = optimize_collection(
        [library / "cube.obj"], tmp_path / "out", "World",
        PRESETS["Balanced"], engine="trimesh", cancel_event=cancel,
    )
    with pytest.raises(OptimizeCancelled):
        list(gen)
    data = json.loads(
        (tmp_path / "out" / "optimization_report.json").read_text(encoding="utf-8")
    )
    assert data["assets"] == []


def test_favorite_aggressive_skips(tmp_path):
    src = tmp_path / "sphere.obj"
    write_subdivided_sphere_obj(src, subdivisions=2)
    rep = optimize_asset(
        src, tmp_path / "out", PRESETS["Aggressive"],
        favorite=True, engine="trimesh",
    )
    assert rep.status == "skipped", rep
    assert "favorite" in rep.reason
    assert rep.triangles_after == 320  # untouched copy


def test_favorite_balanced_warns_but_runs(tmp_path):
    src = tmp_path / "sphere.obj"
    write_subdivided_sphere_obj(src, subdivisions=2)
    rep = optimize_asset(
        src, tmp_path / "out", PRESETS["Balanced"],
        favorite=True, engine="trimesh",
    )
    assert rep.status == "optimized", rep
    assert rep.check_visually is True
    assert any("favorite" in w for w in rep.warnings)


def test_fbx_without_blender_skips_with_reason(tmp_path, monkeypatch):
    from vrchat_asset_vault import blend

    monkeypatch.setattr(blend, "find_blender", lambda: None)
    monkeypatch.setattr(blend, "_dev_tools_blender", lambda: None)
    from conftest import write_fbx_with_scale

    src = tmp_path / "shelf.fbx"
    write_fbx_with_scale(src, 0.01)
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"])
    assert rep.status == "skipped", rep
    assert "Blender" in rep.reason
    assert rep.output.is_file()  # original copied, world still builds


def test_no_blender_obj_glb_still_optimize(tmp_path, monkeypatch, library):
    from vrchat_asset_vault import blend

    monkeypatch.setattr(blend, "find_blender", lambda: None)
    monkeypatch.setattr(blend, "_dev_tools_blender", lambda: None)
    src = tmp_path / "sphere.obj"
    write_subdivided_sphere_obj(src, subdivisions=2)
    rep = optimize_asset(src, tmp_path / "out", PRESETS["Balanced"])
    assert rep.status == "optimized", rep
    assert rep.engine == "trimesh"


# ---------------------------------------------------------------- verify gate

def test_verify_gate_catches_overshoot(tmp_path):
    """The gate itself: an unmodified 320-face sphere against a target of 3 fails."""
    src = tmp_path / "sphere.obj"
    write_subdivided_sphere_obj(src, subdivisions=2)
    from vrchat_asset_vault.preview import mesh_geometry

    geom = mesh_geometry(src)
    bbox = None
    if geom is not None:
        from vrchat_asset_vault.optimizer import _bbox_of

        bbox = _bbox_of(geom[0])
    failures, _diff = _verify_trimesh_output(
        src, src, target=3, before_bbox=bbox, preset=PRESETS["Balanced"]
    )
    assert any("overshot" in f for f in failures)


def test_thumbnail_diff_zero_for_identical_and_high_for_different(tmp_path):
    a = tmp_path / "a.obj"
    b = tmp_path / "b.obj"
    write_subdivided_sphere_obj(a, subdivisions=2)
    write_subdivided_sphere_obj(b, subdivisions=2)
    from vrchat_asset_vault.preview import mesh_geometry

    ga, gb = mesh_geometry(a), mesh_geometry(b)
    assert png_diff_fraction(render_png(*ga, size=96), render_png(*gb, size=96)) == 0.0
    # A flat quad vs a sphere: very different silhouettes.
    quad = tmp_path / "quad.obj"
    quad.write_text(
        "v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\nf 1 2 3\nf 1 3 4\n",
        encoding="utf-8",
    )
    gq = mesh_geometry(quad)
    diff = png_diff_fraction(render_png(*ga, size=96), render_png(*gq, size=96))
    assert diff is not None and diff > 0.25


def test_verify_gate_catches_nan(tmp_path):
    import trimesh

    mesh = trimesh.creation.icosphere(subdivisions=1)
    verts = mesh.vertices.copy()
    verts[0] = [float("nan"), 0.0, 0.0]
    bad = trimesh.Trimesh(vertices=verts, faces=mesh.faces, process=False)
    src = tmp_path / "bad.obj"
    bad.export(src)
    failures, _diff = _verify_trimesh_output(
        src, src, target=None, before_bbox=None, preset=PRESETS["Balanced"]
    )
    assert any("NaN" in f for f in failures)


# ---------------------------------------------------------------- CLI

def _index_library(tmp_path, library, collection="World"):
    from vrchat_asset_vault.__main__ import main
    from vrchat_asset_vault.database import connect, update_asset_meta

    db = tmp_path / "vault.db"
    assert main(["scan", str(library), "--db", str(db)]) == 0
    conn = connect(db)
    for row in conn.execute("SELECT path FROM assets"):
        update_asset_meta(conn, row[0], collection=collection)
    conn.close()
    return db


def test_cli_optimize_end_to_end(tmp_path, library, capsys):
    from vrchat_asset_vault.__main__ import main

    db = _index_library(tmp_path, library)
    out = tmp_path / "Optimized_World"
    assert main(["optimize", str(db), "--collection", "World",
                 "--preset", "Balanced", "--out", str(out)]) == 0
    captured = capsys.readouterr().out
    assert "Optimizing" in captured
    assert "Triangles:" in captured
    assert (out / "optimization_report.json").is_file()
    assert (out / "manifest.json").is_file()
    data = json.loads((out / "optimization_report.json").read_text(encoding="utf-8"))
    assert data["totals"]["assets"] == 4  # cube, book, box.glb, broken.fbx


def test_cli_optimize_empty_collection(tmp_path, capsys):
    from vrchat_asset_vault.__main__ import main
    from vrchat_asset_vault.database import connect

    db = tmp_path / "vault.db"
    connect(db).close()
    assert main(["optimize", str(db), "--collection", "Nope",
                 "--out", str(tmp_path / "out")]) == 0
    assert "empty" in capsys.readouterr().out


def test_optimize_report_world_guard_flags_overrun(tmp_path):
    """A collection still over budget after optimizing says so plainly."""
    reports = []
    from vrchat_asset_vault.optimizer import AssetReport

    for i in range(3):
        reports.append(
            AssetReport(
                source=Path(f"/lib/big{i}.fbx"),
                status="optimized",
                triangles_before=200_000,
                triangles_after=100_000,
            )
        )
    summary = OptimizeReport("World", PRESETS["Balanced"], tmp_path / "out", reports)
    assert summary.totals["triangles_after"] == 300_000
    assert summary.totals["quest_triangles_ok"] is False
    assert any("Still over" in w for w in summary.world_warnings)
    assert any("big0.fbx" in w for w in summary.world_warnings)
