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

## Install (Windows, from source for now)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m vrchat_asset_vault --help
```

A PyInstaller `.exe` for GitHub Releases is planned — no account,
no subscription, no telemetry.

## Use

```bat
python -m vrchat_asset_vault scan "D:\VRChat Assets" --db vault.db
python -m vrchat_asset_vault budget vault.db --world "Biblioteca Prohibida"
python -m vrchat_asset_vault export vault.db --collection "Biblioteca Prohibida" --out "D:\Exports\Biblioteca"
```

The GUI (PySide6) is the next step after this CLI core; the scanner,
budget checker and exporter are the same code the GUI will call.

## Tech

Python 3.11+, PySide6 (GUI, next), SQLite (local index), `trimesh`
when available for triangle counts, Blender headless only for
`.blend` thumbnails. MIT license.
