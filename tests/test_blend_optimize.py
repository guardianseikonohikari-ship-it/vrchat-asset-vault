"""Tests for the Blender optimizer path (blend_optimize.py + blend.blender_optimize).

Tier 2 of the plan: these need a real Blender and are skipped cleanly
when Blender is absent, exactly like tests/test_blend.py. On this VM
Blender 4.2.0 lives in .tools/ (find_blender discovers it), so they run
here — and the round-trip is verified by re-importing the output FBX
into Blender, not by trusting the script's own numbers.

Two facts about Blender 4.2, verified here (not assumed):
- Icosphere subdivisions are offset by one vs trimesh: subdivisions=3
  gives 320 faces (trimesh needs 2 for the same). The fixtures below
  use 3 so the decimation target is 160.
- Blender 4.2's DEFAULT export writes UnitScaleFactor 1.0 with the
  x100 metre-to-cm conversion baked into every node's local scale —
  but the optimizer's FBX_SCALE_ALL re-export writes 100.0 (the
  metre-to-centimetre factor in the header, node scale 1), which is
  what the current Blender-to-Unity guides prescribe: Unity with
  Scale Factor 1 + Convert Units then reads the model at its
  authored size. A 1.0 factor with metre vertices would import 100x
  too small, so the tests assert 100.0, not 1.0.
- A 0.01 file is Blender's old-export signature (node scale 100 +
  factor 0.01). The optimizer compensates it on import
  (global_scale = 1/0.01), so the output restores the AUTHORED size
  (bbox +-1 for the 1 m sphere) — the plain re-export without
  compensation would preserve the 0.01 size instead.
"""
from __future__ import annotations

import json
import struct
import subprocess
import textwrap
from pathlib import Path

import pytest

from vrchat_asset_vault import blend
from vrchat_asset_vault.budget import PRESETS
from vrchat_asset_vault.optimizer import optimize_asset
from vrchat_asset_vault.scanner import fbx_unit_scale_factor

pytest.importorskip("trimesh", reason="optimizer tests need trimesh")


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def no_blender(monkeypatch):
    """Pretend no Blender exists anywhere: PATH, env, and .tools."""
    monkeypatch.setenv("BLENDER_PATH", "")
    monkeypatch.setattr(blend, "find_blender", lambda: None)
    monkeypatch.setattr(blend, "_dev_tools_blender", lambda: None)
    return None


@pytest.fixture()
def blender_exe() -> Path:
    """The Blender this VM can actually run (skips the file if absent)."""
    exe = blend.find_blender()
    if exe is None:
        pytest.skip("no Blender installed here")
    return exe


def _run_builder(blender_exe: Path, script: str, args: list[str]) -> None:
    """Run a small bpy builder script; raises on failure."""
    script_path = Path(args[0]).parent / "_builder.py"
    script_path.write_text(textwrap.dedent(script), encoding="utf-8")
    result = subprocess.run(
        [str(blender_exe), "--background", "--python", str(script_path), "--", *args],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def _make_sphere_blend(blender_exe: Path, path: Path, subdivisions: int = 3) -> None:
    """A .blend with an icosphere (subdivisions=3 → 320 faces)."""
    _run_builder(blender_exe, f"""
        import bpy, sys
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions={subdivisions})
        bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
    """, [str(path)])


def _make_fbx_sphere(blender_exe: Path, path: Path, subdivisions: int = 3) -> None:
    """A real FBX exported by Blender (factor 1.0 on Blender 4.2)."""
    _run_builder(blender_exe, f"""
        import bpy, sys
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions={subdivisions})
        bpy.ops.export_scene.fbx(filepath=sys.argv[-1])
    """, [str(path)])


def _patch_fbx_scale(path: Path, factor: float) -> None:
    """Rewrite the UnitScaleFactor double in a real FBX (fixture only).

    The anchor is the same one scanner.fbx_unit_scale_factor() uses;
    the double sits right after the property header. Patching a
    Blender 4.2 DEFAULT export (node scale 100, factor 1.0) to 0.01
    reproduces exactly the file older Blender versions exported —
    node scale 100 + factor 0.01 — the pattern the optimizer's scale
    fix targets. The optimizer itself never patches bytes.
    """
    data = bytearray(path.read_bytes())
    anchor = data.find(b"UnitScaleFactor")
    assert anchor > 0
    j = data.find(struct.pack("<d", 1.0), anchor, anchor + 80)
    assert j > 0, "no 1.0 double after the UnitScaleFactor anchor"
    data[j:j + 8] = struct.pack("<d", factor)
    path.write_bytes(bytes(data))
    assert fbx_unit_scale_factor(path) == factor


def _make_shape_key_blend(blender_exe: Path, path: Path) -> None:
    _run_builder(blender_exe, """
        import bpy, sys
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        obj.shape_key_add(name="Basis")
        obj.shape_key_add(name="Smile")
        bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
    """, [str(path)])


def _make_armature_blend(blender_exe: Path, path: Path) -> None:
    _run_builder(blender_exe, """
        import bpy, sys
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        bpy.ops.object.armature_add()
        arm = bpy.context.active_object
        mod = obj.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = arm
        bpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])
    """, [str(path)])


def _fbx_face_count(blender_exe: Path, path: Path) -> int:
    """Re-import an FBX in a fresh Blender and count its polygons.

    Independent verification of the optimizer's own numbers — the
    script saying "160 triangles" is not proof the file says so too.
    """
    script_path = path.parent / "_count.py"
    script_path.write_text(textwrap.dedent(f"""
        import bpy, sys
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath={str(path)!r})
        total = sum(len(o.data.polygons) for o in bpy.data.objects
                    if o.type == "MESH")
        print(f"FACE_COUNT={{total}}")
    """), encoding="utf-8")
    result = subprocess.run(
        [str(blender_exe), "--background", "--python", str(script_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    for line in result.stdout.splitlines():
        if line.startswith("FACE_COUNT="):
            return int(line.split("=", 1)[1])
    raise AssertionError("FACE_COUNT not printed:\n" + result.stdout[-2000:])


def _fbx_bbox(blender_exe: Path, path: Path):
    """World-space bbox of an FBX as Blender's importer sees it."""
    script_path = path.parent / "_bbox.py"
    script_path.write_text(textwrap.dedent(f"""
        import bpy, sys, json
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath={str(path)!r})
        mins = [1e9]*3; maxs = [-1e9]*3
        for o in bpy.data.objects:
            if o.type != "MESH":
                continue
            for v in o.data.vertices:
                w = o.matrix_world @ v.co
                for i in range(3):
                    mins[i] = min(mins[i], w[i]); maxs[i] = max(maxs[i], w[i])
        print("BBOX_JSON=" + json.dumps([mins, maxs]))
    """), encoding="utf-8")
    result = subprocess.run(
        [str(blender_exe), "--background", "--python", str(script_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    for line in result.stdout.splitlines():
        if line.startswith("BBOX_JSON="):
            return json.loads(line.split("=", 1)[1])
    raise AssertionError("BBOX_JSON not printed:\n" + result.stdout[-2000:])


def _assert_authored_unit_sphere(bbox, label: str = "") -> None:
    """The re-imported bbox of a 1 m sphere is +-1 on every axis.

    This is the size check that matters for the scale fix: the output
    must restore the AUTHORED size, not the +-0.01 the 0.01 file
    defines when read without compensation.
    """
    for ax in range(3):
        assert abs(bbox[0][ax] - (-1.0)) < 0.01, (label, ax, bbox)
        assert abs(bbox[1][ax] - 1.0) < 0.01, (label, ax, bbox)


# ---------------------------------------------------------------- Blender path

def test_blender_optimize_fbx_decimates_and_fixes_scale(tmp_path, blender_exe):
    fbx = tmp_path / "sphere.fbx"
    _make_fbx_sphere(blender_exe, fbx, subdivisions=3)
    _patch_fbx_scale(fbx, 0.01)  # the old-Blender 0.01 case
    rep = optimize_asset(fbx, tmp_path / "out", PRESETS["Balanced"], engine="blender")
    assert rep.status == "optimized", rep
    assert rep.engine == "blender"
    assert rep.triangles_before == 320
    assert rep.triangles_after == 160, rep
    assert rep.scale_fixed is True
    assert rep.output.suffix.lower() == ".fbx"
    # FBX_SCALE_ALL puts the metre-to-centimetre factor in the header:
    # 100.0 for a metre scene (NOT 1.0 — that would import 100x small).
    assert fbx_unit_scale_factor(rep.output) == 100.0
    # Independent checks: the output FBX really has 160 polygons and
    # restores the authored 1 m size (bbox +-1, object scale 1).
    assert _fbx_face_count(blender_exe, rep.output) == 160
    _assert_authored_unit_sphere(_fbx_bbox(blender_exe, rep.output), "decimated")


def test_blender_optimize_blend_to_fbx(tmp_path, blender_exe):
    blend_path = tmp_path / "sphere.blend"
    _make_sphere_blend(blender_exe, blend_path, subdivisions=3)
    rep = optimize_asset(
        blend_path, tmp_path / "out", PRESETS["Balanced"], engine="blender"
    )
    assert rep.status == "optimized", rep
    assert rep.triangles_before == 320
    assert rep.triangles_after == 160
    assert rep.output.suffix.lower() == ".fbx"  # .blend → FBX delivery
    assert _fbx_face_count(blender_exe, rep.output) == 160


def test_blender_optimize_small_blend_unchanged(tmp_path, blender_exe):
    """A 20-face .blend is below the floor: copied, never decimated."""
    blend_path = tmp_path / "cube.blend"
    _make_sphere_blend(blender_exe, blend_path, subdivisions=1)  # 20 faces
    rep = optimize_asset(
        blend_path, tmp_path / "out", PRESETS["Balanced"], engine="blender"
    )
    assert rep.status == "unchanged", rep
    assert rep.output.suffix.lower() == ".blend"
    assert rep.output.read_bytes() == blend_path.read_bytes()


def test_blender_optimize_skips_shape_keys(tmp_path, blender_exe):
    blend_path = tmp_path / "face.blend"
    _make_shape_key_blend(blender_exe, blend_path)
    rep = optimize_asset(
        blend_path, tmp_path / "out", PRESETS["Balanced"], engine="blender"
    )
    assert rep.status == "skipped", rep
    assert "shape key" in rep.reason
    assert rep.output.read_bytes() == blend_path.read_bytes()


def test_blender_optimize_skips_armature(tmp_path, blender_exe):
    blend_path = tmp_path / "rigged.blend"
    _make_armature_blend(blender_exe, blend_path)
    rep = optimize_asset(
        blend_path, tmp_path / "out", PRESETS["Balanced"], engine="blender"
    )
    assert rep.status == "skipped", rep
    assert "armature" in rep.reason


def test_blender_optimize_no_blender_returns_none(tmp_path, no_blender):
    result = blend.blender_optimize(
        tmp_path / "sphere.fbx", tmp_path / "out.fbx",
        keep_ratio=0.5, cap=50_000, max_texture_px=1024,
    )
    assert result is None


def test_blender_optimize_missing_file(tmp_path, blender_exe):
    result = blend.blender_optimize(
        tmp_path / "nope.fbx", tmp_path / "out.fbx",
        keep_ratio=0.5, cap=50_000, max_texture_px=1024,
    )
    assert result is None


def test_blender_optimize_cancel(tmp_path, blender_exe):
    import threading

    fbx = tmp_path / "sphere.fbx"
    _make_fbx_sphere(blender_exe, fbx, subdivisions=3)
    cancel = threading.Event()
    cancel.set()
    result = blend.blender_optimize(
        fbx, tmp_path / "out.fbx", keep_ratio=0.5, cap=50_000,
        max_texture_px=1024, cancel_event=cancel,
    )
    assert result is None
    # Blender was killed mid-run; the partial output must not linger.
    assert not (tmp_path / "out.fbx").is_file()


def test_blender_optimize_json_parsing_tolerates_noise():
    from vrchat_asset_vault.blend import _parse_optimize_json

    payload = {"status": "optimized", "triangles_after": 160}
    raw = json.dumps(payload)
    assert _parse_optimize_json(raw) == payload  # report file form
    text = "Fra:1 Mem:12.3M\nBLEND_OPTIMIZE_JSON:" + raw + "\nDone\n"
    assert _parse_optimize_json(text) == payload  # stdout form
    assert _parse_optimize_json("no marker here") is None


def test_blender_optimize_scale_fix_only(tmp_path, blender_exe):
    """Scale 0.01 but already within budget → re-export, no decimation."""
    fbx = tmp_path / "cube.fbx"
    _make_fbx_sphere(blender_exe, fbx, subdivisions=1)  # 20 faces
    # The authored size, measured BEFORE patching: a 20-face
    # icosphere's bbox is not +-1 on every axis, so the comparison
    # must use the real authored bbox, not the unit sphere.
    authored_bbox = _fbx_bbox(blender_exe, fbx)
    _patch_fbx_scale(fbx, 0.01)
    rep = optimize_asset(fbx, tmp_path / "out", PRESETS["Balanced"], engine="blender")
    assert rep.status == "optimized", rep
    assert rep.triangles_after == 20  # mesh untouched
    assert rep.scale_fixed is True
    assert fbx_unit_scale_factor(rep.output) == 100.0
    assert _fbx_face_count(blender_exe, rep.output) == 20
    after_bbox = _fbx_bbox(blender_exe, rep.output)
    for ax in range(3):
        d0 = authored_bbox[1][ax] - authored_bbox[0][ax]
        d1 = after_bbox[1][ax] - after_bbox[0][ax]
        assert abs(d1 - d0) / d0 < 0.01, (ax, d0, d1)
