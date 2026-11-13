"""Intuitive GUI for VRChat Asset Vault (PySide6).

Design rule (Mochi, 2026-11-13): intuitive and easy to use first.
One window, three zones, nothing hidden in menus. The VRChat answer
is a colour (green/amber/red for Quest), with the number underneath.

Every button is wired — a button that does nothing is a bug, not a
placeholder. This module calls the same scanner / budget / database /
exporter code as the CLI, so the two can never disagree about a
triangle count.

What the user gets here (v2, 2026-11-13):
- Library remembered between sessions; Scan re-indexes without moving files.
- Search + filters (format, traffic light, favorites only) + sorting.
- Collections per world, each with its own Quest budget bar (250k tris).
- Per-asset notes: tags, source, author, URL, license, collection,
  favorite — all saved in the local SQLite index.
- Duplicate and broken-file warnings, shown on the card and in detail.
- Export one model or a whole collection to Unity, with a manifest
  that carries origin/license per file.
- Open in Blender, show in folder, copy path, remove from index.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QUrl, QSettings
    from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFormLayout,
        QFrame,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QLineEdit,
        QMainWindow,
        QProgressBar,
        QPushButton,
        QSplitter,
        QStatusBar,
        QVBoxLayout,
        QWidget,
    )

    _QT_AVAILABLE = True
    _QT_ERROR: Exception | None = None
except ImportError as exc:  # GUI is optional in the CLI install
    _QT_AVAILABLE = False
    _QT_ERROR = exc

    class _MissingQt:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                f"PySide6 is not available: {_QT_ERROR}. "
                "Install it with: pip install vrchat-asset-vault[gui]"
            )

    Qt = QUrl = QSettings = QDesktopServices = QKeySequence = QApplication = (
        QCheckBox
    ) = QComboBox = QFileDialog = QFormLayout = QFrame = QHBoxLayout = QInputDialog = (
        QLabel
    ) = QListWidget = QListWidgetItem = QLineEdit = QMainWindow = QProgressBar = (
        QPushButton
    ) = QShortcut = QSplitter = QStatusBar = QVBoxLayout = QWidget = _MissingQt
    PySide6 = None  # type: ignore

from .budget import (
    QUEST_TRIANGLE_BUDGET,
    QUEST_WORLD_SIZE_BYTES,
    check_asset,
    AssetStats,
)
from .database import connect, delete_asset, load_meta, update_asset_meta, upsert_asset
from .exporter import export_collection
from .scanner import scan

SOURCES = [
    "",
    "Poly Haven",
    "Sketchfab",
    "Booth",
    "Gumroad",
    "Jinxxy",
    "Own / made by me",
    "Other",
]
LICENSES = [
    "",
    "CC0",
    "CC BY",
    "CC BY-SA",
    "Royalty-free (store terms)",
    "Personal use only",
    "Unknown",
]
FORMATS = ["All", "fbx", "obj", "glb", "gltf", "blend"]

TRAFFIC_COLOURS = {
    "green": "#2ea043",
    "amber": "#d29922",
    "red": "#f85149",
    "unknown": "#8b949e",
}

STYLESHEET = """
QMainWindow { background: #f6f8fa; }
QPushButton { padding: 6px 12px; border-radius: 6px; background: #ffffff;
    border: 1px solid #d0d7de; }
QPushButton:hover { background: #eef2f6; }
QPushButton:default { background: #0969da; color: white; border-color: #0969da; }
QLineEdit, QComboBox { padding: 5px 8px; border-radius: 6px; background: #ffffff;
    border: 1px solid #d0d7de; }
QListWidget { background: #ffffff; border: 1px solid #d0d7de; border-radius: 6px; }
QProgressBar { border: 1px solid #d0d7de; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #2ea043; border-radius: 6px; }
"""


def traffic_dot(status: str) -> str:
    colour = TRAFFIC_COLOURS.get(status, "#8b949e")
    return f'<span style="color:{colour}; font-size:20px">●</span>'


class MainWindow(QMainWindow):
    """One window: top bar, filters, collections | cards | detail, status bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VRChat Asset Vault")
        self.resize(1200, 750)
        self.setStyleSheet(STYLESHEET)
        self.settings = QSettings("VRChatAssetVault", "VRChat Asset Vault")
        self.library_path: Path | None = None
        self.assets: list = []
        self.meta: dict[str, dict] = {}
        self.dup_shas: set[str] = set()
        self.selected_asset = None
        self.db_path = Path.home() / ".vrchat_asset_vault" / "vault.db"

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.add_folder_btn = QPushButton("＋ Add folder")
        self.add_folder_btn.setToolTip("Choose a folder with your 3D models (Ctrl+O)")
        self.add_folder_btn.setDefault(True)
        self.add_folder_btn.clicked.connect(self.choose_folder)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setToolTip("Re-scan the library folder")
        self.scan_btn.clicked.connect(self.scan_library)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models, tags, authors… (Ctrl+F)")
        self.search.textChanged.connect(self.populate_cards)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Sort: name", "Sort: triangles ↓", "Sort: triangles ↑", "Sort: size ↓"])
        self.sort_combo.currentIndexChanged.connect(self.populate_cards)
        top.addWidget(self.add_folder_btn)
        top.addWidget(self.scan_btn)
        top.addWidget(self.search, stretch=1)
        top.addWidget(self.sort_combo)
        layout.addLayout(top)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        self.format_combo.currentIndexChanged.connect(self.populate_cards)
        filters.addWidget(self.format_combo)
        filters.addWidget(QLabel("Quest light:"))
        self.traffic_combo = QComboBox()
        self.traffic_combo.addItems(["All", "green", "amber", "red", "unknown"])
        self.traffic_combo.currentIndexChanged.connect(self.populate_cards)
        filters.addWidget(self.traffic_combo)
        self.fav_only = QCheckBox("★ Favorites only")
        self.fav_only.stateChanged.connect(self.populate_cards)
        filters.addWidget(self.fav_only)
        filters.addStretch(1)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal)

        left = QFrame()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Collections (one per world)"))
        self.collections = QListWidget()
        self.collections.addItems(["All", "Favorites", "Biblioteca Prohibida"])
        self.collections.currentItemChanged.connect(self.on_collection_changed)
        self.collections.setCurrentRow(0)
        left_layout.addWidget(self.collections, stretch=1)
        col_btns = QHBoxLayout()
        self.new_collection_btn = QPushButton("＋ New")
        self.new_collection_btn.clicked.connect(self.new_collection)
        self.del_collection_btn = QPushButton("− Delete")
        self.del_collection_btn.clicked.connect(self.delete_collection)
        col_btns.addWidget(self.new_collection_btn)
        col_btns.addWidget(self.del_collection_btn)
        left_layout.addLayout(col_btns)
        splitter.addWidget(left)

        self.cards = QListWidget()
        self.cards.setViewMode(QListWidget.IconMode)
        self.cards.setResizeMode(QListWidget.Adjust)
        self.cards.itemClicked.connect(self.on_card_clicked)
        splitter.addWidget(self.cards)

        detail = QFrame()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Select a model")
        self.detail_title.setWordWrap(True)
        self.detail_body = QLabel(
            "Click a card to see its VRChat budget, source and license.\n\n"
            "Tip: Add folder, then Scan — your files are never moved."
        )
        self.detail_body.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body)

        self.budget_label = QLabel("World budget: no collection selected")
        self.budget_bar = QProgressBar()
        self.budget_bar.setRange(0, 100)
        self.budget_bar.setValue(0)
        detail_layout.addWidget(self.budget_label)
        detail_layout.addWidget(self.budget_bar)

        form = QFormLayout()
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("furniture, wood, library (comma separated)")
        form.addRow("Tags:", self.tags_edit)
        self.source_combo = QComboBox()
        self.source_combo.setEditable(True)
        self.source_combo.addItems(SOURCES)
        form.addRow("Source:", self.source_combo)
        self.author_edit = QLineEdit()
        form.addRow("Author:", self.author_edit)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://…")
        form.addRow("URL:", self.url_edit)
        self.license_combo = QComboBox()
        self.license_combo.setEditable(True)
        self.license_combo.addItems(LICENSES)
        form.addRow("License:", self.license_combo)
        self.collection_combo = QComboBox()
        self.collection_combo.setEditable(True)
        self.collection_combo.addItems(["", "Biblioteca Prohibida"])
        form.addRow("Collection:", self.collection_combo)
        detail_layout.addLayout(form)

        meta_btns = QHBoxLayout()
        self.favorite_btn = QPushButton("☆ Favorite")
        self.favorite_btn.clicked.connect(self.toggle_favorite)
        self.save_meta_btn = QPushButton("Save notes")
        self.save_meta_btn.clicked.connect(self.save_meta)
        meta_btns.addWidget(self.favorite_btn)
        meta_btns.addWidget(self.save_meta_btn)
        detail_layout.addLayout(meta_btns)

        self.export_btn = QPushButton("Export to Unity")
        self.export_btn.clicked.connect(self.export_selected)
        self.export_collection_btn = QPushButton("Export collection to Unity")
        self.export_collection_btn.clicked.connect(self.export_current_collection)
        self.open_blender_btn = QPushButton("Open in Blender")
        self.open_blender_btn.clicked.connect(self.open_in_blender)
        self.show_folder_btn = QPushButton("Show in folder")
        self.show_folder_btn.clicked.connect(self.show_in_folder)
        self.copy_path_btn = QPushButton("Copy path")
        self.copy_path_btn.clicked.connect(self.copy_path)
        self.remove_btn = QPushButton("Remove from library")
        self.remove_btn.clicked.connect(self.remove_from_library)
        for btn in (
            self.export_btn,
            self.export_collection_btn,
            self.open_blender_btn,
            self.show_folder_btn,
            self.copy_path_btn,
            self.remove_btn,
        ):
            detail_layout.addWidget(btn)
        detail_layout.addStretch(1)
        splitter.addWidget(detail)

        splitter.setSizes([200, 560, 440])
        layout.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Library: not chosen yet — click Add folder")

        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.choose_folder)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.search.setFocus)

        last = self.settings.value("library_path")
        if last and Path(str(last)).is_dir():
            self.library_path = Path(str(last))
            self.scan_library()

    def _db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return connect(self.db_path)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose your 3D models folder")
        if not folder:
            return
        self.library_path = Path(folder)
        self.settings.setValue("library_path", folder)
        self.scan_library()

    def scan_library(self) -> None:
        if self.library_path is None:
            self.statusBar().showMessage("Choose a library folder first — click Add folder")
            self.choose_folder()
            return
        self.assets = scan(self.library_path)
        conn = self._db()
        for asset in self.assets:
            upsert_asset(conn, asset)
            self.meta[str(asset.path)] = load_meta(conn, str(asset.path))
        from collections import Counter

        counts = Counter(a.sha256 for a in self.assets)
        self.dup_shas = {sha for sha, n in counts.items() if n > 1}
        conn.close()
        self.refresh_collections()
        self.populate_cards()
        self.update_budget_bar()
        total_tris = sum(a.triangles or 0 for a in self.assets)
        total_mb = sum(a.size_bytes for a in self.assets) / (1024 * 1024)
        self.statusBar().showMessage(
            f"Library: {self.library_path} — {len(self.assets)} models, "
            f"{total_tris:,} / {QUEST_TRIANGLE_BUDGET:,} tris (Quest), "
            f"{total_mb:.1f} / 100 MB"
        )

    def refresh_collections(self) -> None:
        current = self.current_collection()
        known = {"All", "Favorites"}
        for m in self.meta.values():
            if m.get("collection"):
                known.add(m["collection"])
        known.add("Biblioteca Prohibida")
        self.collections.clear()
        self.collections.addItems(sorted(known, key=lambda c: (c != "All", c != "Favorites", c)))
        for i in range(self.collections.count()):
            if self.collections.item(i).text() == (current or "All"):
                self.collections.setCurrentRow(i)
                break

    def current_collection(self) -> str | None:
        item = self.collections.currentItem()
        if item is None or item.text() == "All":
            return None
        return item.text()

    def new_collection(self) -> None:
        name, ok = QInputDialog.getText(self, "New collection", "Collection name (one per world):")
        if not ok or not name.strip():
            return
        name = name.strip()
        items = [self.collections.item(i).text() for i in range(self.collections.count())]
        if name not in items:
            self.collections.addItem(name)
        self.collections.setCurrentRow(self.collections.count() - 1)

    def delete_collection(self) -> None:
        item = self.collections.currentItem()
        if item is None or item.text() in ("All", "Favorites"):
            self.statusBar().showMessage("All and Favorites cannot be deleted.")
            return
        name = item.text()
        conn = self._db()
        for path, m in list(self.meta.items()):
            if m.get("collection") == name:
                update_asset_meta(conn, path, collection="")
                m["collection"] = ""
        conn.close()
        self.refresh_collections()
        self.populate_cards()
        self.statusBar().showMessage(f"Collection '{name}' deleted — its models are now unassigned.")

    def on_collection_changed(self, *_args) -> None:
        # Fires once during __init__ (setCurrentRow) before the cards
        # widget exists — ignore that one.
        if not hasattr(self, "cards"):
            return
        self.populate_cards()
        self.update_budget_bar()

    def visible_assets(self) -> list:
        query = self.search.text().strip().lower()
        fmt = self.format_combo.currentText()
        light = self.traffic_combo.currentText()
        collection = self.current_collection()
        out = []
        for asset in self.assets:
            m = self.meta.get(str(asset.path), {})
            if fmt != "All" and asset.path.suffix.lower().lstrip(".") != fmt:
                continue
            if collection == "Favorites" and not m.get("favorite"):
                continue
            if collection and collection != "Favorites" and m.get("collection") != collection:
                continue
            if self.fav_only.isChecked() and not m.get("favorite"):
                continue
            stats = AssetStats(triangles=asset.triangles, size_bytes=asset.size_bytes)
            card = check_asset(stats)
            if light != "All" and card["triangles_quest"] != light:
                continue
            if query:
                haystack = " ".join(
                    [asset.path.name, m.get("tags", ""), m.get("author", ""), m.get("source", "")]
                ).lower()
                if query not in haystack:
                    continue
            out.append(asset)
        mode = self.sort_combo.currentText()
        if mode.startswith("Sort: triangles ↓"):
            out.sort(key=lambda a: a.triangles if a.triangles is not None else -1, reverse=True)
        elif mode.startswith("Sort: triangles ↑"):
            out.sort(key=lambda a: a.triangles if a.triangles is not None else 10**18)
        elif mode.startswith("Sort: size ↓"):
            out.sort(key=lambda a: a.size_bytes, reverse=True)
        else:
            out.sort(key=lambda a: a.path.name.lower())
        return out

    def populate_cards(self) -> None:
        self.cards.clear()
        for asset in self.visible_assets():
            m = self.meta.get(str(asset.path), {})
            stats = AssetStats(triangles=asset.triangles, size_bytes=asset.size_bytes)
            card = check_asset(stats)
            star = "★ " if m.get("favorite") else ""
            dup = " [DUP]" if asset.sha256 in self.dup_shas else ""
            warn = " ⚠" if asset.warnings else ""
            item = QListWidgetItem(
                f"{star}{asset.path.name}\n"
                f"{asset.triangles if asset.triangles is not None else '?'} tris — "
                f"Quest: {card['triangles_quest']}{dup}{warn}"
            )
            item.setData(Qt.UserRole, asset)
            self.cards.addItem(item)

    def update_budget_bar(self) -> None:
        collection = self.current_collection()
        if collection == "Favorites":
            assets = [a for a in self.assets if self.meta.get(str(a.path), {}).get("favorite")]
        elif collection:
            assets = [a for a in self.assets if self.meta.get(str(a.path), {}).get("collection") == collection]
        else:
            assets = self.assets
        tris = sum(a.triangles or 0 for a in assets)
        size_mb = sum(a.size_bytes for a in assets) / (1024 * 1024)
        pct = min(100, int(tris / QUEST_TRIANGLE_BUDGET * 100)) if tris else 0
        self.budget_bar.setValue(pct)
        self.budget_bar.setStyleSheet(
            "QProgressBar::chunk { background: %s; }"
            % ("#f85149" if pct >= 100 else "#d29922" if pct >= 80 else "#2ea043")
        )
        label = collection or "All models"
        self.budget_label.setText(
            f"{label}: {tris:,} / {QUEST_TRIANGLE_BUDGET:,} tris (Quest) • "
            f"{size_mb:.1f} / 100 MB"
        )

    def on_card_clicked(self, item) -> None:
        asset = item.data(Qt.UserRole)
        if asset is None:
            return
        self.selected_asset = asset
        m = self.meta.get(str(asset.path), {})
        self.tags_edit.setText(m.get("tags", ""))
        self.source_combo.setCurrentText(m.get("source", ""))
        self.author_edit.setText(m.get("author", ""))
        self.url_edit.setText(m.get("url", ""))
        self.license_combo.setCurrentText(m.get("license", ""))
        self.collection_combo.setCurrentText(m.get("collection", ""))
        self.favorite_btn.setText("★ Favorite" if m.get("favorite") else "☆ Favorite")
        self.show_asset(
            asset.path.name,
            AssetStats(triangles=asset.triangles, size_bytes=asset.size_bytes),
        )
        if asset.warnings:
            self.detail_body.setText(
                self.detail_body.text() + "\n\n⚠ " + "\n⚠ ".join(asset.warnings)
            )
        if asset.sha256 in self.dup_shas:
            self.detail_body.setText(
                self.detail_body.text()
                + "\n\n⚠ Duplicate: another file in this library has the same content."
            )

    def save_meta(self) -> None:
        if self.selected_asset is None:
            self.statusBar().showMessage("Select a model card first.")
            return
        path = str(self.selected_asset.path)
        fields = {
            "tags": self.tags_edit.text().strip(),
            "source": self.source_combo.currentText().strip(),
            "author": self.author_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "license": self.license_combo.currentText().strip(),
            "collection": self.collection_combo.currentText().strip(),
        }
        conn = self._db()
        update_asset_meta(conn, path, **fields)
        conn.close()
        self.meta[path].update(fields)
        self.refresh_collections()
        self.populate_cards()
        self.update_budget_bar()
        self.statusBar().showMessage(f"Notes saved for {self.selected_asset.path.name}")

    def toggle_favorite(self) -> None:
        if self.selected_asset is None:
            self.statusBar().showMessage("Select a model card first.")
            return
        path = str(self.selected_asset.path)
        new_value = 0 if self.meta.get(path, {}).get("favorite") else 1
        conn = self._db()
        update_asset_meta(conn, path, favorite=new_value)
        conn.close()
        self.meta.setdefault(path, {})["favorite"] = new_value
        self.favorite_btn.setText("★ Favorite" if new_value else "☆ Favorite")
        self.populate_cards()
        self.update_budget_bar()

    def show_asset(self, name: str, stats: AssetStats) -> None:
        """Fill the detail panel for one asset. Colour first, numbers second."""
        card = check_asset(stats)
        self.detail_title.setText(name)
        self.detail_body.setText(
            f"{traffic_dot(card['triangles_quest'])} Quest: "
            f"{stats.triangles or '?'} triangles\n"
            f"{traffic_dot(card['triangles_pc'])} PC: "
            f"{stats.triangles or '?'} triangles\n"
            f"Max texture: {stats.max_texture_px or '?'} px\n"
            f"Size: {stats.size_bytes / 1024:.0f} KB\n\n"
            + "\n".join(card["warnings"])
        )

    def _enrich_manifest(self, out_dir: Path, paths: list[Path]) -> None:
        manifest_path = out_dir / "manifest.json"
        if not manifest_path.exists():
            return
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in data.get("assets", []):
            for p in paths:
                if p.name == entry.get("file"):
                    m = self.meta.get(str(p), {})
                    entry["source"] = m.get("source", "")
                    entry["author"] = m.get("author", "")
                    entry["url"] = m.get("url", "")
                    entry["license"] = m.get("license", "")
                    entry["tags"] = m.get("tags", "")
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def export_selected(self) -> None:
        if self.selected_asset is None:
            self.detail_body.setText("Select a model card first, then Export to Unity.")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose where to export for Unity")
        if not out:
            return
        world = self.current_collection() or "World"
        out_dir = Path(out) / f"Export_{world}"
        result = export_collection([self.selected_asset.path], out_dir, world)
        self._enrich_manifest(out_dir, [self.selected_asset.path])
        message = f"Exported to {result['out_dir']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"])
        self.detail_body.setText(message)
        self.statusBar().showMessage(f"Exported {self.selected_asset.path.name} to {out}")

    def export_current_collection(self) -> None:
        assets = self.visible_assets()
        if not assets:
            self.statusBar().showMessage("Nothing to export — the current view is empty.")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose where to export for Unity")
        if not out:
            return
        world = self.current_collection() or "World"
        out_dir = Path(out) / f"Export_{world}"
        result = export_collection([a.path for a in assets], out_dir, world)
        self._enrich_manifest(out_dir, [a.path for a in assets])
        message = f"Exported {result['assets']} models to {result['out_dir']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"][:5])
        self.detail_body.setText(message)
        self.statusBar().showMessage(message.split("\n")[0])

    def open_in_blender(self) -> None:
        if self.selected_asset is None:
            self.detail_body.setText("Select a model card first, then Open in Blender.")
            return
        blender = shutil.which("blender")
        if blender is None:
            self.detail_body.setText(
                "Blender was not found in PATH.\n"
                "Open Blender yourself and import this file:\n"
                f"{self.selected_asset.path}"
            )
            return
        subprocess.Popen([blender, str(self.selected_asset.path)])
        self.statusBar().showMessage(f"Opened {self.selected_asset.path.name} in Blender")

    def show_in_folder(self) -> None:
        if self.selected_asset is None:
            self.statusBar().showMessage("Select a model card first.")
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.selected_asset.path.parent))
        )

    def copy_path(self) -> None:
        if self.selected_asset is None:
            self.statusBar().showMessage("Select a model card first.")
            return
        QApplication.clipboard().setText(str(self.selected_asset.path))
        self.statusBar().showMessage("Path copied to clipboard.")

    def remove_from_library(self) -> None:
        if self.selected_asset is None:
            self.statusBar().showMessage("Select a model card first.")
            return
        name = self.selected_asset.path.name
        conn = self._db()
        delete_asset(conn, str(self.selected_asset.path))
        conn.close()
        self.assets = [a for a in self.assets if a is not self.selected_asset]
        self.meta.pop(str(self.selected_asset.path), None)
        self.selected_asset = None
        self.populate_cards()
        self.update_budget_bar()
        self.detail_title.setText("Select a model")
        self.detail_body.setText(f"{name} removed from the index. The file on disk was NOT deleted.")
        self.statusBar().showMessage(f"Removed {name} from the library index.")


def run() -> int:
    if not _QT_AVAILABLE:
        raise SystemExit(
            f"PySide6 is not available: {_QT_ERROR}. "
            "Run: pip install vrchat-asset-vault[gui]"
        )
    app = QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
