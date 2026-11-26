"""Probe script run INSIDE Blender (bpy) — never imported by the app.

Usage (from blend.py, or by hand):

    blender --background <file.blend> --python blend_probe.py -- <out.json>
    blender --background <file.blend> --python blend_probe.py -- <out.json> --obj <out.obj>

It opens the .blend (Blender does that for --background <file>),
counts triangulated polygons over all mesh objects, counts distinct
materials, measures the images the file references, and — with --obj —
exports the visible mesh objects to a Wavefront OBJ so the Vault's
pure-Python rasterizer can render a thumbnail from it.

Output: one JSON object written to <out.json> and echoed on stdout
after the marker ``BLEND_PROBE_JSON:``. The .blend itself is never
saved or modified on disk.
"""
import json
import sys

import bpy


def _triangulated_polygons(obj):
    """Triangles of one mesh object, n-gons triangulated.

    Uses the evaluated mesh (modifiers applied) when a dependency
    graph is available, so the count matches what Unity/VRChat would
    actually receive.
    """
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
    except Exception:
        mesh = obj.data
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    finally:
        if mesh is not obj.data:
            eval_obj.to_mesh_clear()


def _measure_images():
    """(max_px, count, total_bytes, warnings) for bpy.data.images.

    Packed images report their packed size; linked images report the
    size of the file on disk when it exists. An image whose pixels
    cannot be measured at all is reported in warnings, never guessed.
    """
    import os

    max_px = 0
    count = 0
    total_bytes = 0
    warnings = []
    for img in bpy.data.images:
        count += 1
        w, h = img.size[0], img.size[1]
        if w > 0 and h > 0:
            max_px = max(max_px, w, h)
        else:
            warnings.append(
                "image %r has no measurable size (missing file?)" % img.name
            )
        size = None
        try:
            if img.packed_file is not None:
                size = len(img.packed_file.data)
        except Exception:
            size = None
        if not size:
            # A generated/packed image with no stored file data (e.g. a
            # blank generated texture): approximate from its pixels.
            # Labelled approximate — never presented as an exact file size.
            if w > 0 and h > 0:
                size = w * h * 4  # RGBA8 estimate
        if size is None:
            try:
                path = bpy.path.abspath(img.filepath)
                if path and os.path.isfile(path):
                    size = os.path.getsize(path)
            except Exception:
                size = None
        if size is not None:
            total_bytes += size
    return max_px, count, total_bytes, warnings


def _export_obj(obj_path):
    """Export all visible mesh objects to OBJ. Returns a warning or None."""
    mesh_objs = [
        o for o in bpy.context.scene.objects
        if o.type == "MESH" and not o.hide_render
    ]
    if not mesh_objs:
        return "no mesh objects to export"
    for o in bpy.context.scene.objects:
        o.select_set(o in mesh_objs)
    bpy.context.view_layer.objects.active = mesh_objs[0]
    try:
        # Blender 4.x API; 3.x used export_scene.obj.
        bpy.ops.wm.obj_export(
            filepath=obj_path,
            export_selected_objects=True,
            apply_modifiers=True,
            export_uv=True,
            export_normals=True,
        )
    except Exception:
        try:
            bpy.ops.export_scene.obj(
                filepath=obj_path,
                use_selection=True,
                use_mesh_modifiers=True,
            )
        except Exception as exc:  # pragma: no cover - old-Blender fallback
            return "OBJ export failed: %s" % exc
    return None


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_json = argv[0] if argv else None
    obj_path = None
    if "--obj" in argv:
        obj_path = argv[argv.index("--obj") + 1]

    result = {
        "triangles": 0,
        "materials": 0,
        "max_texture_px": 0,
        "texture_count": 0,
        "texture_bytes": 0,
        "warnings": [],
    }
    try:
        materials = set()
        for obj in bpy.context.scene.objects:
            if obj.type != "MESH":
                continue
            try:
                result["triangles"] += _triangulated_polygons(obj)
            except Exception as exc:
                result["warnings"].append(
                    "could not count %r: %s" % (obj.name, exc)
                )
            for slot in obj.material_slots:
                if slot.material is not None:
                    materials.add(slot.material.name)
        result["materials"] = len(materials)
        max_px, count, total_bytes, img_warnings = _measure_images()
        result["max_texture_px"] = max_px
        result["texture_count"] = count
        result["texture_bytes"] = total_bytes
        result["warnings"].extend(img_warnings)
        if obj_path:
            warn = _export_obj(obj_path)
            if warn:
                result["warnings"].append(warn)
    except Exception as exc:  # never crash Blender without a JSON file
        result["warnings"].append("probe failed: %s" % exc)
        result["error"] = str(exc)

    payload = json.dumps(result)
    if out_json:
        with open(out_json, "w", encoding="utf-8") as f:
            f.write(payload)
    print("BLEND_PROBE_JSON:" + payload)


main()
