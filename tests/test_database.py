import sqlite3
from pathlib import Path

from vrchat_asset_vault.database import (
    collection_texture_totals,
    connect,
    delete_asset,
    list_assets,
    load_meta,
    prune_missing,
    update_asset_meta,
    upsert_asset,
)
from vrchat_asset_vault.scanner import FoundAsset


def _asset(path, **kw):
    defaults = dict(
        size_bytes=100, sha256="a" * 64, triangles=12, materials=2,
        max_texture_px=1024, texture_count=1, texture_bytes=5000,
    )
    defaults.update(kw)
    return FoundAsset(path=path, **defaults)


def test_upsert_stores_new_stat_fields(tmp_path):
    conn = connect(tmp_path / "vault.db")
    asset = _asset(tmp_path / "cube.obj")
    upsert_asset(conn, asset)
    row = conn.execute(
        "SELECT triangles, materials, max_texture_px, texture_count, "
        "texture_bytes FROM assets WHERE path=?",
        (str(tmp_path / "cube.obj"),),
    ).fetchone()
    assert row == (12, 2, 1024, 1, 5000)
    conn.close()


def test_upsert_stores_scale_factor(tmp_path):
    conn = connect(tmp_path / "vault.db")
    upsert_asset(conn, _asset(tmp_path / "shelf.fbx", scale_factor=0.01))
    row = conn.execute(
        "SELECT scale_factor FROM assets WHERE path=?",
        (str(tmp_path / "shelf.fbx"),),
    ).fetchone()
    assert row == (0.01,)
    conn.close()


def test_migration_adds_columns_to_v01_database(tmp_path):
    # A vault.db created by v0.1 has no materials/texture columns.
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE assets (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,"
        " filename TEXT NOT NULL, format TEXT NOT NULL, size_bytes INTEGER NOT NULL,"
        " sha256 TEXT NOT NULL, triangles INTEGER, source TEXT DEFAULT '',"
        " author TEXT DEFAULT '', url TEXT DEFAULT '', license TEXT DEFAULT '',"
        " tags TEXT DEFAULT '', favorite INTEGER DEFAULT 0, collection TEXT DEFAULT '')"
    )
    conn.execute(
        "INSERT INTO assets (path, filename, format, size_bytes, sha256, triangles)"
        " VALUES ('/x/cube.obj', 'cube.obj', 'obj', 100, 'abc', 12)"
    )
    conn.commit()
    conn.close()
    conn = connect(db)  # must migrate, not crash
    cols = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
    assert {"materials", "scale_factor", "max_texture_px", "texture_count", "texture_bytes"} <= cols
    row = conn.execute(
        "SELECT triangles, materials FROM assets WHERE path='/x/cube.obj'"
    ).fetchone()
    assert row == (12, None)  # old data kept, new fields empty
    # And the migrated DB accepts the new upsert immediately.
    upsert_asset(conn, _asset(Path("/x/cube.obj")))
    conn.close()


def test_prune_missing_removes_only_gone_files(tmp_path):
    conn = connect(tmp_path / "vault.db")
    keep = tmp_path / "keep.obj"
    gone = tmp_path / "gone.obj"
    keep.write_text("v 0 0 0\n", encoding="utf-8")
    upsert_asset(conn, _asset(keep))
    upsert_asset(conn, _asset(gone))
    assert len(list_assets(conn)) == 2
    removed = prune_missing(conn, {str(keep)})
    assert removed == 1
    assert [r[0] for r in list_assets(conn)] == [str(keep)]
    # Pruning again with everything present removes nothing.
    assert prune_missing(conn, {str(keep)}) == 0
    conn.close()


def test_meta_roundtrip_and_delete(tmp_path):
    conn = connect(tmp_path / "vault.db")
    path = str(tmp_path / "cube.obj")
    upsert_asset(conn, _asset(tmp_path / "cube.obj"))
    update_asset_meta(conn, path, source="Poly Haven", license="CC0", favorite=1)
    meta = load_meta(conn, path)
    assert meta["source"] == "Poly Haven"
    assert meta["license"] == "CC0"
    assert meta["favorite"] == 1
    delete_asset(conn, path)
    assert list_assets(conn) == []
    conn.close()


def test_collection_texture_totals_names_heaviest(tmp_path):
    conn = connect(tmp_path / "vault.db")
    upsert_asset(conn, _asset(tmp_path / "shelf.fbx", texture_bytes=8_000_000))
    upsert_asset(conn, _asset(tmp_path / "books.obj", texture_bytes=3_000_000))
    upsert_asset(conn, _asset(tmp_path / "candle.obj", texture_bytes=0))
    update_asset_meta(conn, str(tmp_path / "shelf.fbx"), collection="Library")
    update_asset_meta(conn, str(tmp_path / "books.obj"), collection="Library")
    totals = collection_texture_totals(conn, "Library")
    assert totals["assets"] == 2
    assert totals["texture_bytes"] == 11_000_000
    assert [h["path"] for h in totals["heaviest"]] == [
        str(tmp_path / "shelf.fbx"),
        str(tmp_path / "books.obj"),
    ]
    # The whole library includes the unassigned candle too.
    all_totals = collection_texture_totals(conn)
    assert all_totals["assets"] == 3
    assert all_totals["texture_bytes"] == 11_000_000
    conn.close()
