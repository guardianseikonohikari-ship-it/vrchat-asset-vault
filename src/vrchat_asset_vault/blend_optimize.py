"""Optimize script run INSIDE Blender (bpy) — never imported by the app.

Usage (from blend.blender_optimize, or by hand):

    blender --background <file.blend> --python blend_optimize.py -- \\
        --out <out.fbx> --keep-ratio 0.5 --cap 50000 --max-tex 1024 \\
        --min-triangles 100 --report <report.json>
    blender --background --python blend_optimize.py -- \\
        --input <file.fbx> --out <out.fbx> --keep-ratio 0.5 --cap 50000 \\
        --max-tex 1024 --report <report.json> --snapshots <dir>

It opens the file (or the .blend Blender already opened), refuses
meshes with shape keys / armatures / animation (decimation would
destroy them), cleans the meshes, decimates with the COLLAPSE
modifier only (never a remesh — a remesh throws UVs away), fixes
the FBX scale by re-exporting (never by patching bytes), scales
packed images, and exports the result. The source file on disk is
never saved or modified.

Output: one JSON object written to <report.json> and echoed on stdout
after the marker ``BLEND_OPTIMIZE_JSON:``. Status is "optimized",
"unchanged" (nothing to do — the caller copies the original instead),
"skipped" (shape keys / armature / animation) or "failed".
"""
import json
import os
import sys

import bpy


def _parse_args(argv):
    args = {
        "input": None,
        "out": None,
        "keep_ratio": 0.5,
        "cap": 50000,
        "max_tex": 1024,
        "report": None,
        "snapshots": None,
        "source_scale": None,
        # Below this triangle count decimation saves nothing and only
        # risks breaking the mesh (a 12-triangle cube is never
        # "optimized" to 6). Mirrors budget.MIN_DECIMATE_TRIANGLES.
        "min_triangles": 100,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--input":
            args["input"] = argv[i + 1]; i += 2
        elif a == "--out":
            args["out"] = argv[i + 1]; i += 2
        elif a == "--keep-ratio":
            args["keep_ratio"] = float(argv[i + 1]); i += 2
        elif a == "--cap":
            args["cap"] = int(argv[i + 1]); i += 2
        elif a == "--max-tex":
            args["max_tex"] = int(argv[i + 1]); i += 2
        elif a == "--report":
            args["report"] = argv[i + 1]; i += 2
        elif a == "--snapshots":
            args["snapshots"] = argv[i + 1]; i += 2
        elif a == "--source-scale":
            args["source_scale"] = float(argv[i + 1]); i += 2
        elif a == "--min-triangles":
            args["min_triangles"] = int(argv[i + 1]); i += 2
        else:
            i += 1
    return args


def _open_input(path, source_scale=None):
    """Open a model file into an empty scene, by extension.

    FBX with a 0.01 scale factor is Blender's old-export signature:
    the exporter baked the metre-to-cm x100 into every object's
    local scale and wrote 0.01 in the header, so a plain import
    lands 100x too small (object scale 0.01). Importing it with
    global_scale = 1/source_scale compensates exactly and restores
    the authored size. Only 0.01 is compensated: it is the one
    factor no sane exporter uses as a correct unit, so any other
    factor (inches, centimetres, ...) is a legitimate unit choice
    and is left alone — the re-export normalizes its header while
    preserving the size as read.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=path)
    elif suffix == ".fbx":
        kwargs = {}
        if source_scale is not None and abs(source_scale - 0.01) < 1e-6:
            kwargs["global_scale"] = 1.0 / source_scale
        bpy.ops.import_scene.fbx(filepath=path, **kwargs)
    elif suffix == ".obj":
        try:
            bpy.ops.wm.obj_import(filepath=path)
        except Exception:
            bpy.ops.import_scene.obj(filepath=path)
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise ValueError("unsupported input format: %s" % suffix)


def _expected_unit_scale_factor():
    """The UnitScaleFactor the FBX re-export should write.

    Mirrors Blender's own ``units_blender_to_fbx_factor``: 100 x the
    scene's unit scale (100.0 for a metre scene). The verification
    gate checks the output file against this, so the expectation
    follows the scene's units instead of assuming 1.0 or 100.0.
    """
    units = bpy.context.scene.unit_settings
    if units.system == "NONE":
        return 100.0
    return 100.0 * units.scale_length


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _skip_reason(obj):
    """Why this mesh must not be decimated, or None when it is safe."""
    keys = obj.data.shape_keys
    # Basis-only is not a deformation: only real shape keys block.
    if keys is not None and len(keys.key_blocks) > 1:
        return "has shape keys"
    for mod in obj.modifiers:
        if mod.type == "ARMATURE":
            return "has armature"
    if obj.parent is not None and obj.parent.type == "ARMATURE":
        return "has armature"
    anim = obj.animation_data
    if anim is not None and (anim.action is not None or len(anim.nla_tracks) > 0):
        return "has animation"
    return None


def _evaluated_mesh(obj):
    """(eval_obj, mesh) — caller must to_mesh_clear() when needed."""
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        return eval_obj, eval_obj.to_mesh()
    except Exception:
        return obj, obj.data


def _count_triangles(obj):
    eval_obj, mesh = _evaluated_mesh(obj)
    try:
        mesh.calc_loop_triangles()
        return len(mesh.loop_triangles)
    finally:
        if mesh is not obj.data:
            eval_obj.to_mesh_clear()


def _bbox(obj):
    """World-space (min, max) of one mesh object, or None when empty."""
    eval_obj, mesh = _evaluated_mesh(obj)
    try:
        if not mesh.vertices:
            return None
        mins = [float("inf")] * 3
        maxs = [float("-inf")] * 3
        mw = obj.matrix_world
        for v in mesh.vertices:
            w = mw @ v.co
            for i in range(3):
                mins[i] = min(mins[i], w[i])
                maxs[i] = max(maxs[i], w[i])
        return [mins, maxs]
    finally:
        if mesh is not obj.data:
            eval_obj.to_mesh_clear()


def _union_bbox(objs):
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    found = False
    for obj in objs:
        box = _bbox(obj)
        if box is None:
            continue
        found = True
        for i in range(3):
            mins[i] = min(mins[i], box[0][i])
            maxs[i] = max(maxs[i], box[1][i])
    return [mins, maxs] if found else None


def _clean_mesh(obj):
    """Merge doubles, drop degenerate faces and loose verts, fix normals.

    Small disconnected components are NOT removed — a floating
    fragment on a prop can be intentional (a candle flame, a book).
    """
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
    bm.faces.ensure_lookup_table()
    dead = [f for f in bm.faces if f.calc_area() < 1e-12]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
    bm.verts.ensure_lookup_table()
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def _add_decimate(obj, ratio):
    """Decimate COLLAPSE only — a remesh would throw the UVs away."""
    mod = obj.modifiers.new(name="VaultDecimate", type="DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = max(0.01, min(1.0, ratio))
    mod.use_collapse_triangulate = True
    return mod


def _select_meshes(objs):
    for o in bpy.context.scene.objects:
        o.select_set(o in objs)
    if objs:
        bpy.context.view_layer.objects.active = objs[0]


def _export_obj_snapshot(path, apply_modifiers):
    objs = _mesh_objects()
    if not objs:
        return
    _select_meshes(objs)
    try:
        bpy.ops.wm.obj_export(
            filepath=path,
            export_selected_objects=True,
            apply_modifiers=apply_modifiers,
            export_uv=True,
            export_normals=True,
            export_materials=False,
        )
    except Exception:
        bpy.ops.export_scene.obj(
            filepath=path,
            use_selection=True,
            use_mesh_modifiers=apply_modifiers,
        )


def _scale_images(max_tex):
    """Scale packed/linked images over the limit, in memory.

    Returns (scaled_names, bytes_before, bytes_after); byte sizes use
    the same rule as blend_probe (packed size, else RGBA estimate).
    """
    scaled = []
    bytes_before = 0
    bytes_after = 0
    for img in bpy.data.images:
        w, h = img.size[0], img.size[1]
        if w <= 0 or h <= 0:
            continue
        size = None
        try:
            if img.packed_file is not None:
                size = len(img.packed_file.data)
        except Exception:
            size = None
        if not size:
            size = w * h * 4
        bytes_before += size
        if max(w, h) > max_tex:
            try:
                scale = max_tex / max(w, h)
                nw = max(1, int(w * scale))
                nh = max(1, int(h * scale))
                img.scale(nw, nh)
                scaled.append(img.name)
                bytes_after += nw * nh * 4
            except Exception:
                bytes_after += size
        else:
            bytes_after += size
    return scaled, bytes_before, bytes_after


def _export_main(out_path):
    """Write the optimized model. Scale is fixed by the re-export."""
    suffix = os.path.splitext(out_path)[1].lower()
    if suffix == ".fbx":
        kwargs = dict(
            filepath=out_path,
            use_selection=False,
            apply_scale_options="FBX_SCALE_ALL",
            apply_unit_scale=True,
            global_scale=1.0,
            bake_space_transform=True,
            axis_forward="-Z",
            axis_up="Y",
            path_mode="COPY",
            use_mesh_modifiers=True,
            bake_anim=False,
        )
        try:
            bpy.ops.export_scene.fbx(**kwargs)
        except TypeError:
            # Older Blender without one of the keywords: plain export.
            bpy.ops.export_scene.fbx(filepath=out_path, use_selection=False)
    elif suffix == ".obj":
        try:
            bpy.ops.wm.obj_export(
                filepath=out_path,
                export_selected_objects=False,
                apply_modifiers=True,
                export_uv=True,
                export_normals=True,
                export_materials=True,
                path_mode="COPY",
            )
        except Exception:
            bpy.ops.export_scene.obj(
                filepath=out_path,
                use_selection=False,
                use_mesh_modifiers=True,
            )
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.export_scene.gltf(
            filepath=out_path,
            export_format="GLB" if suffix == ".glb" else "GLTF_SEPARATE",
            export_apply=True,
            export_yup=True,
        )
    else:
        raise ValueError("unsupported output format: %s" % suffix)


def _write_report(args, result):
    payload = json.dumps(result)
    if args["report"]:
        with open(args["report"], "w", encoding="utf-8") as f:
            f.write(payload)
    print("BLEND_OPTIMIZE_JSON:" + payload)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = _parse_args(argv)
    result = {"status": "failed", "warnings": []}
    try:
        if args["input"]:
            _open_input(args["input"], args["source_scale"])
        objs = _mesh_objects()
        if not objs:
            result["status"] = "failed"
            result["error"] = "no mesh objects found"
            _write_report(args, result)
            return
        for obj in objs:
            reason = _skip_reason(obj)
            if reason:
                result["status"] = "skipped"
                result["reason"] = "%s: %s" % (obj.name, reason)
                result["triangles_before"] = sum(_count_triangles(o) for o in objs)
                _write_report(args, result)
                return
        tris_before = sum(_count_triangles(o) for o in objs)
        bbox_before = _union_bbox(objs)
        for obj in objs:
            _clean_mesh(obj)
        if args["snapshots"]:
            os.makedirs(args["snapshots"], exist_ok=True)
            _export_obj_snapshot(
                os.path.join(args["snapshots"], "before.obj"), False
            )
        target = None
        if tris_before > args["min_triangles"]:
            target = min(int(tris_before * args["keep_ratio"]), args["cap"])
        decimated = target is not None and target < tris_before
        if decimated:
            ratio = target / tris_before if tris_before else 1.0
            for obj in objs:
                _add_decimate(obj, ratio)
            bpy.context.view_layer.update()
        tris_after = sum(_count_triangles(o) for o in objs)
        bbox_after = _union_bbox(objs)
        if args["snapshots"]:
            _export_obj_snapshot(
                os.path.join(args["snapshots"], "after.obj"), True
            )
        scaled, tex_before, tex_after = _scale_images(args["max_tex"])
        scale_fixed = (
            args["source_scale"] is not None and args["source_scale"] != 1.0
        )
        if decimated or scale_fixed:
            _export_main(args["out"])
        materials = set()
        for obj in objs:
            for slot in obj.material_slots:
                if slot.material is not None:
                    materials.add(slot.material.name)
        result.update(
            {
                "status": "optimized" if (decimated or scale_fixed) else "unchanged",
                "decimated": decimated,
                "scale_fixed": scale_fixed,
                "triangles_before": tris_before,
                "triangles_after": tris_after,
                "target_triangles": target,
                "materials": len(materials),
                "bbox_before": bbox_before,
                "bbox_after": bbox_after,
                "unit_scale_factor": _expected_unit_scale_factor(),
                "images_scaled": scaled,
                "texture_bytes_before": tex_before,
                "texture_bytes_after": tex_after,
            }
        )
    except Exception as exc:  # never crash Blender without a JSON file
        result["status"] = "failed"
        result["error"] = str(exc)
    _write_report(args, result)


main()
