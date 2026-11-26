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
class OptimizePreset:
    """One Quest-optimizer preset: how much to keep, and the hard caps.

    Reduction is a ratio *with a floor and a ceiling*, never an
    unbounded percentage: ``keep_ratio`` is the fraction of triangles
    kept, ``per_asset_tri_cap`` is the absolute ceiling for one asset
    (a 300k-triangle hero prop at Balanced still stops at 50k).
    """

    name: str
    keep_ratio: float  # fraction of triangles kept (0.10–0.90)
    max_texture_px: int  # longest texture side allowed
    per_asset_tri_cap: int  # absolute triangle ceiling per asset

    def target_triangles(self, triangles: int | None) -> int | None:
        """Triangles to aim for, or None when no decimation is needed.

        None means "leave the mesh alone": unknown count, already at
        or below the floor (decimating a 12-triangle cube saves
        nothing), or already at/below both the ratio target and the cap.
        """
        if triangles is None or triangles <= MIN_DECIMATE_TRIANGLES:
            return None
        target = min(int(triangles * self.keep_ratio), self.per_asset_tri_cap)
        return target if target < triangles else None


# Default per-asset ceiling (the Balanced cap): a single prop should
# never eat a fifth of the 250k Quest world budget on its own.
QUEST_PER_ASSET_CAP = 50_000

# Decimating a mesh this small saves nothing and only risks breaking
# it: a 12-triangle cube is never "optimized" to 6 triangles. Below
# the floor the mesh is already negligible (0.04% of the world budget)
# and is copied unchanged.
MIN_DECIMATE_TRIANGLES = 100

PRESETS: dict[str, OptimizePreset] = {
    "Gentle": OptimizePreset("Gentle", 0.75, 1024, 100_000),
    "Balanced": OptimizePreset("Balanced", 0.50, 1024, 50_000),
    "Aggressive": OptimizePreset("Aggressive", 0.25, 512, 20_000),
}
DEFAULT_PRESET_NAME = "Balanced"


def preset_for(name: str) -> OptimizePreset:
    """The named preset, or the default when the name is unknown."""
    return PRESETS.get(name, PRESETS[DEFAULT_PRESET_NAME])


def custom_preset(
    keep_ratio: float, max_texture_px: int, per_asset_tri_cap: int
) -> OptimizePreset:
    """A user-tuned preset; ratios outside 10–90% are rejected, not clamped."""
    if not 0.10 <= keep_ratio <= 0.90:
        raise ValueError(f"keep_ratio must be 0.10–0.90, got {keep_ratio}")
    if max_texture_px not in (256, 512, 1024, 2048):
        raise ValueError(f"max_texture_px must be 256/512/1024/2048, got {max_texture_px}")
    if per_asset_tri_cap <= 0:
        raise ValueError("per_asset_tri_cap must be positive")
    return OptimizePreset("Custom", keep_ratio, max_texture_px, per_asset_tri_cap)


@dataclass
class AssetStats:
    triangles: int | None = None  # None = unknown (e.g. .blend, not parsed yet)
    materials: int | None = None
    max_texture_px: int | None = None
    scale_factor: float | None = None
    size_bytes: int = 0


def scale_warning(scale_factor: float | None) -> str | None:
    """What a non-1.0 FBX UnitScaleFactor means when importing in Unity."""
    if scale_factor is None or scale_factor == 1.0:
        return None
    if scale_factor == 0.01:
        return (
            "UnitScaleFactor is 0.01 (Blender's default export) — Unity may "
            "import this model 100x smaller than expected; in Unity's FBX "
            "import settings, check the Scale Factor (usually set it to 1)."
        )
    return (
        f"UnitScaleFactor is {scale_factor} (not 1.0) — Unity may import "
        "this model at the wrong size; check the Scale Factor in the FBX "
        "import settings."
    )


def texture_totals_for(assets) -> dict:
    """Texture-memory totals for a list of assets (a collection / world).

    The 100 MB Quest limit is usually blown by textures, not by the
    models themselves — "heaviest" names the assets to shrink first.
    Works on in-memory FoundAsset objects (same shape as the DB helper
    collection_texture_totals, so GUI and CLI can never disagree).
    """
    total_tex = sum(a.texture_bytes or 0 for a in assets)
    total_tris = sum(a.triangles or 0 for a in assets)
    heaviest = sorted(assets, key=lambda a: a.texture_bytes or 0, reverse=True)[:5]
    return {
        "assets": len(assets),
        "triangles": total_tris,
        "texture_bytes": total_tex,
        "heaviest": [
            {"name": a.path.name, "texture_bytes": a.texture_bytes or 0}
            for a in heaviest
            if (a.texture_bytes or 0) > 0
        ],
    }


def fmt_bytes(n: int) -> str:
    """Human size: MB with one decimal, else KB, else bytes."""
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def texture_mb_light(texture_mb: float) -> str:
    """Traffic light for texture memory vs the 100 MB Quest limit."""
    return traffic_light(texture_mb, 80, 100)


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
    scale = scale_warning(stats.scale_factor)
    if scale is not None:
        warnings.append(scale)
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
