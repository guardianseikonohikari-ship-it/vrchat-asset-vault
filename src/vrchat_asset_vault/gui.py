"""Intuitive GUI for VRChat Asset Vault (PySide6).

Design rule (Mochi, 2026-11-13): intuitive and easy to use first.
One window, three zones, nothing hidden in menus. The VRChat answer
is a colour (green/amber/red for Quest), with the number underneath.

This module calls the same scanner / budget / database / exporter
code as the CLI, so the two can never disagree about a triangle count.
"""
from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QListWidget,
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

    Qt = QApplication = QFrame = QHBoxLayout = QLabel = QListWidget = QLineEdit = (
        QMainWindow
    ) = QPushButton = QSplitter = QStatusBar = QVBoxLayout = QWidget = _MissingQt
    PySide6 = None  # type: ignore

from .budget import check_asset, AssetStats

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

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Top bar: the two actions that matter, search always visible.
        top = QHBoxLayout()
        self.add_folder_btn = QPushButton("＋ Add folder")
        self.add_folder_btn.setToolTip("Choose a folder with your 3D models")
        self.scan_btn = QPushButton("Scan")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search models, tags, authors…")
        top.addWidget(self.add_folder_btn)
        top.addWidget(self.scan_btn)
        top.addWidget(self.search, stretch=1)
        layout.addLayout(top)

        # --- Middle: collections | cards | detail.
        splitter = QSplitter(Qt.Horizontal)

        self.collections = QListWidget()
        self.collections.addItems(["All", "Favorites", "Biblioteca Prohibida"])
        splitter.addWidget(self.collections)

        self.cards = QListWidget()
        self.cards.setViewMode(QListWidget.IconMode)
        self.cards.setResizeMode(QListWidget.Adjust)
        splitter.addWidget(self.cards)

        detail = QFrame()
        detail_layout = QVBoxLayout(detail)
        self.detail_title = QLabel("Select a model")
        self.detail_title.setWordWrap(True)
        self.detail_body = QLabel("Click a card to see its VRChat budget, source and license.")
        self.detail_body.setWordWrap(True)
        self.export_btn = QPushButton("Export to Unity")
        self.open_blender_btn = QPushButton("Open in Blender")
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_body, stretch=1)
        detail_layout.addWidget(self.export_btn)
        detail_layout.addWidget(self.open_blender_btn)
        splitter.addWidget(detail)

        splitter.setSizes([180, 560, 360])
        layout.addWidget(splitter, stretch=1)

        # --- Status bar: always true, always visible.
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Library: not chosen yet — click Add folder")

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
