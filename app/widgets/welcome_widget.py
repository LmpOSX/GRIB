"""
Pantalla vacía que se muestra cuando no hay archivo GRIB abierto.
Ofrece «Abrir GRIB…» y la lista de archivos recientes.
"""
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal


class WelcomeWidget(QWidget):
    open_clicked = pyqtSignal()
    recent_clicked = pyqtSignal(str)   # emite la ruta absoluta

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeWidget")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 60, 40, 40)
        root.setSpacing(14)

        root.addStretch(1)

        title = QLabel("Visor GRIB")
        title.setObjectName("WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel("Abrí un archivo GRIB2 de viento y temperatura (GFS) "
                          "para ver el mapa por nivel de vuelo.")
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        root.addSpacing(18)

        # ── Acciones ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        self._open_btn = QPushButton("Abrir GRIB…")
        self._open_btn.setObjectName("WelcomeBtn")
        self._open_btn.setFixedHeight(42)
        self._open_btn.setMinimumWidth(200)
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self.open_clicked.emit)
        btn_row.addWidget(self._open_btn)

        btn_row.addStretch()
        root.addLayout(btn_row)

        root.addSpacing(26)

        # ── Archivos recientes ──
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
        """Llena la lista de recientes. Los que ya no existen se muestran en
        gris; quien recibe el clic se ocupa del archivo faltante."""
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
