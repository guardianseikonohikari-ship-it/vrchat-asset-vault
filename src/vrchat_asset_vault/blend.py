"""Stats + thumbnails for .blend files via Blender headless.

The Vault never guesses at .blend contents: when Blender is
available this module runs it in the background (``blender
--background <file> --python blend_probe.py``) and reads back the
JSON the probe writes. When Blender is missing, slow, or fails, every
function returns None and records a human-readable reason in
``LAST_ERROR`` — the GUI must never hang or crash over a .blend.

Blender lookup order (first hit wins):
1. ``BLENDER_PATH`` environment variable (a Blender binary or the
   folder containing one).
2. ``blender`` on PATH (``shutil.which``).
3. The usual install locations (Windows ``Program Files``,
   macOS ``/Applications/Blender.app``, Linux ``/usr/bin`` and
   ``/usr/local/bin``).
4. ``<repo>/.tools/blender/`` — the dev fallback used on this VM
   only; it is NOT part of the shipped app and is never bundled
   by PyInstaller.

Public API (integration points — see the report for the call sites):
- ``blender_available() -> bool``
- ``find_blender() -> Path | None``
- ``blend_stats(path, timeout=120) -> dict | None``
- ``blend_thumbnail(path, cache_dir, size=192, timeout=180) -> Path | None``
- ``unavailable_reason() -> str | None`` (why the last call returned None)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# A .blend probe is one Blender start-up + one file open; 120 s is
# generous for any sane asset and still bounds a hung GUI call.
DEFAULT_TIMEOUT = 120
THUMBNAIL_TIMEOUT = 180

#: Human-readable reason the most recent call returned None.
#: Empty (None) when the last call succeeded.
LAST_ERROR: str | None = None

_PROBE = Path(__file__).with_name("blend_probe.py")

# Typical Blender install locations, checked after PATH.
_CANDIDATE_DIRS = [
    # Windows
    Path(r"C:\Program Files\Blender Foundation"),
    Path(r"C:\Program Files (x86)\Blender Foundation"),
    # macOS
    Path("/Applications/Blender.app/Contents/MacOS"),
    # Linux
    Path("/usr/bin"),
    Path("/usr/local/bin"),
    Path("/opt/blender"),
]


def _repo_root() -> Path:
    # blend.py lives at <repo>/src/vrchat_asset_vault/blend.py
    return Path(__file__).resolve().parents[2]


def _dev_tools_blender() -> Path | None:
    """<repo>/.tools/blender/<build>/blender[.exe] — dev-only fallback.

    This is how the Linux VM used for development finds the Blender
    downloaded into .tools/; end users on Windows get Blender from
    PATH or Program Files instead. Never bundled, never required.
    """
    tools = _repo_root() / ".tools" / "blender"
    if not tools.is_dir():
        return None
    names = ("blender.exe", "blender") if os.name == "nt" else ("blender",)
    candidates = sorted(tools.glob("blender-*/blender")) + sorted(
        tools.glob("blender-*/blender.exe")
    )
    for cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    for name in names:
        direct = tools / name
        if direct.is_file() and os.access(direct, os.X_OK):
            return direct
    return None


def find_blender() -> Path | None:
    """Locate a Blender binary, or None when there is none to use."""
    env = os.environ.get("BLENDER_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        exe = p / ("blender.exe" if os.name == "nt" else "blender")
        if exe.is_file():
            return exe
    which = shutil.which("blender")
    if which:
        return Path(which)
    exe_name = "blender.exe" if os.name == "nt" else "blender"
    for base in _CANDIDATE_DIRS:
        if not base.is_dir():
            continue
        direct = base / exe_name
        if direct.is_file():
            return direct
        # Windows: "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
        for sub in sorted(base.glob("Blender *")):
            cand = sub / exe_name
            if cand.is_file():
                return cand
    return _dev_tools_blender()


def blender_available() -> bool:
    """True when a Blender binary can be found (not yet run)."""
    return find_blender() is not None


def unavailable_reason() -> str | None:
    """Why the last blend_stats/blend_thumbnail call returned None."""
    return LAST_ERROR


def parse_probe_json(text: str) -> dict | None:
    """Parse probe JSON (raw text or a ``BLEND_PROBE_JSON:`` stdout line).

    Returns the stats dict, or None when the text is not usable probe
    output. A probe dict carrying an ``"error"`` key is returned
    as-is so the caller can surface the probe's own message.
    """
    text = text.strip()
    if not text:
        return None
    marker = "BLEND_PROBE_JSON:"
    if marker in text:
        text = text[text.index(marker) + len(marker):].strip()
    try:
        # raw_decode: the JSON object, ignoring any Blender chatter
        # printed after it on the same stream.
        data, _ = json.JSONDecoder().raw_decode(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _run_probe(blend_path: Path, timeout: float, obj_path: Path | None = None) -> dict | None:
    """Run Blender headless + blend_probe.py; return the probe dict or None.

    Sets LAST_ERROR on every failure path. Never raises for a missing
    binary, a timeout, a bad exit code, or unparsable output.
    """
    global LAST_ERROR
    LAST_ERROR = None
    blender = find_blender()
    if blender is None:
        LAST_ERROR = (
            "Blender not found — install Blender and make sure 'blender' "
            "is on PATH, or set BLENDER_PATH to the Blender binary."
        )
        return None
    if not blend_path.is_file():
        LAST_ERROR = f"file not found: {blend_path}"
        return None
    if not _PROBE.is_file():
        LAST_ERROR = f"probe script missing: {_PROBE}"
        return None

    with tempfile.TemporaryDirectory(prefix="vault-blend-") as tmp:
        out_json = Path(tmp) / "probe.json"
        cmd = [
            str(blender),
            "--background",
            str(blend_path),
            "--python",
            str(_PROBE),
            "--",
            str(out_json),
        ]
        if obj_path is not None:
            cmd += ["--obj", str(obj_path)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                # Blender prints a lot; keep it out of the user's console.
            )
        except subprocess.TimeoutExpired:
            LAST_ERROR = (
                f"Blender timed out after {timeout:.0f}s while reading "
                f"{blend_path.name} — file skipped, try opening it in Blender."
            )
            return None
        except OSError as exc:
            LAST_ERROR = f"could not start Blender ({blender}): {exc}"
            return None

        data = None
        if out_json.is_file():
            data = parse_probe_json(out_json.read_text(encoding="utf-8"))
        if data is None:
            data = parse_probe_json(proc.stdout or "")
        if data is None:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = detail[-1] if detail else "no output"
            LAST_ERROR = (
                f"Blender ran but produced no usable stats for "
                f"{blend_path.name} (exit {proc.returncode}): {tail}"
            )
            return None
        if data.get("error"):
            LAST_ERROR = f"Blender probe failed for {blend_path.name}: {data['error']}"
            return None
        return data


def blend_stats(path: Path | str, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """Triangles/materials/textures of a .blend, via Blender headless.

    Returns ``{"triangles", "materials", "max_texture_px",
    "texture_count", "texture_bytes", "warnings"}`` or None when the
    stats could not be produced — see ``unavailable_reason()``.
    """
    global LAST_ERROR
    data = _run_probe(Path(path), timeout=timeout)
    if data is None or data.get("error"):
        if data and data.get("error"):
            LAST_ERROR = f"Blender probe failed for {Path(path).name}: {data['error']}"
        return None
    return {
        "triangles": int(data.get("triangles") or 0),
        "materials": int(data.get("materials") or 0),
        "max_texture_px": int(data.get("max_texture_px") or 0),
        "texture_count": int(data.get("texture_count") or 0),
        "texture_bytes": int(data.get("texture_bytes") or 0),
        "warnings": list(data.get("warnings") or []),
    }


def blend_thumbnail(
    path: Path | str,
    cache_dir: Path | str,
    size: int = 192,
    timeout: float = THUMBNAIL_TIMEOUT,
) -> Path | None:
    """Cached PNG thumbnail for a .blend, same cache as preview.py.

    The file name is ``<sha256 of the .blend>.png`` inside ``cache_dir``
    — identical to ``preview.thumbnail_for`` — so a .blend thumbnail
    and an OBJ/GLB thumbnail for the same content share one cache
    entry and a rescan never re-renders an unchanged file.

    How it renders: Blender exports the mesh objects to a temporary
    OBJ (one headless run, stats included), and the Vault's own
    pure-Python rasterizer (``preview.render_png``) draws the same
    flat-shaded 3/4 view as every other format. No Blender render
    engine, no Eevee/Cycles set-up, no extra dependency.
    """
    global LAST_ERROR
    path = Path(path)
    cache_dir = Path(cache_dir)
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        LAST_ERROR = f"could not read {path.name}: {exc}"
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{digest}.png"
    if out.exists():
        LAST_ERROR = None
        return out

    with tempfile.TemporaryDirectory(prefix="vault-blend-thumb-") as tmp:
        obj_path = Path(tmp) / "mesh.obj"
        data = _run_probe(path, timeout=timeout, obj_path=obj_path)
        if data is None:
            return None  # LAST_ERROR already set by _run_probe
        if not obj_path.is_file():
            LAST_ERROR = (
                f"Blender opened {path.name} but exported no geometry — "
                "the file may contain no mesh objects."
            )
            return None
        from .preview import mesh_geometry, render_png

        geom = mesh_geometry(obj_path)
        if geom is None:
            LAST_ERROR = (
                f"Blender exported {path.name} but the exported mesh "
                "could not be read back."
            )
            return None
        verts, faces = geom
        try:
            out.write_bytes(render_png(verts, faces, size=size))
        except Exception as exc:
            LAST_ERROR = f"could not render thumbnail for {path.name}: {exc}"
            return None
    LAST_ERROR = None
    return out


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print("blender:", find_blender() or "NOT FOUND")
    if target is not None:
        print("stats:", blend_stats(target))
        if len(sys.argv) > 2:
            print("thumbnail:", blend_thumbnail(target, sys.argv[2]))
        print("error:", unavailable_reason())
