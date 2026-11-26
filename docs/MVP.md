# MVP spec — VRChat Asset Vault v0.1

Source: demand research 2026-11-13 (Blender Artists, VRChat Creators docs,
VRCLibrary, Hoard, Assets Manager for VRChat, LocalFab, Oddments,
AssetHoard, LIBRO/BKeeper, VRWorldToolkit). No quantitative survey was
found; evidence is qualitative and documented in the research notes.

## VRChat budgets the program must know

- World total: ~250,000 triangles recommended (not a hard upload cap).
- Textures: aim for 1024×1024 maximum; larger textures are the main
  cause of high memory use, especially on Quest.
- Android / Quest world: 100 MB maximum after build-time compression.
- Materials: each extra material is an extra submesh / draw call.
- Show PC and Quest separately. PC is more forgiving (~500k–1M tris
  workable in community guides); Quest is where 250k rules.

## P0 — must have in v0.1

1. **Index without moving.** Recursive scan of FBX/OBJ/GLB/.blend +
   textures. SQLite index. Cached thumbnails. Source files untouched.
2. **Search + tags.** Instant text search, multi-category tags, filters:
   format, source/store, favorite.
3. **VRChat card.** Per asset: triangles, mesh count, material count,
   max texture resolution, disk size, % of world budget. Traffic light
   PC / Quest.
4. **Clean Unity export.** Copy FBX + referenced textures to
   `Export_<World>/`, repair relative paths where possible, write
   `manifest.json` (origin, author, URL, license per file). Warn on:
   OBJ without .mtl, missing texture, FBX not binary or < 7.1.
   Never import `.blend` directly into Unity — export FBX first.
5. **Origin + license + credits.** Fields: store, author, URL, license
   (CC0 / Royalty-Free / Personal / Commercial / NC), notes. Export a
   credits list. This matters because Booth/Gumroad terms typically
   forbid reselling / redistributing the asset files as standalone.

## P1 — right after P0

6. **Collections per world** with summed tris / materials / size,
   export the whole set at once.
7. **Duplicates + broken files.** Same content hash in different
   folders; referenced texture that doesn't exist on disk.
8. **Open in Blender / Explorer / copy path.** Coexist with Blender's
   native library and with VRWorldToolkit (which checks *inside*
   Unity, after the world is built — we check *before* choosing).

## Not in v1 (decided, with reason)

- Store sync (Booth/Gumroad/Jinxxy login + scraping): Hoard does it
  free and open source; fragile against store changes.
- Texture atlasing / LODs / avatars in the optimizer: atlasing
  rewrites UVs (high risk, low v1 value), LODs are a second feature,
  and avatars (rigged / blendshaped meshes) must never be decimated
  by an automatic tool — the optimizer refuses them with a reason.
- Full PBR viewer, AI search, cloud/collaboration, model store:
  scope and cost explode; a simple orbit/wireframe thumbnail is enough.
- Bundled models: never, for licensing reasons.

Decimation used to be on this list ("Blender Decimate, CATS and
VRWorldToolkit already do it; bad decimation destroys a model").
It landed in v0.4 (below) because the gap the research found was
real — free, open source, local-first, *before* import, at the
library level — and the risk is contained by the verification gate
(copy-only originals, triangle/texture/bbox/silhouette checks,
fail-safe copy on any failed check).

## v0.2 (2026-11-13) — P0 gaps closed

Research (docs/research-needs-vrchat-2026-11-13.md) confirmed the
P0 list was right and found the card was half-empty in practice:
texture size and materials always showed "?", and there were no
thumbnails at all. v0.2 closes those gaps: real thumbnails
(`preview.py`), texture dimensions + material counts in the card,
stale-file pruning on rescan, `.unitypackage` export, `CREDITS.md`
in every export, and a real FBX version check. 36 tests, GUI
verified offscreen with a screenshot.

## v0.3 (2026-11-13) — the four things v0.2 left open, all closed

- **Texture-memory totals per collection** (`budget.texture_totals_for`
  + `database.collection_texture_totals`): how close a world is to the
  100 MB Quest limit and which assets are the worst offenders. The
  budget bar and the `budget` CLI command show both.
- **FBX UnitScaleFactor detection** (`scanner.fbx_unit_scale_factor`):
  reads the scale from the binary GlobalSettings node and warns for
  Blender's 0.01 default in the card and in export warnings.
- **Multi-select in the GUI**: Ctrl+click / Shift+click, combined
  totals in the detail panel, export of exactly the selection
  (folder or `.unitypackage`).
- **`.blend` stats + thumbnails via Blender headless** (`blend.py` +
  `blend_probe.py`, Blender 4.2 LTS verified on Linux): real
  triangles/materials/textures and a rendered thumbnail per `.blend`,
  same cache as the other formats; graceful "Blender not found"
  when Blender is missing — never guessed numbers.

69 tests (36 v0.2 + 33 v0.3), GUI verified offscreen with
screenshots (multi-select, FBX scale, real `.blend` card).

Still open (not in v0.3): `.blend` end-to-end test on Windows
(verified on Linux only — same code paths, but PATH lookup differs);
scan speed with many `.blend` files (one Blender start each — a
background worker is the fix, not in scope); full-scene validation
(draw calls, 45 FPS) stays with the VRChat SDK / VRWorldToolkit,
as the research warned the Vault must not promise it.

## v0.4 (2026-11-26) — One-click Quest optimizer

The most-demanded next feature, verified 2026-11-25 against VRChat
docs (Quest content is a challenge; the 100 MB world cap and large
textures are the main culprits) and paid tools proving demand
(Polytool 2, $25, 456 ratings; Synthos Scene Optimizer). The gap:
free, open source, local-first, *before* import, at the library
level — the paid tools live inside Unity, after the world is built.

- **Presets** (`budget.py`): Gentle 75% / 1024px / 100k cap,
  Balanced 50% / 1024px / 50k cap (default), Aggressive 25% /
  512px / 20k cap, Custom. A mesh under 100 triangles is never
  decimated (a 12-triangle cube is not "optimized" to 6).
- **Engines** (`optimizer.py` + `blend_optimize.py`): Blender
  headless (bpy Decimate COLLAPSE only, never remesh) is the only
  FBX round-trip — trimesh cannot read or write FBX at all — and
  handles FBX/OBJ/GLB/`.blend`; trimesh + fast-simplification is the
  fallback for OBJ/GLB/GLTF only, with a nearest-vertex UV remap
  (trimesh's wrapper drops UVs). Pillow downscales textures
  (PNG/JPG/BMP/TGA; EXR/HDR/DDS are copied + warned).
- **Scale fix**: old Blender 0.01 FBX files are imported with
  `global_scale = 1/0.01` (restores the authored size) and
  re-exported with FBX_SCALE_ALL + bake_space_transform, so the
  output carries the metre-to-centimetre factor (100.0 for a metre
  scene) with node scale 1 — never a byte-patch of
  `UnitScaleFactor`.
- **Safety** (plan §2): originals are never modified (copies under
  `Optimized_<World>/`, verified by hash in tests); every output
  passes a verification gate (triangles within ±5% of target,
  texture size, bounding box within 1%, silhouette diff) and any
  failed check falls back to an untouched copy; shape keys /
  armatures / animations are skipped with a reason; favourites are
  protected (Aggressive skips, Balanced warns); optimized copies
  are NOT indexed in the DB; `CREDITS.md` travels with outputs and
  optimized copies inherit the original license.
- **CLI + GUI**: `optimize` subcommand and the GUI flow in
  `docs/GUI.md` share the same engine (`optimize_collection`).
  114 tests (69 + 45 new: 30 core, 10 Blender-path, 5 GUI),
  full suite green, including the GUI offscreen.

Still open (not in v0.4): the Blender path is verified end-to-end
on Linux (Blender 4.2.0) only — the exact Windows check is in the
v0.4 report (`optimize` on a real collection after `git pull` on
Windows, Blender on PATH); `.blend` end-to-end on Windows (same
caveat as v0.3); texture atlasing, LODs and avatars stay out of v1
by decision (above).

## Decisions still open for Mochi

- GUI first screen: grid of thumbnails vs list with VRChat card?
- Thumbnail source for FBX/OBJ in v0.1: render with trimesh +
  matplotlib (no Blender needed) vs Blender headless (slower, prettier)?
  Opinion: trimesh first, Blender headless only for `.blend`.
- Name: `vrchat-asset-vault` is the working name; rename is cheap
  before the first public release.
- Repo: public under `guardianseikonohikari-ship-it`, MIT.
  Blocked 2026-11-13: cloud browser session is JeanPontigo, not
  ship-it. Mochi must switch the session (or take the browser) before
  the repo can be created there. Local scaffold lives in
  `~/workspace/vrchat-asset-vault/` until then.
