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


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_asset(conn: sqlite3.Connection, asset) -> None:
    conn.execute(
        """
        INSERT INTO assets (path, filename, format, size_bytes, sha256, triangles)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            size_bytes=excluded.size_bytes,
            sha256=excluded.sha256,
            triangles=excluded.triangles
        """,
        (
            str(asset.path),
            asset.path.name,
            asset.path.suffix.lower().lstrip("."),
            asset.size_bytes,
            asset.sha256,
            asset.triangles,
        ),
    )
    conn.commit()


def find_duplicates(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(sha256, count) for files stored twice under different paths."""
    return conn.execute(
        "SELECT sha256, COUNT(*) c FROM assets GROUP BY sha256 HAVING c > 1"
    ).fetchall()


def list_assets(conn: sqlite3.Connection, collection: str | None = None):
    if collection:
        return conn.execute(
            "SELECT path, triangles, size_bytes FROM assets WHERE collection = ?",
            (collection,),
        ).fetchall()
    return conn.execute("SELECT path, triangles, size_bytes FROM assets").fetchall()
