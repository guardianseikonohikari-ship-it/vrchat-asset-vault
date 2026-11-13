"""CLI core — the same code the PySide6 GUI will call."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .budget import check_asset, check_world, AssetStats
from .database import connect, list_assets, upsert_asset
from .exporter import export_collection
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

    args = parser.parse_args(argv)

    if args.cmd == "scan":
        assets = scan(Path(args.root))
        conn = connect(Path(args.db))
        for a in assets:
            upsert_asset(conn, a)
            card = check_asset(
                AssetStats(triangles=a.triangles, size_bytes=a.size_bytes)
            )
            print(f"{a.path.name}: tris={a.triangles} quest={card['triangles_quest']}")
            for w in a.warnings + card["warnings"]:
                print(f"  ! {w}")
        print(f"Indexed {len(assets)} models into {args.db}")
        return 0

    if args.cmd == "budget":
        conn = connect(Path(args.db))
        rows = list_assets(conn)
        total_tris = sum(r[1] or 0 for r in rows)
        total_size = sum(r[2] for r in rows)
        result = check_world(total_tris, total_size)
        print(f"World: {args.world or '(all indexed)'}")
        print(f"Assets: {len(rows)}  Triangles: {total_tris:,}")
        print(f"Quest triangles: {result['quest_triangles']} (budget 250,000)")
        print(f"Size: {total_size / 1024 / 1024:.1f} MB (Quest limit 100 MB)")
        return 0

    if args.cmd == "export":
        conn = connect(Path(args.db))
        rows = list_assets(conn, args.collection)
        result = export_collection(
            [Path(r[0]) for r in rows], Path(args.out), args.collection
        )
        print(f"Exported {result['assets']} assets to {result['out_dir']}")
        for w in result["warnings"]:
            print(f"  ! {w}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
