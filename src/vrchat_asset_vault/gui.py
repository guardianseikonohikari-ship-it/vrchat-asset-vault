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

What the user gets here (v3, 2026-11-13):
- Texture-memory totals per collection: how close the world is to
  the 100 MB Quest limit, and which assets are the worst offenders.
- FBX UnitScaleFactor detection: Blender's 0.01 default is flagged
  before the model imports 100x too small in Unity.
- Multi-select (Ctrl+click / Shift+click): combined totals for the
  selection, and export of exactly the selected models.
- .blend stats + thumbnails via Blender headless when Blender is
  installed (graceful "not available" when it is not).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

try:
    from PySide6.QtCore import Qt, QSize, QUrl, QSettings
    from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
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
    # Do NOT leave the Qt names undefined: that used to crash the import
    # with a confusing NameError instead of a clear message. A missing
    # Qt (e.g. libEGL.so.1 on Linux) is an ImportError here, and the
    # dummy base below turns it into a readable RuntimeError on use.
    _QT_AVAILABLE = False
    _QT_ERROR = exc

    class _MissingQt:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                f"PySide6 is not available: {_QT_ERROR}. "
                "Install it with: pip install vrchat-asset-vault[gui]"
            )

    Qt = QUrl = QSettings = QDesktopServices = QIcon = QKeySequence = QApplication = (
        QCheckBox
    ) = QComboBox = QFileDialog = QFormLayout = QFrame = QHBoxLayout = QInputDialog = (
        QLabel
    ) = QListWidget = QListWidgetItem = QLineEdit = QMainWindow = QPixmap = (
        QProgressBar
    ) = QPushButton = QShortcut = QSize = QSplitter = QStatusBar = QVBoxLayout = (
        QWidget
    ) = _MissingQt
    PySide6 = None  # type: ignore

from .budget import (
    QUEST_TRIANGLE_BUDGET,
    QUEST_WORLD_SIZE_BYTES,
    check_asset,
    fmt_bytes,
    texture_mb_light,
    texture_totals_for,
    traffic_light,
    AssetStats,
)
from .database import (
    connect,
    delete_asset,
    load_meta,
    prune_missing,
    update_asset_meta,
    upsert_asset,
)
from .exporter import export_collection, export_unitypackage
from .preview import thumbnail_for
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
        self.selected_assets: list = []
        self.db_path = Path.home() / ".vrchat_asset_vault" / "vault.db"
        self.thumb_dir = self.db_path.parent / "thumbnails"

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Top bar: the two actions that matter, search always visible.
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

        # --- Filters row: format, traffic light, favorites only.
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

        # --- Middle: collections | cards | detail.
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
        self.cards.setIconSize(QSize(96, 96))
        # ExtendedSelection: Ctrl+click adds one card, Shift+click a
        # range — the detail panel then shows the combined totals.
        self.cards.setSelectionMode(QListWidget.ExtendedSelection)
        self.cards.itemClicked.connect(self.on_card_clicked)
        self.cards.itemSelectionChanged.connect(self.on_selection_changed)
        splitter.addWidget(self.cards)

        detail = QFrame()
        detail_layout = QVBoxLayout(detail)
        self.preview_label = QLabel("No preview yet")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(200)
        self.preview_label.setStyleSheet(
            "background: #eef2f6; border: 1px solid #d0d7de; border-radius: 6px;"
        )
        detail_layout.addWidget(self.preview_label)
        self.detail_title = QLabel("Select a model")
        self.detail_title.setWordWrap(True)
        self.detail_body = QLabel(
            "Click a card to see its VRChat budget, source and license.\n\n"
            "Tip: Add folder, then Scan — your files are never moved."
        )
        self.detail_body.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body)

        # World budget bar for the selected collection.
        self.budget_label = QLabel("World budget: no collection selected")
        self.budget_bar = QProgressBar()
        self.budget_bar.setRange(0, 100)
        self.budget_bar.setValue(0)
        detail_layout.addWidget(self.budget_label)
        detail_layout.addWidget(self.budget_bar)
        # Texture memory: the number that actually blows the 100 MB
        # Quest limit, plus the worst offenders by name.
        self.texture_label = QLabel("")
        self.texture_label.setWordWrap(True)
        detail_layout.addWidget(self.texture_label)

        # Editable notes: tags, origin, license, collection, favorite.
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

        # Actions.
        self.export_btn = QPushButton("Export to Unity")
        self.export_btn.setToolTip("Export the selected model(s) to Unity")
        self.export_btn.clicked.connect(self.export_selected)
        self.export_collection_btn = QPushButton("Export collection to Unity")
        self.export_collection_btn.clicked.connect(self.export_current_collection)
        self.export_package_btn = QPushButton("Export .unitypackage")
        self.export_package_btn.setToolTip(
            "One file Unity opens on double-click — the selected models, "
            "or the current collection when nothing is selected"
        )
        self.export_package_btn.clicked.connect(self.export_package)
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
            self.export_package_btn,
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

        # --- Status bar: always true, always visible.
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Library: not chosen yet — click Add folder")

        # Shortcuts.
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.choose_folder)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.search.setFocus)

        # Remember the library between sessions.
        last = self.settings.value("library_path")
        if last and Path(str(last)).is_dir():
            self.library_path = Path(str(last))
            self.scan_library()

    # --- Library ---

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
        # Files deleted or moved since the last scan leave the index.
        removed = prune_missing(conn, {str(a.path) for a in self.assets})
        # Duplicates: same content hash under different paths.
        from collections import Counter

        counts = Counter(a.sha256 for a in self.assets)
        self.dup_shas = {sha for sha, n in counts.items() if n > 1}
        conn.close()
        # Thumbnails are cached by content hash: a rescan never
        # re-renders an unchanged model.
        for asset in self.assets:
            thumbnail_for(asset.path, self.thumb_dir)
        self.refresh_collections()
        self.populate_cards()
        self.update_budget_bar()
        total_tris = sum(a.triangles or 0 for a in self.assets)
        total_mb = sum(a.size_bytes for a in self.assets) / (1024 * 1024)
        message = (
            f"Library: {self.library_path} — {len(self.assets)} models, "
            f"{total_tris:,} / {QUEST_TRIANGLE_BUDGET:,} tris (Quest), "
            f"{total_mb:.1f} / 100 MB"
        )
        if removed:
            message += f" • {removed} removed (no longer on disk)"
        self.statusBar().showMessage(message)

    # --- Collections ---

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

    # --- Cards, filters, sorting ---

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
            # Cached thumbnail only — generating here would stall every
            # keystroke in search; scan_library renders them once.
            thumb = self.thumb_dir / f"{asset.sha256}.png"
            if thumb.exists():
                item.setIcon(QIcon(QPixmap(str(thumb))))
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
        pct = min(100, int(tris / QUEST_TRIANGLE_BUDGET * 100)) if tris else 0
        self.budget_bar.setValue(pct)
        self.budget_bar.setStyleSheet(
            "QProgressBar::chunk { background: %s; }"
            % ("#f85149" if pct >= 100 else "#d29922" if pct >= 80 else "#2ea043")
        )
        totals = texture_totals_for(assets)
        tex_mb = totals["texture_bytes"] / (1024 * 1024)
        label = collection or "All models"
        self.budget_label.setText(
            f"{label}: {tris:,} / {QUEST_TRIANGLE_BUDGET:,} tris (Quest) • "
            f"Models {fmt_bytes(sum(a.size_bytes for a in assets))} • "
            f"Textures {tex_mb:.1f} / 100 MB "
            f"{traffic_dot(texture_mb_light(tex_mb))}"
        )
        if totals["heaviest"]:
            heavy = " • ".join(
                f"{h['name']} {fmt_bytes(h['texture_bytes'])}"
                for h in totals["heaviest"][:3]
            )
            self.texture_label.setText(f"Heaviest textures: {heavy}")
        else:
            self.texture_label.setText("No textures found next to these models.")

    # --- Detail panel ---

    def on_card_clicked(self, item) -> None:
        asset = item.data(Qt.UserRole)
        if asset is None:
            return
        self._select_assets([asset])

    def on_selection_changed(self) -> None:
        """Ctrl+click / Shift+click selection — combined totals for >1."""
        assets = [
            item.data(Qt.UserRole)
            for item in self.cards.selectedItems()
            if item.data(Qt.UserRole) is not None
        ]
        self._select_assets(assets)

    def _select_assets(self, assets: list) -> None:
        self.selected_assets = list(assets)
        if not assets:
            self.selected_asset = None
            self.detail_title.setText("Select a model")
            self.detail_body.setText(
                "Click a card to see its VRChat budget, source and license.\n\n"
                "Tip: Add folder, then Scan — your files are never moved."
            )
            self.preview_label.setText("No preview yet")
            self.preview_label.setPixmap(QPixmap())
            return
        if len(assets) == 1:
            self._show_single_asset(assets[0])
            return
        # Multi-select: combined totals. The notes form still edits
        # the first (anchor) model, and the body says so plainly.
        anchor = assets[0]
        self.selected_asset = anchor
        self._fill_meta_form(anchor)
        self._show_combined(assets)

    def _fill_meta_form(self, asset) -> None:
        m = self.meta.get(str(asset.path), {})
        self.tags_edit.setText(m.get("tags", ""))
        self.source_combo.setCurrentText(m.get("source", ""))
        self.author_edit.setText(m.get("author", ""))
        self.url_edit.setText(m.get("url", ""))
        self.license_combo.setCurrentText(m.get("license", ""))
        self.collection_combo.setCurrentText(m.get("collection", ""))
        self.favorite_btn.setText("★ Favorite" if m.get("favorite") else "☆ Favorite")

    def _show_single_asset(self, asset) -> None:
        self.selected_asset = asset
        self._fill_meta_form(asset)
        self.show_asset(
            asset.path.name,
            AssetStats(
                triangles=asset.triangles,
                materials=asset.materials,
                max_texture_px=asset.max_texture_px,
                scale_factor=asset.scale_factor,
                size_bytes=asset.size_bytes,
            ),
            texture_count=asset.texture_count,
            texture_bytes=asset.texture_bytes,
        )
        self._show_preview(asset)
        # Append scanner warnings (broken / unparsable files) to the body.
        if asset.warnings:
            self.detail_body.setText(
                self.detail_body.text() + "<br/><br/>⚠ " + "<br/>⚠ ".join(asset.warnings)
            )
        if asset.sha256 in self.dup_shas:
            self.detail_body.setText(
                self.detail_body.text()
                + "<br/><br/>⚠ Duplicate: another file in this library has the same content."
            )

    def _show_combined(self, assets: list) -> None:
        """Combined totals for a multi-select — the answer before export."""
        totals = texture_totals_for(assets)
        total_tris = totals["triangles"]
        total_mb = sum(a.size_bytes for a in assets)
        tex_mb = totals["texture_bytes"] / (1024 * 1024)
        materials = sum(a.materials or 0 for a in assets)
        unknown_mats = sum(1 for a in assets if a.materials is None)
        tris_light = traffic_light(
            total_tris, QUEST_TRIANGLE_BUDGET, QUEST_TRIANGLE_BUDGET
        )
        self.detail_title.setText(f"{len(assets)} models selected")
        self.preview_label.setText(f"{len(assets)} models selected")
        self.preview_label.setPixmap(QPixmap())
        lines = [
            f"{traffic_dot(tris_light)} Quest: {total_tris:,} / "
            f"{QUEST_TRIANGLE_BUDGET:,} triangles combined",
            f"{traffic_dot(texture_mb_light(tex_mb))} Textures: "
            f"{tex_mb:.1f} / 100 MB",
            f"Models: {fmt_bytes(total_mb)} on disk",
            "Materials: "
            f"{materials}"
            + (f" (+{unknown_mats} unknown)" if unknown_mats else "")
            + " (each one adds a draw call)",
        ]
        if totals["heaviest"]:
            heavy = ", ".join(
                f"{h['name']} {fmt_bytes(h['texture_bytes'])}"
                for h in totals["heaviest"][:3]
            )
            lines.append(f"Heaviest textures: {heavy}")
        lines.append("")
        lines.append(
            "Export to Unity exports all selected models. "
            "Notes below apply to the first model."
        )
        self.detail_body.setText("<br/>".join(lines))

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

    def _show_preview(self, asset) -> None:
        """Big preview in the detail panel (generated once, cached)."""
        thumb = thumbnail_for(asset.path, self.thumb_dir)
        if thumb is not None:
            pixmap = QPixmap(str(thumb))
            self.preview_label.setPixmap(
                pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            return
        if asset.path.suffix.lower() == ".blend":
            from .blend import unavailable_reason

            reason = unavailable_reason() or "Blender unavailable"
            self.preview_label.setText(
                f"No preview — {reason}.\nOpen in Blender to see it."
            )
        else:
            self.preview_label.setText(
                "No preview — this mesh could not be read.\n"
                "Check the warnings below."
            )

    def show_asset(
        self,
        name: str,
        stats: AssetStats,
        texture_count: int = 0,
        texture_bytes: int = 0,
    ) -> None:
        """Fill the detail panel for one asset. Colour first, numbers second."""
        card = check_asset(stats)
        materials = (
            f"{stats.materials} materials" if stats.materials is not None else "? materials"
        )
        max_tex = (
            f"{stats.max_texture_px} px" if stats.max_texture_px is not None else "? px"
        )
        textures = (
            f"{texture_count} file(s), max {max_tex}, "
            f"{fmt_bytes(texture_bytes)}"
            if texture_count
            else "none found next to the model"
        )
        scale_line = ""
        if stats.scale_factor is not None:
            note = (
                " (Blender default — may import 100x small in Unity)"
                if stats.scale_factor == 0.01
                else ""
            )
            scale_line = f"FBX scale: {stats.scale_factor}{note}<br/>"
        self.detail_title.setText(name)
        # NOTE: the traffic dots are HTML, so this label renders as
        # rich text — line breaks must be <br/>, plain "\n" collapses.
        self.detail_body.setText(
            f"{traffic_dot(card['triangles_quest'])} Quest: "
            f"{stats.triangles or '?'} triangles<br/>"
            f"{traffic_dot(card['triangles_pc'])} PC: "
            f"{stats.triangles or '?'} triangles<br/>"
            f"{traffic_dot(card['texture'])} Max texture: {max_tex}<br/>"
            f"Materials: {materials} (each one adds a draw call)<br/>"
            f"Textures: {textures}<br/>"
            f"{scale_line}"
            f"Size: {fmt_bytes(stats.size_bytes)}<br/><br/>"
            + "<br/>".join(card["warnings"])
        )

    # --- Actions ---

    def _meta_for(self, paths) -> dict:
        return {str(p): self.meta.get(str(p), {}) for p in paths}

    def export_selected(self) -> None:
        """Export the selected model(s) — one card or a multi-select."""
        assets = self.selected_assets or (
            [self.selected_asset] if self.selected_asset is not None else []
        )
        if not assets:
            self.detail_body.setText("Select a model card first, then Export to Unity.")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose where to export for Unity")
        if not out:
            return
        world = self.current_collection() or "World"
        out_dir = Path(out) / f"Export_{world}"
        result = export_collection(
            [a.path for a in assets],
            out_dir,
            world,
            meta_by_path=self._meta_for([a.path for a in assets]),
        )
        names = ", ".join(a.path.name for a in assets[:3])
        if len(assets) > 3:
            names += f" (+{len(assets) - 3} more)"
        message = f"Exported {len(assets)} model(s) ({names}) to {result['out_dir']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"])
        self.detail_body.setText(message)
        self.statusBar().showMessage(f"Exported {len(assets)} model(s) to {out}")

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
        result = export_collection(
            [a.path for a in assets],
            out_dir,
            world,
            meta_by_path=self._meta_for([a.path for a in assets]),
        )
        message = f"Exported {result['assets']} models to {result['out_dir']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"][:5])
        self.detail_body.setText(message)
        self.statusBar().showMessage(message.split("\n")[0])

    def export_package(self) -> None:
        """Selected models as one .unitypackage — or the current view."""
        assets = self.selected_assets or self.visible_assets()
        if not assets:
            self.statusBar().showMessage("Nothing to export — the current view is empty.")
            return
        world = self.current_collection() or "World"
        out, _ = QFileDialog.getSaveFileName(
            self,
            "Save .unitypackage",
            f"Export_{world}.unitypackage",
            "Unity package (*.unitypackage)",
        )
        if not out:
            return
        result = export_unitypackage(
            [a.path for a in assets],
            Path(out),
            world,
            meta_by_path=self._meta_for([a.path for a in assets]),
        )
        message = f"Exported {result['assets']} models to {result['out_file']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"][:5])
        self.detail_body.setText(message)
        self.statusBar().showMessage(message.split("\n")[0])

    def open_in_blender(self) -> None:
        if self.selected_asset is None:
            self.detail_body.setText("Select a model card first, then Open in Blender.")
            return
        from .blend import find_blender

        found = find_blender()
        blender = str(found) if found is not None else shutil.which("blender")
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
