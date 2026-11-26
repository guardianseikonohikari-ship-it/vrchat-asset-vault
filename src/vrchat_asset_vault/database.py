"""Local SQLite index. No account, no cloud, no telemetry.

The index only stores metadata + paths + hashes. Source files are
never moved, copied or modified by indexing.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    triangles INTEGER,
    materials INTEGER,
    scale_factor REAL,
    max_texture_px INTEGER,
    texture_count INTEGER DEFAULT 0,
    texture_bytes INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    author TEXT DEFAULT '',
    url TEXT DEFAULT '',
    license TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    favorite INTEGER DEFAULT 0,
    collection TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_assets_sha ON assets(sha256);
CREATE INDEX IF NOT EXISTS idx_assets_collection ON assets(collection);
"""

# Columns added after v0.1 — old vault.db files gain them on first open.
_MIGRATIONS = {
    "materials": "ALTER TABLE assets ADD COLUMN materials INTEGER",
    "scale_factor": "ALTER TABLE assets ADD COLUMN scale_factor REAL",
    "max_texture_px": "ALTER TABLE assets ADD COLUMN max_texture_px INTEGER",
    "texture_count": "ALTER TABLE assets ADD COLUMN texture_count INTEGER DEFAULT 0",
    "texture_bytes": "ALTER TABLE assets ADD COLUMN texture_bytes INTEGER DEFAULT 0",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(assets)")}
    for column, sql in _MIGRATIONS.items():
        if column not in existing:
            conn.execute(sql)
    conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def upsert_asset(conn: sqlite3.Connection, asset) -> None:
    conn.execute(
        """
        INSERT INTO assets (path, filename, format, size_bytes, sha256,
            triangles, materials, scale_factor, max_texture_px, texture_count, texture_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            sha256=excluded.sha256,
            triangles=excluded.triangles,
            materials=excluded.materials,
            scale_factor=excluded.scale_factor,
            max_texture_px=excluded.max_texture_px,
            texture_count=excluded.texture_count,
            texture_bytes=excluded.texture_bytes
        """,
        (
            str(asset.path),
            asset.path.name,
            asset.path.suffix.lower().lstrip("."),
            asset.size_bytes,
            asset.sha256,
            asset.triangles,
            getattr(asset, "materials", None),
            getattr(asset, "scale_factor", None),
            getattr(asset, "max_texture_px", None),
            getattr(asset, "texture_count", 0),
            getattr(asset, "texture_bytes", 0),
        ),
    )
    conn.commit()


META_FIELDS = ("source", "author", "url", "license", "tags", "favorite", "collection")


def update_asset_meta(conn: sqlite3.Connection, path: str, **fields) -> None:
    """Save the user's own notes for an asset (tags, origin, favorite...)."""
    sets = []
    values: list = []
    for key, value in fields.items():
        if key not in META_FIELDS:
            raise ValueError(f"unknown metadata field: {key}")
        sets.append(f"{key}=?")
        values.append(value)
    if not sets:
        return
    values.append(path)
    conn.execute(f"UPDATE assets SET {', '.join(sets)} WHERE path=?", values)
    conn.commit()


def load_meta(conn: sqlite3.Connection, path: str) -> dict:
    """The saved metadata for one asset (empty strings when never edited)."""
    row = conn.execute(
        "SELECT source, author, url, license, tags, favorite, collection "
        "FROM assets WHERE path=?",
        (path,),
    ).fetchone()
    if row is None:
        return {k: "" for k in META_FIELDS}
    return dict(zip(META_FIELDS, row))


def delete_asset(conn: sqlite3.Connection, path: str) -> None:
    """Remove an asset from the index only — the file on disk is untouched."""
    conn.execute("DELETE FROM assets WHERE path=?", (path,))
    conn.commit()


def prune_missing(conn: sqlite3.Connection, existing_paths) -> int:
    """Drop index rows whose file no longer exists on disk.

    A scan only ever upserts, so without this a deleted or moved file
    would haunt the library forever. Returns how many rows were removed.
    """
    existing = set(existing_paths)
    rows = conn.execute("SELECT path FROM assets").fetchall()
    removed = 0
    for (path,) in rows:
        if path not in existing:
            conn.execute("DELETE FROM assets WHERE path=?", (path,))
            removed += 1
    if removed:
        conn.commit()
    return removed


def find_duplicates(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(sha256, count) for files stored twice under different paths."""
    return conn.execute(
        "SELECT sha256, COUNT(*) c FROM assets GROUP BY sha256 HAVING c > 1"
    ).fetchall()


def list_assets(conn: sqlite3.Connection, collection: str | None = None):
    if collection:
        return conn.execute(
            "SELECT path, triangles, size_bytes, texture_bytes FROM assets "
            "WHERE collection = ?",
            (collection,),
        ).fetchall()
    return conn.execute(
        "SELECT path, triangles, size_bytes, texture_bytes FROM assets"
    ).fetchall()


def collection_texture_totals(
    conn: sqlite3.Connection, collection: str | None = None, top_n: int = 5
) -> dict:
    """Texture-memory totals for a collection (or the whole library).

    VRChat's 100 MB Quest limit is usually blown by textures, not by
    the models themselves — this is the number that tells the creator
    which assets to shrink first. "heaviest" lists the worst offenders
    by texture bytes, biggest first.
    """
    rows = list_assets(conn, collection)
    total_tex = sum(r[3] or 0 for r in rows)
    total_size = sum(r[2] or 0 for r in rows)
    total_tris = sum(r[1] or 0 for r in rows)
    heaviest = sorted(rows, key=lambda r: r[3] or 0, reverse=True)[:top_n]
    return {
        "assets": len(rows),
        "triangles": total_tris,
        "texture_bytes": total_tex,
        "model_bytes": total_size,
        "heaviest": [
            {"path": r[0], "texture_bytes": r[3] or 0}
            for r in heaviest
            if (r[3] or 0) > 0
        ],
    }
