# GUI design — intuitive first

Mochi's rule (2026-11-13): the interface must be intuitive and easy
to use. That outranks extra features.

## Principles

1. **One window, three zones, nothing hidden in menus.** If a user
   has to open a menu to find the main action, the design failed.
2. **Three clicks max to the goal.** Add folder -> pick asset ->
   Export to Unity. Everything else is one click from the detail panel.
3. **Plain language, no jargon on buttons.** "Add folder", "Export to
   Unity", "Open in Blender" — not "Index", "Serialize", "Invoke DCC".
4. **The VRChat answer is a colour, not a number.** Green / amber /
   red dot for Quest, plus the number underneath for those who want it.
5. **Language: English UI.** The audience is VRChat creators worldwide;
   the README is English too. Mochi's own workflow is in Spanish, but
   the product's users are global.
6. **No account, no cloud, no surprise.** Everything happens on the
   user's PC. The status bar always shows where the library lives.

## Layout

```
+--------------------------------------------------------------+
| [Add folder]  [Scan]   Search: [________]  [Quest v] [PC v]  |
+----------+-----------------------------------+-------------+
| All      |  [card] [card] [card] [card]     | Asset name  |
| Favorites|  [card] [card] [card] [card]     | ● Quest     |
| Biblioteca| [card] [card] [card] [card]    | ● PC        |
|  Prohibida|                                 | Tris: 12,400|
| + New    |                                 | Textures:   |
|  collection|                                | 1024 max    |
|          |                                 | Source: ... |
|          |                                 | License: ...|
|          |                                 | [Export]    |
|          |                                 | [Open in    |
|          |                                 |  Blender]   |
+----------+-----------------------------------+-------------+
| Library: D:\VRChat Assets   Total: 84,200 / 250,000 tris ●  |
+--------------------------------------------------------------+
```

- **Top bar:** Add folder (primary, biggest), Scan, search always
  visible, Quest/PC toggle for the traffic lights.
- **Left:** collections, not folders. A collection is a world
  ("Biblioteca Prohibida"). "+ New collection" is one click.
- **Center:** cards. Thumbnail, name, format badge (FBX/OBJ/GLB/blend),
  triangles, one coloured dot. Click selects, double-click opens the
  detail. No card needs a manual to read.
- **Right:** the selected asset's VRChat card, origin/license fields
  (editable in place), and the two actions that matter: Export and
  Open in Blender. "Show in folder" is a small link, not a button.
- **Bottom status bar:** library path, total triangles vs 250k,
  total size vs 100 MB Quest limit. Always visible, always true.

## What the GUI deliberately does NOT do in v0.1

- No full 3D viewer — a rendered thumbnail is enough to recognise a
  prop. A viewer is v0.2 at the earliest.
- No settings screen on first run — the library folder is chosen
  with the big Add folder button, and remembered.
- No login, no sync, no store.

## Implementation

`src/vrchat_asset_vault/gui.py` — PySide6, one `MainWindow`.
It calls the same `scanner` / `budget` / `database` / `exporter`
modules as the CLI, so the CLI and the GUI can never disagree about
a triangle count. Thumbnails in v0.1 are placeholders; real
thumbnails come from trimesh (FBX/OBJ/GLB) and Blender headless
(.blend) in the next step.
