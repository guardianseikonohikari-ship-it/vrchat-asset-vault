import json
import tarfile

from vrchat_asset_vault.exporter import (
    export_collection,
    export_unitypackage,
    fbx_version,
    write_credits,
)

from conftest import write_fake_fbx

META = {
    "source": "Poly Haven",
    "author": "Ulan Cabanilla",
    "url": "https://polyhaven.com/a/wooden_bookshelf_worn",
    "license": "CC0",
    "tags": "furniture, wood",
}


def test_folder_export_enriches_manifest_and_writes_credits(library, tmp_path):
    out = tmp_path / "Export_World"
    result = export_collection(
        [library / "cube.obj"],
        out,
        "World",
        meta_by_path={str(library / "cube.obj"): META},
    )
    assert result["assets"] == 1
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["assets"][0]
    assert entry["source"] == "Poly Haven"
    assert entry["author"] == "Ulan Cabanilla"
    assert entry["license"] == "CC0"
    assert entry["textures"] == ["cube_diffuse.png", "cube_specular.jpg"]
    assert (out / "cube_diffuse.png").exists()
    assert (out / "cube.mtl").exists()
    credits = (out / "CREDITS.md").read_text(encoding="utf-8")
    assert "Poly Haven" in credits
    assert "Ulan Cabanilla" in credits
    assert "CC0" in credits
    assert "https://polyhaven.com/a/wooden_bookshelf_worn" in credits


def test_folder_export_without_meta_writes_no_credits(library, tmp_path):
    out = tmp_path / "Export_World"
    export_collection([library / "book.obj"], out, "World")
    assert not (out / "CREDITS.md").exists()


def test_credits_flags_unknown_origin(tmp_path):
    model = tmp_path / "mystery.obj"
    model.write_text("v 0 0 0\n", encoding="utf-8")
    out = tmp_path / "CREDITS.md"
    write_credits([model], {}, out)
    assert "unknown" in out.read_text(encoding="utf-8").lower()


def test_unitypackage_contents(library, tmp_path):
    out = tmp_path / "World.unitypackage"
    result = export_unitypackage(
        [library / "cube.obj", library / "book.obj"],
        out,
        "World",
        meta_by_path={str(library / "cube.obj"): META},
    )
    assert result["assets"] == 2
    assert out.exists()
    with tarfile.open(out, "r:gz") as tar:
        names = tar.getnames()
    # Model + its .meta, textures + their .meta, shared dedupe, credits.
    assert "Assets/cube.obj" in names
    assert "Assets/cube.obj.meta" in names
    assert "Assets/cube.mtl" in names
    assert "Assets/cube_diffuse.png" in names
    assert "Assets/book.obj" in names
    assert "Assets/CREDITS.md" in names
    assert "Assets/CREDITS.md.meta" in names
    assert names.count("Assets/cube_diffuse.png") == 1
    with tarfile.open(out, "r:gz") as tar:
        meta_text = tar.extractfile("Assets/cube.obj.meta").read().decode("utf-8")
    guid = [l for l in meta_text.splitlines() if l.startswith("guid:")][0].split()[1]
    assert len(guid) == 32 and all(c in "0123456789abcdef" for c in guid)
    # Same content -> same GUID across exports (stable, not random).
    out2 = tmp_path / "World2.unitypackage"
    export_unitypackage([library / "cube.obj"], out2, "World")
    with tarfile.open(out2, "r:gz") as tar:
        meta2 = tar.extractfile("Assets/cube.obj.meta").read().decode("utf-8")
    assert meta2 == meta_text


def test_old_fbx_version_warns(tmp_path):
    old = tmp_path / "old.fbx"
    write_fake_fbx(old, 6100)
    assert fbx_version(old) == 6100
    result = export_collection([old], tmp_path / "out", "World")
    assert any("FBX version 6.1" in w for w in result["warnings"])
    new = tmp_path / "new.fbx"
    write_fake_fbx(new, 7400)
    result = export_collection([new], tmp_path / "out2", "World")
    assert not any("FBX version" in w for w in result["warnings"])


def test_blend_export_warns_but_copies(tmp_path):
    blend = tmp_path / "model.blend"
    blend.write_bytes(b"BLENDER")
    result = export_collection([blend], tmp_path / "out", "World")
    assert (tmp_path / "out" / "model.blend").exists()
    assert any(".blend" in w for w in result["warnings"])


def test_fbx_scale_factor_warns_on_export(tmp_path):
    from conftest import write_fbx_with_scale

    small = tmp_path / "blender.fbx"
    write_fbx_with_scale(small, 0.01)
    result = export_collection([small], tmp_path / "out", "World")
    assert any("0.01" in w and "100x" in w for w in result["warnings"])
    ok = tmp_path / "unity.fbx"
    write_fbx_with_scale(ok, 1.0)
    result = export_collection([ok], tmp_path / "out2", "World")
    assert not any("UnitScaleFactor" in w for w in result["warnings"])
