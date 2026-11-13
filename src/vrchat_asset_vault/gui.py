"""Intuitive GUI for VRChat Asset Vault (PySide6).

Design rule (Mochi, 2026-11-13): intuitive and easy to use first.
One window, three zones, nothing hidden in menus. The VRChat answer
is a colour (green/amber/red for Quest), with the number underneath.

Every button is wired — a button that does nothing is a bug, not a
placeholder. This module calls the same scanner / budget / database /
exporter code as the CLI, so the two can never disagree about a
triangle count.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QLineEdit,
        QMainWindow,
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

    Qt = QApplication = QFileDialog = QFrame = QHBoxLayout = QLabel = QListWidget = (
        QListWidgetItem
    ) = QLineEdit = QMainWindow = QPushButton = QSplitter = QStatusBar = (
        QVBoxLayout
    ) = QWidget = _MissingQt
    PySide6 = None  # type: ignore

from .budget import check_asset, AssetStats
from .database import connect, upsert_asset
from .exporter import export_collection
from .scanner import scan

TRAFFIC_COLOURS = {
    "green": "#2ea043",
    "amber": "#d29922",
    "red": "#f85149",
    "unknown": "#8b949e",
}


def traffic_dot(status: str) -> str:
    colour = TRAFFIC_COLOURS.get(status, "#8b949e")
    return f'<span style="color:{colour}; font-size:20px">●</span>'


class MainWindow(QMainWindow):
    """One window: top bar, collections | cards | detail, status bar."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("VRChat Asset Vault")
        self.resize(1100, 700)
        self.library_path: Path | None = None
        self.assets: list = []
        self.selected_asset = None
        self.db_path = Path.home() / ".vrchat_asset_vault" / "vault.db"

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.add_folder_btn = QPushButton("＋ Add folder")
        self.add_folder_btn.setToolTip("Choose a folder with your 3D models")
        self.add_folder_btn.clicked.connect(self.choose_folder)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setToolTip("Re-scan the library folder")
        self.scan_btn.clicked.connect(self.scan_library)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models, tags, authors…")
        self.search.textChanged.connect(self.filter_cards)
        top.addWidget(self.add_folder_btn)
        top.addWidget(self.scan_btn)
        top.addWidget(self.search, stretch=1)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)

        self.collections = QListWidget()
        self.collections.addItems(["All", "Favorites", "Biblioteca Prohibida"])
        splitter.addWidget(self.collections)

        self.cards = QListWidget()
        self.cards.setViewMode(QListWidget.IconMode)
        self.cards.setResizeMode(QListWidget.Adjust)
        self.cards.itemClicked.connect(self.on_card_clicked)
        splitter.addWidget(self.cards)

        detail = QFrame()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Select a model")
        self.detail_title.setWordWrap(True)
        self.detail_body = QLabel("Click a card to see its VRChat budget, source and license.")
        self.detail_body.setWordWrap(True)
        self.export_btn = QPushButton("Export to Unity")
        self.export_btn.clicked.connect(self.export_selected)
        self.open_blender_btn = QPushButton("Open in Blender")
        self.open_blender_btn.clicked.connect(self.open_in_blender)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body, stretch=1)
        detail_layout.addWidget(self.export_btn)
        detail_layout.addWidget(self.open_blender_btn)
        splitter.addWidget(detail)

        splitter.setSizes([180, 560, 360])
        layout.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Library: not chosen yet — click Add folder")

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose your 3D models folder")
        if not folder:
            return
        self.library_path = Path(folder)
        self.statusBar().showMessage(f"Library: {folder}")
        self.scan_library()

    def scan_library(self) -> None:
        if self.library_path is None:
            self.statusBar().showMessage("Choose a library folder first — click Add folder")
            self.choose_folder()
            return
        self.assets = scan(self.library_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(self.db_path)
        for asset in self.assets:
            upsert_asset(conn, asset)
        conn.close()
        self.populate_cards()
        total_tris = sum(a.triangles or 0 for a in self.assets)
        self.statusBar().showMessage(
            f"Library: {self.library_path} — {len(self.assets)} models, "
            f"{total_tris:,} / 250,000 tris (Quest budget)"
        )

    def populate_cards(self) -> None:
        self.cards.clear()
        for asset in self.assets:
            stats = AssetStats(triangles=asset.triangles, size_bytes=asset.size_bytes)
            card = check_asset(stats)
            item = QListWidgetItem(
                f"{asset.path.name}\n"
                f"{asset.triangles if asset.triangles is not None else '?'} tris — "
                f"Quest: {card['triangles_quest']}"
            )
            item.setData(Qt.UserRole, asset)
            self.cards.addItem(item)
        self.filter_cards()

    def filter_cards(self) -> None:
        query = self.search.text().strip().lower()
        for i in range(self.cards.count()):
            item = self.cards.item(i)
            item.setHidden(bool(query) and query not in item.text().lower())

    def on_card_clicked(self, item) -> None:
        asset = item.data(Qt.UserRole)
        if asset is None:
            return
        self.selected_asset = asset
        self.show_asset(
            asset.path.name,
            AssetStats(triangles=asset.triangles, size_bytes=asset.size_bytes),
        )

    def export_selected(self) -> None:
        if self.selected_asset is None:
            self.detail_body.setText("Select a model card first, then Export to Unity.")
            return
        out = QFileDialog.getExistingDirectory(self, "Choose where to export for Unity")
        if not out:
            return
        world = "World"
        current = self.collections.currentItem()
        if current is not None and current.text() != "All":
            world = current.text()
        result = export_collection(
            [self.selected_asset.path], Path(out), world
        )
        message = f"Exported to {result['out_dir']}"
        if result["warnings"]:
            message += "\n\n" + "\n".join(f"! {w}" for w in result["warnings"])
        self.detail_body.setText(message)
        self.statusBar().showMessage(f"Exported {self.selected_asset.path.name} to {out}")

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
