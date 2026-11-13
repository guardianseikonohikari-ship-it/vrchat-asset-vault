"""VRChat budget rules.

Official VRChat guidance (Creators docs, Android Content Optimization):
- ~250,000 triangles recommended per world in total (recommendation,
  not a hard upload cap).
- Textures: aim for 1024x1024 maximum; larger textures are the main
  cause of high memory use on Quest.
- Android/Quest world: 100 MB max after build-time compression.
- Each extra material is an extra submesh / draw call.

PC is more forgiving in community guides (~500k-1M tris workable),
so the traffic light is shown for PC and Quest separately.
"""
from __future__ import annotations

from dataclasses import dataclass

QUEST_TRIANGLE_BUDGET = 250_000
PC_TRIANGLE_BUDGET = 750_000  # working midpoint of community 500k-1M range
MAX_TEXTURE_SIZE = 1024
QUEST_WORLD_SIZE_BYTES = 100 * 1024 * 1024


@dataclass
class AssetStats:
    triangles: int | None = None  # None = unknown (e.g. .blend, not parsed yet)
    materials: int | None = None
    max_texture_px: int | None = None
    size_bytes: int = 0


def traffic_light(value: int | None, warn_at: int, bad_at: int) -> str:
    """green / amber / red / unknown."""
    if value is None:
        return "unknown"
    if value >= bad_at:
        return "red"
    if value >= warn_at:
        return "amber"
    return "green"


def check_asset(stats: AssetStats) -> dict:
    """Per-asset VRChat card. Returns a plain dict the GUI/CLI can render."""
    return {
        "triangles": stats.triangles,
        "triangles_quest": traffic_light(
            stats.triangles, QUEST_TRIANGLE_BUDGET // 10, QUEST_TRIANGLE_BUDGET // 2
        ),
        # A single prop should be a small share of the world budget.
        "triangles_pc": traffic_light(
            stats.triangles, PC_TRIANGLE_BUDGET // 10, PC_TRIANGLE_BUDGET // 2
        ),
        "max_texture_px": stats.max_texture_px,
        "texture": traffic_light(stats.max_texture_px, MAX_TEXTURE_SIZE + 1, 2048),
        "size_bytes": stats.size_bytes,
        "warnings": warnings_for(stats),
    }


def warnings_for(stats: AssetStats) -> list[str]:
    warnings: list[str] = []
    if stats.triangles is not None and stats.triangles >= QUEST_TRIANGLE_BUDGET // 2:
        warnings.append(
            f"{stats.triangles:,} triangles is half the recommended "
            f"Quest world budget ({QUEST_TRIANGLE_BUDGET:,}) on its own."
        )
    if stats.max_texture_px is not None and stats.max_texture_px > MAX_TEXTURE_SIZE:
        warnings.append(
            f"Texture {stats.max_texture_px}px exceeds the 1024px VRChat target."
        )
    if stats.materials is not None and stats.materials > 8:
        warnings.append(
            f"{stats.materials} materials — each one adds a submesh / draw call."
        )
    return warnings


def check_world(total_triangles: int, total_size_bytes: int) -> dict:
    return {
        "total_triangles": total_triangles,
        "quest_triangles": traffic_light(
            total_triangles, QUEST_TRIANGLE_BUDGET, QUEST_TRIANGLE_BUDGET
        ),
        "quest_size_ok": total_size_bytes <= QUEST_WORLD_SIZE_BYTES,
        "quest_size_bytes": total_size_bytes,
        "quest_size_limit_bytes": QUEST_WORLD_SIZE_BYTES,
    }
