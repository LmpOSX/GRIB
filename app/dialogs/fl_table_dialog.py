# -*- coding: utf-8 -*-
"""«Ver tabla»: los FL del modo elegido con su presión ISA exacta (donde va
el dato) y la etiqueta que se graba en el GRIB. Se abre desde Exportar a
WAFS y desde Preferencias ▸ WAFS; el combo permite cambiar de modo."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import fl_table as flt


class FlTableDialog(GlassDialog):
    COLS = ("FL", "ISA_Pa (dato)", "Etiqueta en el GRIB", "Nominal hPa", "OACI16", "INDRA14")

    def __init__(self, parent=None, mode=flt.DEFAULT_MODE):
        super().__init__(parent)
        self.setWindowTitle("Tabla de niveles de vuelo")
        self.setMinimumSize(640, 560)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        title = QLabel("Tabla FL ↔ presión del generador WAFS")
        title.setObjectName("Heading")
        lay.addWidget(title)
        row = QHBoxLayout()
        row.addWidget(QLabel("Modo"))
        self.cb_mode = QComboBox()
        for m in flt.MODES:
            self.cb_mode.addItem(flt.MODE_LABELS[m], m)
        self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(flt.normalize_mode(mode))))
        self.cb_mode.currentIndexChanged.connect(lambda _i: self._fill())
        row.addWidget(self.cb_mode, 1)
        lay.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        hh = self.table.horizontalHeader()
        for i in range(len(self.COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.table, 1)
        self.lbl = QLabel("")
        self.lbl.setObjectName("Hint")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Cerrar")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)
        self._fill()

    def mode(self):
        return self.cb_mode.currentData() or flt.DEFAULT_MODE

    def _fill(self):
        mode = self.mode()
        rows = flt.table_rows(mode)
        self.table.setRowCount(len(rows))
        for r, (fl, isa, lab, txt) in enumerate(rows):
            vals = [f"F{fl:03d}", f"{isa} Pa ({isa / 100.0:g} hPa)", txt, f"{flt.nominal_hpa(fl)}",
                    "✓" if fl in flt.OACI16 else "", "✓" if fl in flt.INDRA14 else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                elif c >= 4:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, it)
        self.lbl.setText(f"{len(rows)} niveles. El dato de cada FL se interpola siempre a ISA_Pa; "
                         "la etiqueta es la presión que se graba en el mensaje GRIB y la que "
                         "reconoce cada consumidor. Tabla copiada literal del generador del "
                         "servidor (NOAA-EMC/wafs), no recalculada.")
