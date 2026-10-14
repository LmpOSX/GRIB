"""
Empty-state widget shown when no project is open.
Offers quick actions (new / open) and a list of recent files.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal


class WelcomeWidget(QWidget):
    new_clicked = pyqtSignal()
    open_clicked = pyqtSignal()
    recent_clicked = pyqtSignal(str)   # emits absolute path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeWidget")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 60, 40, 40)
        root.setSpacing(14)

        root.addStretch(1)

        title = QLabel("Presupuestador Pro")
        title.setObjectName("WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel("Creá un nuevo presupuesto o abrí uno existente.")
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        root.addSpacing(18)

        # ── Action buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        self._new_btn = QPushButton("Nuevo presupuesto")
        self._new_btn.setObjectName("WelcomeBtn")
        self._new_btn.setFixedHeight(42)
        self._new_btn.setMinimumWidth(200)
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.clicked.connect(self.new_clicked.emit)
        btn_row.addWidget(self._new_btn)

        self._open_btn = QPushButton("Abrir…")
        self._open_btn.setObjectName("WelcomeBtn")
        self._open_btn.setFixedHeight(42)
        self._open_btn.setMinimumWidth(200)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self.open_clicked.emit)
        btn_row.addWidget(self._open_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addSpacing(26)

        # ── Recent files ──
        self._recent_label = QLabel("Archivos recientes")
        self._recent_label.setObjectName("WelcomeSectionHeader")
        self._recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._recent_label)

        self._recent_list = QListWidget()
        self._recent_list.setObjectName("RecentFilesList")
        self._recent_list.setMaximumWidth(560)
        self._recent_list.setMaximumHeight(260)
        self._recent_list.setFrameShape(QListWidget.Shape.NoFrame)
        self._recent_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self._recent_list.itemActivated.connect(self._on_item_activated)
        self._recent_list.itemClicked.connect(self._on_item_activated)

        list_row = QHBoxLayout()
        list_row.addStretch()
        list_row.addWidget(self._recent_list)
        list_row.addStretch()
        root.addLayout(list_row)

        self._empty_label = QLabel("No hay archivos recientes.")
        self._empty_label.setObjectName("WelcomeEmpty")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._empty_label)

        root.addStretch(2)

    def _on_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.recent_clicked.emit(path)

    def set_recent_files(self, paths: list):
        """Populate the recent files list. Paths that no longer exist are
        shown grayed out — the caller handles missing files on click."""
        self._recent_list.clear()
        paths = paths or []

        for p in paths:
            exists = os.path.exists(p)
            name = os.path.basename(p) or p
            folder = os.path.dirname(p) or "~"
            folder = folder.replace(os.path.expanduser("~"), "~")
            display = f"{name}\n{folder}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, p)
            item.setToolTip(p if exists else f"{p}  (no encontrado)")
            if not exists:
                item.setForeground(Qt.GlobalColor.gray)
            self._recent_list.addItem(item)

        has_any = bool(paths)
        self._recent_label.setVisible(has_any)
        self._recent_list.setVisible(has_any)
        self._empty_label.setVisible(not has_any)
