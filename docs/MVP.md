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
- Decimation / optimization inside the app: Blender Decimate, CATS
  and VRWorldToolkit already do it; bad decimation destroys a model.
- Full PBR viewer, AI search, cloud/collaboration, model store:
  scope and cost explode; a simple orbit/wireframe thumbnail is enough.
- Bundled models: never, for licensing reasons.

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
