from vrchat_asset_vault.budget import (
    AssetStats,
    check_asset,
    check_world,
    scale_warning,
    texture_mb_light,
    texture_totals_for,
)
from vrchat_asset_vault.scanner import FoundAsset


def test_small_prop_is_green():
    card = check_asset(AssetStats(triangles=1200, max_texture_px=1024, size_bytes=1000))
    assert card["triangles_quest"] == "green"
    assert card["warnings"] == []


def test_huge_prop_warns():
    card = check_asset(AssetStats(triangles=200_000, max_texture_px=4096, size_bytes=1000))
    assert card["triangles_quest"] == "red"
    assert any("1024px" in w for w in card["warnings"])


def test_world_over_budget():
    result = check_world(300_000, 50 * 1024 * 1024)
    assert result["quest_triangles"] == "red"
    assert result["quest_size_ok"] is True


def test_scale_factor_warning_blender_default():
    card = check_asset(AssetStats(triangles=100, scale_factor=0.01))
    assert any("0.01" in w and "100x" in w for w in card["warnings"])
    assert scale_warning(1.0) is None
    assert scale_warning(None) is None
    assert "not 1.0" in (scale_warning(2.54) or "")


def test_texture_totals_for_names_heaviest(tmp_path):
    from pathlib import Path

    def asset(name, tex_bytes, tris=12):
        return FoundAsset(
            path=Path(f"/lib/{name}"), size_bytes=1000, sha256="x" * 64,
            triangles=tris, texture_bytes=tex_bytes,
        )

    totals = texture_totals_for(
        [asset("shelf.fbx", 8_000_000), asset("books.obj", 3_000_000), asset("candle.obj", 0)]
    )
    assert totals["assets"] == 3
    assert totals["triangles"] == 36
    assert totals["texture_bytes"] == 11_000_000
    assert [h["name"] for h in totals["heaviest"]] == ["shelf.fbx", "books.obj"]
    assert texture_mb_light(10.0) == "green"
    assert texture_mb_light(85.0) == "amber"
    assert texture_mb_light(120.0) == "red"
