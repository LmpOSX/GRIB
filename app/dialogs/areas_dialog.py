# -*- coding: utf-8 -*-
"""Diálogo «Áreas / FIR»: las mismas tablas de áreas y de grillas con
nombre que la pestaña de Preferencias, abierto desde el bloque Área de
«Obtener datos…». Devuelve en `values()` las claves `areas`,
`areas_margin_deg`, `areas_coord_format` y `grids`."""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMessageBox

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.areas_editor import AreasEditor
from ..widgets.grids_editor import GridsEditor


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
        lay.addWidget(self.editor, 2)
        lbl = QLabel("Grillas con nombre")
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)
        self.grids_editor = GridsEditor(self._cfg)
        self.editor.cb_format.currentIndexChanged.connect(
            lambda _i: self.grids_editor.set_coord_format(self.editor.coord_format()))
        lay.addWidget(self.grids_editor, 1)
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
        errs = self.editor.errors() + self.grids_editor.errors()
        if errs:
            QMessageBox.warning(self, "Áreas / FIR", "Corregí la tabla antes de aplicar:\n"
                                + "\n".join(errs[:6]))
            return
        self.accept()

    def values(self):
        return dict(self.editor.values(), **self.grids_editor.values())
