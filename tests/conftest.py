"""Shared fixtures: a tiny library with known triangle/material/texture stats."""
import struct
from pathlib import Path

import pytest


def write_cube_obj(path: Path, materials: int = 2) -> None:
    """A box: 8 verts, 6 quads = 12 triangles, split across N materials."""
    verts = [
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ]
    quads = [
        (1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2),
        (2, 6, 7, 3), (3, 7, 8, 4), (5, 1, 4, 8),
    ]
    lines = ["# test cube"]
    for v in verts:
        lines.append(f"v {v[0]} {v[1]} {v[2]}")
    for i, q in enumerate(quads):
        mat = f"mat_{i % materials}" if materials else None
        if mat:
            lines.append(f"usemtl {mat}")
        lines.append(f"f {q[0]} {q[1]} {q[2]} {q[3]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_image(path: Path, width: int, height: int) -> None:
    pytest.importorskip("PIL", reason="test image fixtures need Pillow")
    from PIL import Image

    fmt = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "bmp": "BMP", "tga": "TGA"}[
        path.suffix.lower().lstrip(".")
    ]
    Image.new("RGB", (width, height), color=(200, 100, 50)).save(path, fmt)


def write_glb_box(path: Path, with_material: bool = False) -> None:
    pytest.importorskip("trimesh", reason="test mesh fixtures need trimesh")
    import trimesh

    mesh = trimesh.creation.box(extents=[1, 1, 1])
    if with_material:
        from trimesh.visual.material import PBRMaterial

        mesh.visual.material = PBRMaterial(
            name="red_mat", baseColorFactor=[1.0, 0.0, 0.0, 1.0]
        )
    mesh.export(path)


def write_fake_fbx(path: Path, version: int) -> None:
    """Minimal binary FBX header: 21-byte magic + 2 marker bytes + version.

    Real layout (Blender FBX spec): bytes 0-20 magic "Kaydara FBX
    Binary  \\0", bytes 21-22 [0x1A, 0x00], bytes 23-26 uint32 LE
    version (7300 = 7.3, 7400 = 7.4). No scene data after the header.
    """
    path.write_bytes(
        b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", version)
    )


def write_fbx_with_scale(
    path: Path, scale: float, version: int = 7400, name: str = "UnitScaleFactor"
) -> None:
    """Minimal binary FBX with a GlobalSettings UnitScaleFactor.

    Builds real 32-bit node records with correct end offsets:
    GlobalSettings -> Properties70 -> P: "<name>", "double", "", "",
    <scale>. The parser is tested against the byte layout Blender
    actually writes, not against a hand-placed string.
    """
    def prop_str(s: str) -> bytes:
        b = s.encode("utf-8")
        return b"S" + struct.pack("<I", len(b)) + b

    def prop_double(v: float) -> bytes:
        return b"D" + struct.pack("<d", v)

    def prop_int(v: int) -> bytes:
        return b"I" + struct.pack("<i", v)

    def node(nm: str, props: list[bytes], children: list, start: int) -> bytes:
        name_b = nm.encode("utf-8")
        props_b = b"".join(props)
        header_len = 13 + len(name_b) + len(props_b)
        built = b""
        child_start = start + header_len
        for child_nm, child_props, grandkids in children:
            child_b = node(child_nm, child_props, grandkids, child_start)
            built += child_b
            child_start += len(child_b)
        inner = built + (b"\x00" * 13 if built else b"")
        total = header_len + len(inner)
        return (
            struct.pack("<III", start + total, len(props), len(props_b))
            + bytes([len(name_b)])
            + name_b
            + props_b
            + inner
        )

    p_node = (
        "P",
        [prop_str(name), prop_str("double"), prop_str(""), prop_str(""), prop_double(scale)],
        [],
    )
    props70 = ("Properties70", [], [p_node])
    settings = ("GlobalSettings", [prop_int(1000)], [props70])
    header = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", version)
    body = node(*settings, start=len(header))
    path.write_bytes(header + body + b"\x00" * 13)


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    """library/
      cube.obj (12 tris, 2 materials) + cube_diffuse.png 2048x1024
        + cube_specular.jpg 512x512 + cube.mtl (2 newmtl)
      book.obj (12 tris, 1 material) + book_cover.bmp 64x64
      box.glb (12 tris, trimesh box)
      broken.fbx (text, not a real FBX)
    """
    lib = tmp_path / "library"
    lib.mkdir()
    write_cube_obj(lib / "cube.obj", materials=2)
    (lib / "cube.mtl").write_text(
        "newmtl mat_0\nnewmtl mat_1\n", encoding="utf-8"
    )
    write_image(lib / "cube_diffuse.png", 2048, 1024)
    write_image(lib / "cube_specular.jpg", 512, 512)
    write_cube_obj(lib / "book.obj", materials=1)
    write_image(lib / "book_cover.bmp", 64, 64)
    write_glb_box(lib / "box.glb")
    (lib / "broken.fbx").write_text("this is not an FBX file", encoding="utf-8")
    return lib
