"""CLI core — the same code the PySide6 GUI will call."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .budget import check_asset, check_world, fmt_bytes, AssetStats
from .database import (
    collection_texture_totals,
    connect,
    list_assets,
    load_meta,
    prune_missing,
    upsert_asset,
)
from .exporter import export_collection, export_unitypackage
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

    return 2


if __name__ == "__main__":
    sys.exit(main())
