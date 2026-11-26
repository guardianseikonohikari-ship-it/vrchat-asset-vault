"""Tests for .blend support (blend.py + blend_probe.py).

Two tiers, by design:

1. Always-run: the no-Blender fallback (None + a clear reason, never
   an exception), probe-JSON parsing, and Blender lookup rules.
   These must pass on any machine, Blender or not.
2. End-to-end (skipped without Blender): a real .blend is built with
   Blender headless (cube + material), then blend_stats and
   blend_thumbnail run against it and their values are checked.

PENDING ON WINDOWS: the e2e tier is verified here on Linux with
Blender 4.2 LTS. It still needs a run on the user's Windows machine
(with Blender installed from blender.org) to confirm the same
``blender --background`` invocation works there — the code paths are
identical, but PATH lookup and the .tools fallback differ by OS.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from vrchat_asset_vault import blend
from vrchat_asset_vault.blend import (
    blend_stats,
    blend_thumbnail,
    blender_available,
    find_blender,
    parse_probe_json,
    unavailable_reason,
)

# bpy script that builds a test .blend: one cube (12 triangles),
# one material, one packed 64x32 image used by that material.
_MAKE_CUBE_BLEND = r"""
import sys
import bpy

out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2.0)
cube = bpy.context.active_object
mat = bpy.data.materials.new(name="TestMat")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
img = bpy.data.images.new("TestTex", width=64, height=32)
img.pack()
tex.image = img
mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
cube.data.materials.append(mat)
bpy.ops.wm.save_as_mainfile(filepath=out)
print("TEST_BLEND_SAVED:" + out)
"""


def _make_test_blend(blender: Path, out: Path) -> Path:
    script = out.with_suffix(".py")
    script.write_text(_MAKE_CUBE_BLEND, encoding="utf-8")
    proc = subprocess.run(
        [str(blender), "--background", "--python", str(script), "--", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert out.is_file(), (
        f"could not build test .blend (exit {proc.returncode}):\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
    return out


@pytest.fixture()
def no_blender(monkeypatch):
    """Pretend no Blender exists anywhere: PATH, env, and .tools."""
    monkeypatch.setenv("BLENDER_PATH", "")
    monkeypatch.setattr(blend, "find_blender", lambda: None)
    monkeypatch.setattr(blend, "_dev_tools_blender", lambda: None)
    return None


@pytest.fixture()
def real_blender():
    """The Blender binary found on this machine, or skip the e2e tier."""
    found = find_blender()
    if found is None:
        pytest.skip("no Blender on this machine — e2e .blend tests skipped")
    return found


# ---------------------------------------------------------------- fallback

def test_find_blender_respects_blender_path_env(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("BLENDER_PATH", str(fake))
    assert find_blender() == fake


def test_find_blender_env_points_at_directory(monkeypatch, tmp_path):
    fake = tmp_path / "blender"
    fake.write_text("#!/bin/sh\necho fake\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("BLENDER_PATH", str(tmp_path))
    assert find_blender() == fake


def test_blender_available_false_when_missing(no_blender):
    assert blender_available() is False


def test_blend_stats_without_blender_is_none_with_reason(no_blender, tmp_path):
    fake_blend = tmp_path / "thing.blend"
    fake_blend.write_bytes(b"BLENDER-fake")
    assert blend_stats(fake_blend) is None
    reason = unavailable_reason()
    assert reason and "Blender not found" in reason


def test_blend_thumbnail_without_blender_is_none_with_reason(no_blender, tmp_path):
    fake_blend = tmp_path / "thing.blend"
    fake_blend.write_bytes(b"BLENDER-fake")
    assert blend_thumbnail(fake_blend, tmp_path / "cache") is None
    reason = unavailable_reason()
    assert reason and "Blender not found" in reason


def test_blend_stats_missing_file_does_not_raise(tmp_path, real_blender):
    # Blender exists, but the file does not: None + reason, no crash.
    assert blend_stats(tmp_path / "nope.blend") is None
    assert unavailable_reason() and "not found" in unavailable_reason()


# ---------------------------------------------------------------- probe JSON

SAMPLE_PROBE = {
    "triangles": 12,
    "materials": 1,
    "max_texture_px": 2048,
    "texture_count": 2,
    "texture_bytes": 123456,
    "warnings": ["image 'x' has no measurable size (missing file?)"],
}


def test_parse_probe_json_plain():
    assert parse_probe_json(json.dumps(SAMPLE_PROBE)) == SAMPLE_PROBE


def test_parse_probe_json_from_stdout_marker():
    text = "Fra:1 Mem:12.0M\nBLEND_PROBE_JSON:" + json.dumps(SAMPLE_PROBE) + "\nSaved: foo"
    assert parse_probe_json(text) == SAMPLE_PROBE


def test_parse_probe_json_rejects_garbage():
    assert parse_probe_json("") is None
    assert parse_probe_json("not json at all") is None
    assert parse_probe_json("[1, 2, 3]") is None
    assert parse_probe_json('{"triangles": ') is None


def test_parse_probe_json_keeps_probe_error():
    data = parse_probe_json(json.dumps({"error": "boom", "warnings": []}))
    assert data is not None and data["error"] == "boom"


def test_blend_stats_normalises_probe_dict(monkeypatch, tmp_path):
    """blend_stats maps the probe dict onto the scanner's field names."""
    monkeypatch.setattr(
        blend, "_run_probe", lambda *a, **k: dict(SAMPLE_PROBE)
    )
    stats = blend_stats(tmp_path / "x.blend")
    assert stats == {
        "triangles": 12,
        "materials": 1,
        "max_texture_px": 2048,
        "texture_count": 2,
        "texture_bytes": 123456,
        "warnings": SAMPLE_PROBE["warnings"],
    }


def test_blend_stats_propagates_probe_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        blend, "_run_probe", lambda *a, **k: {"error": "boom", "warnings": []}
    )
    assert blend_stats(tmp_path / "x.blend") is None
    assert unavailable_reason() and "boom" in unavailable_reason()


# ---------------------------------------------------------------- end to end

def test_blend_stats_real_cube(real_blender, tmp_path):
    blend_file = _make_test_blend(real_blender, tmp_path / "cube.blend")
    stats = blend_stats(blend_file)
    assert stats is not None, f"blend_stats failed: {unavailable_reason()}"
    assert stats["triangles"] == 12, stats
    assert stats["materials"] == 1, stats
    assert stats["texture_count"] == 1, stats
    assert stats["max_texture_px"] == 64, stats
    assert stats["texture_bytes"] > 0, stats
    assert stats["warnings"] == [], stats


def test_blend_thumbnail_real_cube(real_blender, tmp_path):
    blend_file = _make_test_blend(real_blender, tmp_path / "cube.blend")
    cache = tmp_path / "thumbs"
    thumb = blend_thumbnail(blend_file, cache)
    assert thumb is not None, f"blend_thumbnail failed: {unavailable_reason()}"
    # Same cache layout as preview.thumbnail_for: <sha256>.png
    import hashlib

    digest = hashlib.sha256(blend_file.read_bytes()).hexdigest()
    assert thumb == cache / f"{digest}.png"
    data = thumb.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (192, 192)
    # Second call hits the cache: same path, file untouched.
    before = thumb.stat().st_mtime_ns
    assert blend_thumbnail(blend_file, cache) == thumb
    assert thumb.stat().st_mtime_ns == before


def test_blend_thumbnail_empty_blend_is_none(real_blender, tmp_path):
    """A .blend with no mesh objects: no thumbnail, no crash."""
    script = tmp_path / "empty.py"
    script.write_text(
        "import sys, bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.wm.save_as_mainfile(filepath=sys.argv[sys.argv.index('--') + 1])\n",
        encoding="utf-8",
    )
    empty = tmp_path / "empty.blend"
    subprocess.run(
        [str(real_blender), "--background", "--python", str(script),
         "--", str(empty)],
        capture_output=True, text=True, timeout=120, check=True,
    )
    assert blend_thumbnail(empty, tmp_path / "thumbs") is None
    assert unavailable_reason() and "no geometry" in unavailable_reason()
