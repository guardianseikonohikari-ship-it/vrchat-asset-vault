"""CLI core — the same code the PySide6 GUI will call."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .budget import check_asset, check_world, fmt_bytes, AssetStats, preset_for
from .database import (
    collection_texture_totals,
    connect,
    list_assets,
    load_meta,
    prune_missing,
    upsert_asset,
)
from .exporter import export_collection, export_unitypackage
from .optimizer import optimize_collection
from .scanner import scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vrchat-asset-vault")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Index a folder recursively")
    p_scan.add_argument("root")
    p_scan.add_argument("--db", default="vault.db")

    p_budget = sub.add_parser("budget", help="World budget summary from the index")
    p_budget.add_argument("db")
    p_budget.add_argument("--world", default="")

    p_export = sub.add_parser("export", help="Export a collection cleanly for Unity")
    p_export.add_argument("db")
    p_export.add_argument("--collection", required=True)
    p_export.add_argument("--out", required=True)

    p_package = sub.add_parser(
        "package", help="Export a collection as one .unitypackage file"
    )
    p_package.add_argument("db")
    p_package.add_argument("--collection", required=True)
    p_package.add_argument("--out", required=True)

    p_opt = sub.add_parser(
        "optimize", help="Make a collection Quest-ready (decimate + downscale)"
    )
    p_opt.add_argument("db")
    p_opt.add_argument("--collection", required=True)
    p_opt.add_argument("--out", default=None)
    p_opt.add_argument("--preset", default="Balanced",
                       choices=["Gentle", "Balanced", "Aggressive"])
    p_opt.add_argument("--engine", default="auto",
                       choices=["auto", "blender", "trimesh"])

    sub.add_parser("gui", help="Open the intuitive graphical interface")

    args = parser.parse_args(argv)

    if args.cmd == "gui":
        from .gui import run

        return run()

    if args.cmd == "scan":
        assets = scan(Path(args.root))
        conn = connect(Path(args.db))
        for a in assets:
            upsert_asset(conn, a)
            card = check_asset(
                AssetStats(
                    triangles=a.triangles,
                    materials=a.materials,
                    max_texture_px=a.max_texture_px,
                    scale_factor=a.scale_factor,
                    size_bytes=a.size_bytes,
                )
            )
            line = (
                f"{a.path.name}: tris={a.triangles} "
                f"materials={a.materials} "
                f"max_tex={a.max_texture_px or '?'}px "
                f"quest={card['triangles_quest']}"
            )
            if a.scale_factor is not None:
                line += f" scale={a.scale_factor}"
            print(line)
            for w in a.warnings + card["warnings"]:
                print(f"  ! {w}")
        removed = prune_missing(conn, {str(a.path) for a in assets})
        print(f"Indexed {len(assets)} models into {args.db}")
        if removed:
            print(f"Removed {removed} entries whose files no longer exist.")
        return 0

    if args.cmd == "budget":
        conn = connect(Path(args.db))
        rows = list_assets(conn)
        total_tris = sum(r[1] or 0 for r in rows)
        total_size = sum(r[2] for r in rows)
        result = check_world(total_tris, total_size)
        totals = collection_texture_totals(conn)
        tex_mb = totals["texture_bytes"] / 1024 / 1024
        print(f"World: {args.world or '(all indexed)'}")
        print(f"Assets: {len(rows)}  Triangles: {total_tris:,}")
        print(f"Quest triangles: {result['quest_triangles']} (budget 250,000)")
        print(f"Size: {total_size / 1024 / 1024:.1f} MB (Quest limit 100 MB)")
        print(f"Textures: {tex_mb:.1f} MB (Quest limit 100 MB)")
        for h in totals["heaviest"]:
            print(f"  heaviest: {Path(h['path']).name} {fmt_bytes(h['texture_bytes'])}")
        return 0

    if args.cmd == "export":
        conn = connect(Path(args.db))
        rows = list_assets(conn, args.collection)
        paths = [Path(r[0]) for r in rows]
        meta = {str(p): load_meta(conn, str(p)) for p in paths}
        result = export_collection(paths, Path(args.out), args.collection, meta_by_path=meta)
        print(f"Exported {result['assets']} assets to {result['out_dir']}")
        for w in result["warnings"]:
            print(f"  ! {w}")
        return 0

    if args.cmd == "package":
        conn = connect(Path(args.db))
        rows = list_assets(conn, args.collection)
        paths = [Path(r[0]) for r in rows]
        meta = {str(p): load_meta(conn, str(p)) for p in paths}
        result = export_unitypackage(
            paths, Path(args.out), args.collection, meta_by_path=meta
        )
        print(f"Exported {result['assets']} assets to {result['out_file']}")
        for w in result["warnings"]:
            print(f"  ! {w}")
        return 0

    if args.cmd == "optimize":
        from .optimizer import OptimizeCancelled

        conn = connect(Path(args.db))
        rows = list_assets(conn, args.collection)
        paths = [Path(r[0]) for r in rows]
        meta = {str(p): load_meta(conn, str(p)) for p in paths}
        favorites = {str(p) for p in paths if meta[str(p)].get("favorite")}
        conn.close()
        if not paths:
            print(f"Nothing to optimize — collection '{args.collection}' is empty.")
            return 0
        preset = preset_for(args.preset)
        out_dir = (
            Path(args.out)
            if args.out
            else Path(f"Optimized_{args.collection}")
        )
        print(
            f"Optimizing {len(paths)} asset(s) ({preset.name}: keep "
            f"{int(preset.keep_ratio * 100)}% of triangles, textures "
            f"≤{preset.max_texture_px}px) → {out_dir}"
        )
        reports = []
        try:
            for rep in optimize_collection(
                paths, out_dir, args.collection, preset,
                meta_by_path=meta, favorites=favorites, engine=args.engine,
            ):
                reports.append(rep)
                tris = (
                    f"{rep.triangles_before:,} → {rep.triangles_after:,} tris"
                    if rep.triangles_before is not None
                    and rep.triangles_after is not None
                    else f"tris {rep.triangles_after}"
                )
                line = f"{rep.source.name}: {rep.status} ({tris}, {rep.engine})"
                if rep.reason:
                    line += f" — {rep.reason}"
                print(line)
                for w in rep.warnings:
                    print(f"  ! {w}")
                if rep.check_visually:
                    print("  ! check the model visually before using it")
        except OptimizeCancelled:
            print("Cancelled — partial results are in the output folder.")
        totals = {
            "triangles_before": sum(r.triangles_before or 0 for r in reports),
            "triangles_after": sum(r.triangles_after or 0 for r in reports),
            "texture_before": sum(r.texture_bytes_before for r in reports),
            "texture_after": sum(r.texture_bytes_after for r in reports),
        }
        print(
            f"Triangles: {totals['triangles_before']:,} → "
            f"{totals['triangles_after']:,} "
            f"(Quest budget 250,000)"
        )
        print(
            f"Textures: {fmt_bytes(totals['texture_before'])} → "
            f"{fmt_bytes(totals['texture_after'])} (Quest limit 100 MB)"
        )
        print(f"Report: {out_dir / 'optimization_report.json'}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
