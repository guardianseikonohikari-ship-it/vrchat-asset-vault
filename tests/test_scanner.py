from pathlib import Path

import pytest

from vrchat_asset_vault.scanner import analyze_mesh, scan
from vrchat_asset_vault.textures import probe_image_size, texture_stats_for

from conftest import write_cube_obj, write_fake_fbx, write_image


def test_obj_triangles_and_materials(tmp_path):
    path = tmp_path / "cube.obj"
    write_cube_obj(path, materials=2)
    info = analyze_mesh(path)
    assert info.triangles == 12  # 6 quads triangulated
    assert info.materials == 2
    assert info.warnings == []


def test_obj_without_materials_counts_zero(tmp_path):
    path = tmp_path / "plain.obj"
    write_cube_obj(path, materials=0)
    info = analyze_mesh(path)
    assert info.triangles == 12
    assert info.materials == 0


def test_glb_triangles_and_materials(library):
    info = analyze_mesh(library / "box.glb")
    assert info.triangles == 12
    assert info.materials == 0  # a plain trimesh box carries no material
    assert info.warnings == []


def test_glb_with_material_counts_it(tmp_path):
    from conftest import write_glb_box

    path = tmp_path / "box_mat.glb"
    write_glb_box(path, with_material=True)
    info = analyze_mesh(path)
    assert info.triangles == 12
    assert info.materials == 1


def test_broken_fbx_warns_instead_of_crashing(library):
    info = analyze_mesh(library / "broken.fbx")
    assert info.triangles is None
    assert any("could not parse" in w for w in info.warnings)


def test_blend_reports_planned_not_guessed(tmp_path, monkeypatch):
    # A fake .blend never gets invented stats: without Blender the
    # warning says Blender is missing; the triangles stay unknown.
    from vrchat_asset_vault import blend

    monkeypatch.setattr(blend, "find_blender", lambda: None)
    path = tmp_path / "model.blend"
    path.write_bytes(b"BLENDER")
    info = analyze_mesh(path)
    assert info.triangles is None
    assert any("Blender not found" in w for w in info.warnings)


def test_scan_fills_texture_and_material_fields(library):
    found = {a.path.name: a for a in scan(library)}
    cube = found["cube.obj"]
    assert cube.triangles == 12
    assert cube.materials == 2
    assert cube.texture_count == 2
    assert cube.max_texture_px == 2048  # 2048x1024 diffuse is the biggest
    assert cube.texture_bytes > 0
    book = found["book.obj"]
    assert book.materials == 1
    assert book.texture_count == 1
    assert book.max_texture_px == 64


def test_probe_png_jpeg_bmp_tga(tmp_path):
    cases = [
        ("a.png", 300, 200),
        ("b.jpg", 512, 512),
        ("c.bmp", 64, 48),
        ("d.tga", 128, 256),
    ]
    for name, w, h in cases:
        path = tmp_path / name
        write_image(path, w, h)
        assert probe_image_size(path) == (w, h)


def test_probe_unknown_returns_none(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"not a png at all")
    assert probe_image_size(path) is None
    missing = tmp_path / "nope.jpg"
    assert probe_image_size(missing) is None


def test_texture_stats_no_textures(tmp_path):
    model = tmp_path / "lonely.obj"
    write_cube_obj(model, materials=1)
    stats = texture_stats_for(model)
    assert stats == {"count": 0, "max_px": None, "total_bytes": 0}


def test_fake_fbx_version_read(tmp_path):
    from vrchat_asset_vault.exporter import fbx_version, is_binary_fbx

    path = tmp_path / "v74.fbx"
    write_fake_fbx(path, 7400)
    assert is_binary_fbx(path) is True
    assert fbx_version(path) == 7400
    text = tmp_path / "text.fbx"
    text.write_text("Kaydara FBX Binary", encoding="utf-8")
    assert fbx_version(text) is None


def test_fbx_unit_scale_factor_blender_default(tmp_path):
    from conftest import write_fbx_with_scale
    from vrchat_asset_vault.scanner import fbx_unit_scale_factor

    path = tmp_path / "model.fbx"
    write_fbx_with_scale(path, 0.01)
    assert fbx_unit_scale_factor(path) == 0.01


def test_fbx_unit_scale_factor_one(tmp_path):
    from conftest import write_fbx_with_scale
    from vrchat_asset_vault.scanner import fbx_unit_scale_factor

    path = tmp_path / "model.fbx"
    write_fbx_with_scale(path, 1.0)
    assert fbx_unit_scale_factor(path) == 1.0


def test_fbx_unit_scale_factor_missing_means_none(tmp_path):
    from vrchat_asset_vault.scanner import fbx_unit_scale_factor

    bare = tmp_path / "bare.fbx"
    write_fake_fbx(bare, 7400)  # header only, no GlobalSettings
    assert fbx_unit_scale_factor(bare) is None
    text = tmp_path / "text.fbx"
    text.write_text("not an fbx", encoding="utf-8")
    assert fbx_unit_scale_factor(text) is None
    assert fbx_unit_scale_factor(tmp_path / "nope.fbx") is None


def test_fbx_original_scale_is_not_matched(tmp_path):
    from conftest import write_fbx_with_scale
    from vrchat_asset_vault.scanner import fbx_unit_scale_factor

    # "OriginalUnitScaleFactor" contains the name as a substring —
    # the parser must not mistake it for the real property.
    path = tmp_path / "model.fbx"
    write_fbx_with_scale(path, 1.0, name="OriginalUnitScaleFactor")
    assert fbx_unit_scale_factor(path) is None


def test_analyze_mesh_reports_scale_even_when_unparsable(tmp_path):
    from conftest import write_fbx_with_scale

    path = tmp_path / "model.fbx"
    write_fbx_with_scale(path, 0.01)
    info = analyze_mesh(path)
    # No geometry in the minimal fixture, but the scale is real data.
    assert info.scale_factor == 0.01


def test_scan_blend_uses_blender_stats(tmp_path):
    """End-to-end: a real .blend scans to real triangles/materials."""
    from test_blend import _make_test_blend
    from vrchat_asset_vault.blend import find_blender

    blender = find_blender()
    if blender is None:
        pytest.skip("no Blender on this machine — .blend scan test skipped")
    lib = tmp_path / "lib"
    lib.mkdir()
    _make_test_blend(blender, lib / "cube.blend")
    found = {a.path.name: a for a in scan(lib)}
    cube = found["cube.blend"]
    assert cube.triangles == 12
    assert cube.materials == 1
    assert cube.texture_count == 1
    assert cube.max_texture_px == 64
    assert cube.texture_bytes > 0
    assert cube.warnings == []


def test_scan_fills_scale_factor(tmp_path):
    from conftest import write_cube_obj, write_fbx_with_scale

    lib = tmp_path / "lib"
    lib.mkdir()
    write_cube_obj(lib / "cube.obj", materials=1)
    write_fbx_with_scale(lib / "shelf.fbx", 0.01)
    found = {a.path.name: a for a in scan(lib)}
    assert found["shelf.fbx"].scale_factor == 0.01
    assert found["cube.obj"].scale_factor is None
