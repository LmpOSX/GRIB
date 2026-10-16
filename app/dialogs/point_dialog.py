# -*- coding: utf-8 -*-
"""Ventana «Consulta de punto» (clic derecho, ⌘I): el mismo bloque de
consulta que la ficha del clic sobre el mapa (PointQueryWidget), en una
ventana no modal y única: cada clic derecho le cambia el punto; el FL y la
hora que cargó el usuario se conservan.
"""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.point_query_widget import PointQueryWidget


class PointDialog(GlassDialog):
    def __init__(self, parent=None, variation_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Consulta de punto")
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        title = QLabel("Viento y temperatura en un punto")
        title.setObjectName("Heading")
        lay.addWidget(title)
        head = QLabel("PUNTO")
        head.setObjectName("PopupHead")
        lay.addWidget(head)
        self.query = PointQueryWidget(self, variation_fn=variation_fn)
        lay.addWidget(self.query)
        hint = QLabel("Cambiá el geodésico, la hora o el FL y se recalcula; el dato es el del "
                      "origen de la celda (esquina SO), como en el FDP")
        hint.setObjectName("PopupHint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        row = QHBoxLayout()
        self.btn_copy = QPushButton("Copiar")
        self.btn_copy.setToolTip("Copia la consulta y los valores como texto")
        self.btn_copy.clicked.connect(self.copy_text)
        row.addWidget(self.btn_copy)
        row.addStretch()
        b = QPushButton("Cerrar")
        b.clicked.connect(self.close)
        row.addWidget(b)
        lay.addLayout(row)
        # Los mismos nombres que el bloque, para quien use la ventana directamente
        q = self.query
        self.ed_geo, self.ed_time, self.sp_fl = q.ed_geo, q.ed_time, q.sp_fl
        self.lbl_cell, self.lbl_step, self.lbl_mode = q.lbl_cell, q.lbl_step, q.lbl_mode

    # ── Delegación al bloque ─────────────────────────────────────────────────

    @property
    def lat(self):
        return self.query.lat

    @property
    def lon(self):
        return self.query.lon

    def set_reader(self, reader):
        self.query.set_reader(reader)

    def set_defaults(self, when=None, fl=None):
        self.query.set_defaults(when, fl)

    def set_point(self, lat, lon):
        self.query.set_point(lat, lon)

    def fl(self):
        return self.query.fl()

    @staticmethod
    def cell():
        return PointQueryWidget.cell()

    def when(self):
        return self.query.when()

    def refresh(self):
        self.query.refresh()

    def rows(self):
        return self.query.rows()

    def report_text(self):
        return self.query.report_text()

    def copy_text(self):
        self.query.copy_text()
