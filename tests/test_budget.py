from vrchat_asset_vault.budget import AssetStats, check_asset, check_world


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
