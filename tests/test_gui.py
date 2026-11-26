"""Offscreen GUI tests (QT_QPA_PLATFORM=offscreen).

The window must build and every wired button must work without a real
display. HOME is redirected to a temp dir so the test never touches
the user's real ~/.vrchat_asset_vault vault or QSettings.
"""
import os

import pytest

pytest.importorskip("PySide6", reason="GUI tests need PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vrchat_asset_vault.gui import MainWindow  # noqa: E402


@pytest.fixture()
def window(library, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.library_path = library
    win.scan_library()
    yield win
    win.close()


def test_window_scans_and_shows_cards(window, library):
    assert window.cards.count() == 4  # cube, book, box.glb, broken.fbx
    assert "4 models" in window.statusBar().currentMessage()
    assert window.thumb_dir.is_dir()
    thumbs = list(window.thumb_dir.glob("*.png"))
    assert len(thumbs) == 3  # cube, book, box.glb — broken.fbx has none


def test_card_click_shows_real_stats_and_preview(window):
    for i in range(window.cards.count()):
        item = window.cards.item(i)
        if item.text().startswith("cube.obj"):
            break
    else:
        raise AssertionError("cube.obj card not found")
    window.on_card_clicked(item)
    body = window.detail_body.text()
    assert "12 triangles" in body
    assert "2 materials" in body  # cube.obj: 2 usemtl groups
    assert "2048 px" in body  # cube_diffuse.png is 2048 wide
    assert "Textures: 2 file(s)" in body
    assert window.preview_label.pixmap() is not None
    assert not window.preview_label.pixmap().isNull()


def test_broken_file_card_warns(window):
    for i in range(window.cards.count()):
        item = window.cards.item(i)
        if "broken.fbx" in item.text():
            window.on_card_clicked(item)
            break
    assert "could not parse" in window.detail_body.text()
    pixmap = window.preview_label.pixmap()
    assert pixmap is None or pixmap.isNull()  # QLabel returns a null pixmap, not None


def test_prune_reports_deleted_file(window, library, tmp_path):
    (library / "book.obj").unlink()
    window.scan_library()
    assert window.cards.count() == 3
    assert "1 removed (no longer on disk)" in window.statusBar().currentMessage()


def test_search_filters_cards(window):
    window.search.setText("book")
    assert window.cards.count() == 1
    assert "book.obj" in window.cards.item(0).text()
    window.search.setText("zzz-no-match")
    assert window.cards.count() == 0
    window.search.setText("")


def test_budget_bar_updates_for_collection(window):
    window.collections.setCurrentRow(0)  # All
    # cube 12 + book 12 + box.glb 12 + broken.fbx unknown = 36 tris
    assert "36 / 250,000 tris" in window.budget_label.text()


def test_budget_bar_shows_texture_totals(window):
    # cube.obj has two neighbouring textures, book.obj one — the bar
    # names the texture memory and the worst offender.
    assert "Textures" in window.budget_label.text()
    assert "100 MB" in window.budget_label.text()
    assert "Heaviest textures:" in window.texture_label.text()


def test_multi_select_shows_combined_totals(window):
    items = [window.cards.item(i) for i in range(window.cards.count())]
    cube = next(i for i in items if i.text().startswith("cube.obj"))
    book = next(i for i in items if i.text().startswith("book.obj"))
    cube.setSelected(True)
    book.setSelected(True)
    assert window.detail_title.text() == "2 models selected"
    body = window.detail_body.text()
    assert "24" in body  # 12 + 12 triangles combined
    assert "Textures:" in body
    assert "Export to Unity exports all selected models" in body


def test_export_selected_exports_selection(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    items = [window.cards.item(i) for i in range(window.cards.count())]
    cube = next(i for i in items if i.text().startswith("cube.obj"))
    book = next(i for i in items if i.text().startswith("book.obj"))
    cube.setSelected(True)
    book.setSelected(True)
    window.export_selected()
    out = tmp_path / "Export_World"
    assert (out / "cube.obj").exists()
    assert (out / "book.obj").exists()
    assert (out / "cube_diffuse.png").exists()


def test_export_package_exports_selection(window, tmp_path, monkeypatch):
    import tarfile

    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "sel.unitypackage"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "")
    )
    items = [window.cards.item(i) for i in range(window.cards.count())]
    cube = next(i for i in items if i.text().startswith("cube.obj"))
    book = next(i for i in items if i.text().startswith("book.obj"))
    cube.setSelected(True)
    book.setSelected(True)
    window.export_package()
    assert target.exists()
    with tarfile.open(target, "r:gz") as tar:
        names = tar.getnames()
    assert "Assets/cube.obj" in names
    assert "Assets/book.obj" in names
    assert "Assets/box.glb" not in names  # not selected: stays out


def test_card_click_shows_fbx_scale(window, library):
    from conftest import write_fbx_with_scale

    write_fbx_with_scale(library / "shelf.fbx", 0.01)
    window.scan_library()
    for i in range(window.cards.count()):
        item = window.cards.item(i)
        if item.text().startswith("shelf.fbx"):
            break
    else:
        raise AssertionError("shelf.fbx card not found")
    window.on_card_clicked(item)
    body = window.detail_body.text()
    assert "FBX scale: 0.01" in body
    assert "100x smaller" in body


def test_blend_card_shows_real_stats_and_preview(window, library):
    """End-to-end wiring: a real .blend scans, previews, shows stats."""
    from test_blend import _make_test_blend
    from vrchat_asset_vault.blend import find_blender

    blender = find_blender()
    if blender is None:
        pytest.skip("no Blender on this machine — .blend GUI test skipped")
    # Distinct stem: "cube.blend" would inherit cube.obj's neighbouring
    # textures (same stem), and the merged max would be 2048, not 64.
    _make_test_blend(blender, library / "blendcube.blend")
    window.scan_library()
    for i in range(window.cards.count()):
        item = window.cards.item(i)
        if item.text().startswith("blendcube.blend"):
            break
    else:
        raise AssertionError("blendcube.blend card not found")
    window.on_card_clicked(item)
    body = window.detail_body.text()
    assert "12 triangles" in body
    assert "1 materials" in body
    assert "64 px" in body
    pixmap = window.preview_label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
