"""Diálogo «Acerca de» (menú Ayuda)."""
import platform

from PyQt6.QtCore import Qt, QT_VERSION_STR
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from .. import __version__
from .glass_dialog import GlassDialog, add_shadow as _add_shadow


class AboutDialog(GlassDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Acerca de Visor GRIB")
        self.setMinimumWidth(420)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)

        title = QLabel("Visor GRIB")
        title.setObjectName("Heading")
        lay.addWidget(title)

        version = QLabel(f"Versión {__version__}")
        version.setObjectName("SubHeading")
        lay.addWidget(version)

        desc = QLabel(
            "Visor de escritorio de archivos GRIB2 de viento y temperatura "
            "(GFS) en niveles de presión: barbas coloreadas por velocidad, "
            "contornos de temperatura, niveles de vuelo (ISA, interpolación "
            "en ln p), exportación a PNG y CSV.")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        deps = []
        try:
            import eccodes
            deps.append(f"ecCodes {eccodes.__version__}")
        except Exception:
            deps.append("ecCodes no disponible")
        try:
            import matplotlib
            deps.append(f"matplotlib {matplotlib.__version__}")
        except Exception:
            pass
        try:
            import cartopy
            deps.append(f"cartopy {cartopy.__version__}")
        except Exception:
            deps.append("cartopy no disponible (mapa sin costas)")
        info = QLabel(f"Qt {QT_VERSION_STR} · Python {platform.python_version()}<br>"
                      + " · ".join(deps))
        info.setObjectName("SubHeading")
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setWordWrap(True)
        lay.addWidget(info)

        row = QHBoxLayout()
        row.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.setObjectName("AccentBtn")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)
