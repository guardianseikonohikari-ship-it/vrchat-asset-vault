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

# ---------------------------------------------------------------- optimizer

def _wait_for_worker(window, timeout: float = 60.0) -> None:
    """Pump events until the optimize worker finishes (or time out)."""
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + timeout
    while window.optimize_worker is not None and window.optimize_worker.isRunning():
        if time.monotonic() > deadline:
            raise AssertionError("optimize worker did not finish in time")
        QApplication.processEvents()
        time.sleep(0.05)
    QApplication.processEvents()


def test_optimize_preflight_shows_summary(window):
    window.optimize_preflight()
    body = window.detail_body.text()
    assert "Optimize 4 model(s)" in body  # cube, book, box.glb, broken.fbx
    assert "Balanced" in body
    assert "Blender:" in body  # found here (.tools Blender), or not found
    assert "Originals are never modified" in body
    assert not window.start_optimize_btn.isHidden()
    assert window.optimize_btn.isHidden()
    assert window.detail_title.text() == "Optimize for Quest — ready"


def test_optimize_preflight_warns_without_blender(window, monkeypatch):
    import vrchat_asset_vault.gui as gui_module

    monkeypatch.setattr(gui_module, "blender_available", lambda: False)
    window.optimize_preflight()
    body = window.detail_body.text()
    assert "Blender: not found" in body
    assert "will be skipped (no Blender): broken.fbx" in body


def test_optimize_run_reports_and_writes_folder(
    window, library, tmp_path, monkeypatch
):
    import json

    import vrchat_asset_vault.gui as gui_module
    from vrchat_asset_vault.optimizer import OptimizeCancelled  # noqa: F401
    from vrchat_asset_vault.scanner import sha256_of

    from conftest import write_subdivided_sphere_obj

    # A real decimation target in the library, then rescan.
    sphere = library / "sphere.obj"
    write_subdivided_sphere_obj(sphere, subdivisions=2)
    window.scan_library()
    assert window.cards.count() == 5
    before_hash = sha256_of(sphere)

    # Trimesh engine for a fast, deterministic GUI test (the Blender
    # engine has its own tests in test_blend_optimize.py).
    monkeypatch.setattr(
        "vrchat_asset_vault.blend.blender_available", lambda: False
    )
    monkeypatch.setattr(
        "vrchat_asset_vault.gui.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path),
    )
    window.optimize_preflight()
    window.start_optimization()
    _wait_for_worker(window)

    assert window.report_table.rowCount() == 5
    statuses = {
        window.report_table.item(r, 0).text(): window.report_table.item(r, 3).text()
        for r in range(window.report_table.rowCount())
    }
    assert statuses["sphere.obj"] == "optimized"
    assert statuses["broken.fbx"] == "skipped"  # FBX needs Blender
    assert "Optimization finished" in window.detail_body.text()
    assert "Optimized 5 model(s)" in window.statusBar().currentMessage()

    out_dir = tmp_path / "Optimized_World"
    data = json.loads((out_dir / "optimization_report.json").read_text(encoding="utf-8"))
    assert data["totals"]["assets"] == 5
    assert data["totals"]["triangles_before"] == sum(
        a["triangles_before"] or 0 for a in data["assets"]
    )
    assert (out_dir / "sphere.obj").is_file()
    assert sha256_of(sphere) == before_hash  # original untouched


def test_optimize_cancel_stops_between_assets(window, tmp_path, monkeypatch):
    import time

    import vrchat_asset_vault.gui as gui_module
    from vrchat_asset_vault.optimizer import OptimizeCancelled

    def slow_collection(paths, out_dir, world, preset, **kwargs):
        """One asset, then wait until cancelled, then stop."""
        from vrchat_asset_vault.optimizer import AssetReport

        cancel = kwargs.get("cancel_event")
        yield AssetReport(
            source=paths[0],
            output=out_dir / "cube.obj",
            status="optimized",
            engine="trimesh",
            triangles_before=12,
            triangles_after=12,
            texture_bytes_before=0,
            texture_bytes_after=0,
        )
        deadline = time.monotonic() + 10.0
        while not (cancel is not None and cancel.is_set()):
            if time.monotonic() > deadline:
                return
            time.sleep(0.05)
        raise OptimizeCancelled()

    monkeypatch.setattr(gui_module, "optimize_collection", slow_collection)
    monkeypatch.setattr(
        "vrchat_asset_vault.gui.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path),
    )
    window.optimize_preflight()
    window.start_optimization()
    # Wait for the first asset to land in the table, then cancel.
    import time as _time

    deadline = _time.monotonic() + 10.0
    while window.report_table.rowCount() == 0:
        if _time.monotonic() > deadline:
            raise AssertionError("first asset never reported")
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        _time.sleep(0.05)
    window.cancel_optimization()
    _wait_for_worker(window)
    assert window.report_table.rowCount() == 1
    assert "Cancelled" in window.detail_body.text()
    assert "cancelled" in window.statusBar().currentMessage().lower()


def test_export_optimized_to_unity_after_run(window, library, tmp_path, monkeypatch):
    import json

    import vrchat_asset_vault.gui as gui_module

    from conftest import write_subdivided_sphere_obj

    write_subdivided_sphere_obj(library / "sphere.obj", subdivisions=2)
    window.scan_library()
    monkeypatch.setattr(
        "vrchat_asset_vault.blend.blender_available", lambda: False
    )
    dirs = iter([str(tmp_path), str(tmp_path)])
    monkeypatch.setattr(
        "vrchat_asset_vault.gui.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: next(dirs),
    )
    window.optimize_preflight()
    window.start_optimization()
    _wait_for_worker(window)
    assert window.last_optimized_dir == tmp_path / "Optimized_World"

    window.export_optimized_to_unity()
    export_dir = tmp_path / "Export_World"
    assert (export_dir / "manifest.json").is_file()
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"], "exported manifest is empty"
    assert "Exported" in window.statusBar().currentMessage()
