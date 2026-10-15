# -*- coding: utf-8 -*-
"""Diálogo «Áreas / FIR»: la misma tabla de áreas que la pestaña de
Preferencias, abierta desde el bloque Área de «Obtener datos…». Devuelve en
`values()` las claves `areas`, `areas_margin_deg` y `areas_coord_format`."""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMessageBox

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.areas_editor import AreasEditor


class AreasDialog(GlassDialog):
    def __init__(self, parent=None, cfg=None, regions_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Áreas / FIR")
        self.setMinimumWidth(820)
        self._cfg = dict(cfg or {})
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        title = QLabel("Áreas de descarga por FIR")
        title.setObjectName("Heading")
        lay.addWidget(title)
        self.editor = AreasEditor(self._cfg, regions_fn=regions_fn)
        lay.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Cancelar")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        self.btn_ok = QPushButton("Aplicar")
        self.btn_ok.setObjectName("AccentBtn")
        self.btn_ok.clicked.connect(self._accept)
        row.addWidget(self.btn_ok)
        lay.addLayout(row)

    def _accept(self):
        errs = self.editor.errors()
        if errs:
            QMessageBox.warning(self, "Áreas / FIR", "Corregí la tabla antes de aplicar:\n"
                                + "\n".join(errs[:6]))
            return
        self.accept()

    def values(self):
        return self.editor.values()
