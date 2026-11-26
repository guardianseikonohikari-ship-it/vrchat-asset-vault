import struct

import pytest

from vrchat_asset_vault.preview import mesh_geometry, render_png, thumbnail_for

from conftest import write_cube_obj


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_render_cube_is_valid_png(tmp_path):
    path = tmp_path / "cube.obj"
    write_cube_obj(path, materials=1)
    verts, faces = mesh_geometry(path)
    png = render_png(verts, faces, size=192)
    assert _png_size(png) == (192, 192)
    # Not a blank image: the mesh must cover a good share of pixels.
    assert len(png) > 1000


def test_render_is_deterministic(tmp_path):
    path = tmp_path / "cube.obj"
    write_cube_obj(path, materials=1)
    verts, faces = mesh_geometry(path)
    assert render_png(verts, faces) == render_png(verts, faces)


def test_render_empty_raises():
    with pytest.raises(ValueError):
        render_png([], [])


def test_mesh_geometry_obj_and_unknown(tmp_path):
    cube = tmp_path / "cube.obj"
    write_cube_obj(cube, materials=1)
    verts, faces = mesh_geometry(cube)
    assert len(verts) == 8
    assert len(faces) == 12
    blend = tmp_path / "model.blend"
    blend.write_bytes(b"BLENDER")
    assert mesh_geometry(blend) is None


def test_thumbnail_caches_by_hash(tmp_path):
    model = tmp_path / "cube.obj"
    write_cube_obj(model, materials=1)
    cache = tmp_path / "thumbs"
    first = thumbnail_for(model, cache)
    assert first is not None and first.exists()
    assert _png_size(first.read_bytes()) == (192, 192)
    mtime = first.stat().st_mtime_ns
    second = thumbnail_for(model, cache)
    assert second == first
    assert second.stat().st_mtime_ns == mtime  # not re-rendered


def test_thumbnail_none_for_blend(tmp_path):
    model = tmp_path / "model.blend"
    model.write_bytes(b"BLENDER")
    assert thumbnail_for(model, tmp_path / "thumbs") is None
