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
- ``blender_optimize(src, out_path, keep_ratio=0.5, cap=50000,
  max_texture_px=1024, ...) -> dict | None`` — one-click Quest
  optimizer engine (see blend_optimize.py, run inside Blender).
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
_OPTIMIZE = Path(__file__).with_name("blend_optimize.py")

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


def _parse_optimize_json(text: str) -> dict | None:
    """Parse an optimize report (raw JSON or a BLEND_OPTIMIZE_JSON: line)."""
    text = text.strip()
    if not text:
        return None
    marker = "BLEND_OPTIMIZE_JSON:"
    if marker in text:
        text = text[text.index(marker) + len(marker):].strip()
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def blender_optimize(
    src: Path | str,
    out_path: Path | str,
    keep_ratio: float = 0.5,
    cap: int = 50_000,
    max_texture_px: int = 1024,
    source_scale: float | None = None,
    min_triangles: int = 100,
    timeout: float = DEFAULT_TIMEOUT,
    cancel_event=None,
    snapshots: bool = False,
) -> dict | None:
    """Optimize one model with Blender headless (see blend_optimize.py).

    Returns the report dict from the bpy script — ``status`` is
    "optimized", "unchanged" (nothing to do; the caller copies the
    original instead), "skipped" (shape keys / armature / animation)
    or "failed" — or None when Blender could not run at all (see
    ``unavailable_reason()``). A cancelled run returns None with
    LAST_ERROR "cancelled by user" and no partial output file.

    The source file is never saved or modified; only ``out_path``
    (and its textures, with path_mode COPY) is written.
    """
    import time

    global LAST_ERROR
    LAST_ERROR = None
    blender = find_blender()
    if blender is None:
        LAST_ERROR = (
            "Blender not found — install Blender and make sure 'blender' "
            "is on PATH, or set BLENDER_PATH to the Blender binary."
        )
        return None
    src = Path(src)
    out_path = Path(out_path)
    if not src.is_file():
        LAST_ERROR = f"file not found: {src}"
        return None
    if not _OPTIMIZE.is_file():
        LAST_ERROR = f"optimize script missing: {_OPTIMIZE}"
        return None

    with tempfile.TemporaryDirectory(prefix="vault-optimize-") as tmp:
        tmp = Path(tmp)
        report_json = tmp / "optimize.json"
        snap_dir = tmp / "snaps"
        if snapshots:
            snap_dir.mkdir()
        cmd = [str(blender), "--background"]
        if src.suffix.lower() == ".blend":
            cmd.append(str(src))
        cmd += [
            "--python",
            str(_OPTIMIZE),
            "--",
            "--out",
            str(out_path),
            "--keep-ratio",
            str(keep_ratio),
            "--cap",
            str(cap),
            "--max-tex",
            str(max_texture_px),
            "--min-triangles",
            str(min_triangles),
            "--report",
            str(report_json),
        ]
        if src.suffix.lower() != ".blend":
            cmd += ["--input", str(src)]
        if source_scale is not None:
            cmd += ["--source-scale", str(source_scale)]
        if snapshots:
            cmd += ["--snapshots", str(snap_dir)]

        log_path = tmp / "blender.log"
        try:
            log_file = log_path.open("w", encoding="utf-8")
        except OSError as exc:
            LAST_ERROR = f"could not start Blender log: {exc}"
            return None
        try:
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        except OSError as exc:
            log_file.close()
            LAST_ERROR = f"could not start Blender ({blender}): {exc}"
            return None
        start = time.monotonic()
        rc = None
        while rc is None:
            rc = proc.poll()
            if rc is not None:
                break
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                log_file.close()
                LAST_ERROR = "cancelled by user"
                return None
            if time.monotonic() - start > timeout:
                proc.kill()
                proc.wait()
                log_file.close()
                LAST_ERROR = (
                    f"Blender timed out after {timeout:.0f}s while optimizing "
                    f"{src.name} — file skipped."
                )
                return None
            time.sleep(0.2)
        log_file.close()

        data = None
        if report_json.is_file():
            data = _parse_optimize_json(report_json.read_text(encoding="utf-8"))
        if data is None:
            try:
                data = _parse_optimize_json(log_path.read_text(encoding="utf-8"))
            except OSError:
                data = None
        if data is None:
            LAST_ERROR = (
                f"Blender ran but produced no usable report for "
                f"{src.name} (exit {rc}) — see the Blender log."
            )
            return None
        if data.get("error"):
            LAST_ERROR = f"Blender optimize failed for {src.name}: {data['error']}"
            return None
        if data.get("status") == "failed":
            LAST_ERROR = (
                f"Blender optimize failed for {src.name}: "
                f"{data.get('error') or data.get('reason') or 'unknown error'}"
            )
            return None

        # Thumbnail diff from the before/after OBJ snapshots: the same
        # 3/4 view the Vault renders for every other format, so the
        # optimizer can flag a changed silhouette on the Blender path
        # too. Advisory only — a missing snapshot never fails the run.
        if snapshots:
            before_obj = snap_dir / "before.obj"
            after_obj = snap_dir / "after.obj"
            if before_obj.is_file() and after_obj.is_file():
                try:
                    from .preview import mesh_geometry, png_diff_fraction, render_png

                    g0 = mesh_geometry(before_obj)
                    g1 = mesh_geometry(after_obj)
                    if g0 is not None and g1 is not None:
                        diff = png_diff_fraction(
                            render_png(g0[0], g0[1], size=96),
                            render_png(g1[0], g1[1], size=96),
                        )
                        if diff is not None:
                            data["thumbnail_diff"] = diff
                except Exception:
                    pass
        return data


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print("blender:", find_blender() or "NOT FOUND")
    if target is not None:
        print("stats:", blend_stats(target))
        if len(sys.argv) > 2:
            print("thumbnail:", blend_thumbnail(target, sys.argv[2]))
        print("error:", unavailable_reason())
