# VRChat Asset Vault

Free, local-first 3D asset library for VRChat world creators.

Organize the FBX / OBJ / GLB / `.blend` models you already own, preview
them without opening Blender, and know **before** importing whether a prop
fits your world's VRChat budget — then export a clean folder ready for Unity.

> **No models are included.** This program ships empty. You point it at
> your own folders. Every model keeps its own author, source and license,
> and nothing is uploaded anywhere.

## Why this exists

- Blender's Asset Browser was built for assets already marked inside
  `.blend` files, one by one. Creators with hundreds of loose FBX/OBJ
  files in nested folders can't catalog them that way.
- BlenderKit is Blender-only, needs an account, and its full library is
  a subscription. It doesn't check VRChat budgets or export to Unity.
- LocalFab does the local-library part, but it's Mac-only and paid.
  Oddments / AssetHoard are great general libraries, but they don't know
  VRChat limits.
- A pretty prop can break a world. VRChat recommends ~250,000 triangles
  per world in total, textures at most 1024×1024, and 100 MB after build
  compression on Android / Quest. This tool shows that per asset, for
  PC and Quest separately, before you build.

## What's new in v0.3 (2026-11-13)

- **Texture-memory totals per collection.** The budget bar now shows
  how much of the 100 MB Quest limit your textures eat, with a green /
  amber / red dot — and names the heaviest assets ("Heaviest textures:
  shelf.fbx 8.1 MB"), so you know what to shrink first. Same totals
  in `budget` on the CLI.
- **FBX scale detection.** The scanner reads `UnitScaleFactor` from
  the binary FBX and flags Blender's 0.01 default in the detail panel
  and in export warnings, before the model imports 100x too small in
  Unity.
- **Multi-select.** Ctrl+click / Shift+click several cards: the detail
  panel shows their combined triangles, texture memory and materials,
  and Export / Export .unitypackage export exactly the selection.
- **`.blend` stats + thumbnails via Blender headless.** When Blender
  is installed, `.blend` files get real triangle/material/texture
  stats and a rendered thumbnail (same 3/4 view as the other formats,
  same cache). When Blender is missing, the card says so honestly
  instead of guessing — install Blender and rescan.
- **Caveat:** scanning a folder with many `.blend` files costs one
  Blender start per file (~1-2 s each). Thumbnails are cached, so a
  rescan only re-runs Blender for new or changed files.

## What's new in v0.2 (2026-11-13)

- **Real thumbnails.** Cards and the detail panel show a rendered
  3/4 view of each model (pure-stdlib rasterizer, no new dependency),
  cached by content hash. `.blend` had no preview yet — fixed in v0.3
  (above).
- **The VRChat card is complete now.** Materials are counted (OBJ
  `usemtl`, FBX/GLB via trimesh) and texture sizes are read from the
  file headers (PNG/JPEG/BMP/TGA, no Pillow) — the 1024px warning
  actually fires now instead of showing "?".
- **Stale files leave the library.** A rescan drops index rows whose
  file no longer exists on disk, and says how many it removed.
- **Export as `.unitypackage`.** One file Unity opens on
  double-click, with a stable `.meta` GUID per file, plus
  `CREDITS.md` in every export (folder or package).
- **FBX version is really checked.** The exporter reads the version
  from the binary header and warns below 7.1, instead of only
  checking that the file is binary.

## MVP (v0.1)

1. Index folders recursively without moving anything — SQLite index,
   cached thumbnails, files stay where they are.
2. Instant search + multi-category tags (a model can be furniture,
   wood *and* library at once) + filters by format, source and favorite.
3. VRChat card per asset: triangles, meshes/materials, max texture
   resolution, disk size, and a PC / Quest traffic light.
4. Clean export to Unity: FBX + textures together in
   `Export_<WorldName>/`, a `manifest.json` with origin and license per
   file, and warnings for a missing `.mtl`/texture or a non-binary /
   old FBX.
5. Origin + license per asset (Poly Haven / Sketchfab / Booth / Gumroad /
   Jinxxy / own work), author, URL, and an exportable credits list.
6. Collections / sets per world, with summed budget.
7. Duplicate and broken-file detection (same hash, missing texture).
8. Open in Blender / show in Explorer / copy path — no reinventing Blender.

Explicitly **not** in v1: syncing purchases with Booth/Gumroad
(Hoard already does that, free), mesh decimation / texture atlasing
(Blender, CATS and VRWorldToolkit already do that — v1 only *warns*),
a full PBR 3D viewer, AI search, cloud, or a model store.

## Install (Windows)

**Easiest — just double-click:** download `VRChat Asset Vault.exe`
from the latest GitHub Release and double-click it. No Python, no
commands, no account.

**From the folder:** clone the repo, then double-click `run.bat`.
It installs the app the first time (needs Python 3.11+ from
python.org) and then opens the window. No commands needed.

**From a terminal, if you prefer:**

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .[gui]
python -m vrchat_asset_vault gui
```

No account, no subscription, no telemetry. The `.exe` is built by
GitHub Actions (`.github/workflows/build-windows.yml`) on every
release tag — see `vrchat-asset-vault.spec`.

## Use

```bat
python -m vrchat_asset_vault scan "D:\VRChat Assets" --db vault.db
python -m vrchat_asset_vault budget vault.db --world "Biblioteca Prohibida"
python -m vrchat_asset_vault export vault.db --collection "Biblioteca Prohibida" --out "D:\Exports\Biblioteca"
```

Or open the graphical interface (needs the `[gui]` extra):

```bat
python -m vrchat_asset_vault gui
```

The GUI (PySide6, `src/vrchat_asset_vault/gui.py`) calls the same
scanner, budget checker and exporter as this CLI, so the two can
never disagree about a triangle count.

## Tech

Python 3.11+, PySide6 (GUI, next), SQLite (local index), `trimesh`
when available for triangle counts, Blender headless for `.blend`
stats + thumbnails (when installed; graceful fallback when not).
MIT license.
