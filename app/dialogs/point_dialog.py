# -*- coding: utf-8 -*-
"""Consulta de un punto del mapa (clic derecho): viento y temperatura de la
capa inferior, la superior y el valor en un FL cualquiera, para el paso
cuya ventana de validez contiene la hora pedida, al estilo del FDP.

Ventana no modal y única: cada clic derecho le cambia el punto; el FL, la
hora y la convención de celda que cargó el usuario se conservan. No
conoce la ventana principal: recibe el lector con set_reader y un
callable que devuelve la variación magnética vigente (norte magnético).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator, QGuiApplication
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QComboBox,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import point_query as pq


class PointDialog(GlassDialog):
    COLS = ("Capa", "Nivel", "Viento (kt / °)", "Temperatura (°C)")
    ROWS = ("Capa superior", "Nivel pedido", "Capa inferior")

    def __init__(self, parent=None, variation_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Consulta de punto")
        self.setMinimumSize(640, 460)
        self._reader = None
        self._variation_fn = variation_fn
        self._variation = 0.0
        self.lat = self.lon = None
        self._res = None            # último point_query
        self._step = None           # (índice, GribStep, dentro de ventana)
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

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Geodésico (grados y minutos):"), 0, 0)
        self.ed_geo = QLineEdit()
        self.ed_geo.setPlaceholderText("3125S06411W")
        self.ed_geo.setToolTip("Punto del clic; se puede escribir otro (DDMM[N|S]DDDMM[E|W])")
        self.ed_geo.editingFinished.connect(self._geo_edited)
        grid.addWidget(self.ed_geo, 0, 1)
        self.lbl_geo = QLabel("")
        self.lbl_geo.setObjectName("Hint")
        grid.addWidget(self.lbl_geo, 0, 2)

        grid.addWidget(QLabel("Hora de sobrevuelo (YYMMDDHHMM):"), 1, 0)
        self.ed_time = QLineEdit()
        self.ed_time.setPlaceholderText("2510221300")
        self.ed_time.setValidator(QIntValidator(0, 999999999, self))
        self.ed_time.setMaxLength(12)
        self.ed_time.setToolTip("Hora UTC; se usa el paso cuya ventana de validez la contiene")
        self.ed_time.textChanged.connect(lambda _t: self.refresh())
        grid.addWidget(self.ed_time, 1, 1)
        self.lbl_step = QLabel("")
        self.lbl_step.setObjectName("Hint")
        self.lbl_step.setWordWrap(True)
        grid.addWidget(self.lbl_step, 1, 2)

        grid.addWidget(QLabel("Nivel de sobrevuelo (banda, sin F):"), 2, 0)
        self.sp_fl = QSpinBox()
        self.sp_fl.setRange(0, 999)
        self.sp_fl.setSingleStep(10)
        self.sp_fl.setValue(300)
        self.sp_fl.setToolTip("Cualquier FL: si no es un nivel del archivo se interpola en ln(p) "
                              "entre la capa de abajo y la de arriba (no se extrapola)")
        self.sp_fl.valueChanged.connect(self._fl_changed)
        grid.addWidget(self.sp_fl, 2, 1)
        self.lbl_fl = QLabel("")
        self.lbl_fl.setObjectName("Hint")
        self.lbl_fl.setWordWrap(True)
        grid.addWidget(self.lbl_fl, 2, 2)

        grid.addWidget(QLabel("Celda:"), 3, 0)
        self.cb_cell = QComboBox()
        for key, name in pq.CELL_MODES:
            self.cb_cell.addItem(name, key)
        self.cb_cell.setToolTip("Qué punto de la grilla representa al clic")
        self.cb_cell.currentIndexChanged.connect(lambda _i: self.refresh())
        grid.addWidget(self.cb_cell, 3, 1)
        self.lbl_cell = QLabel("")
        self.lbl_cell.setObjectName("Hint")
        grid.addWidget(self.lbl_cell, 3, 2)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        self.table = QTableWidget(len(self.ROWS), len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        hh = self.table.horizontalHeader()
        for i in range(len(self.COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for r, name in enumerate(self.ROWS):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            for c in range(1, len(self.COLS)):
                self.table.setItem(r, c, QTableWidgetItem("—"))
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.table)
        self.lbl_mode = QLabel("")
        self.lbl_mode.setObjectName("Hint")
        self.lbl_mode.setWordWrap(True)
        lay.addWidget(self.lbl_mode)

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

    def _fit_table(self):
        """Alto justo para las tres filas (la tabla no tiene scroll)."""
        t = self.table
        h = t.horizontalHeader().height() + 2 * t.frameWidth()
        for r in range(t.rowCount()):
            h += t.rowHeight(r)
        t.setFixedHeight(h)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_table()

    # ── Entradas ─────────────────────────────────────────────────────────────

    def set_reader(self, reader):
        """Lector abierto (o None al cerrar el archivo)."""
        self._reader = reader
        self.refresh()

    def set_defaults(self, when=None, fl=None):
        """Hora y FL iniciales (el paso y el FL del panel) sólo si el usuario
        todavía no cargó los suyos."""
        if when is not None and not self.ed_time.text().strip():
            self.ed_time.setText(pq.format_overflown_time(when))
        if fl is not None and not getattr(self, "_fl_touched", False):
            self.sp_fl.blockSignals(True)
            self.sp_fl.setValue(int(fl))
            self.sp_fl.blockSignals(False)
            self.refresh()

    def set_point(self, lat, lon):
        """Punto del clic derecho."""
        self.lat, self.lon = float(lat), float(lon)
        self.ed_geo.blockSignals(True)
        self.ed_geo.setText(pq.geodesic_ddmm(self.lat, self.lon))
        self.ed_geo.blockSignals(False)
        self.refresh()

    def _fl_changed(self, _v):
        self._fl_touched = True
        self.refresh()

    def _geo_edited(self):
        parsed = pq.parse_geodesic(self.ed_geo.text())
        if parsed is None:
            self.lbl_geo.setText("formato: 3125S06411W")
            return
        self.lat, self.lon = parsed
        self.refresh()

    def fl(self):
        return int(self.sp_fl.value())

    def cell(self):
        return self.cb_cell.currentData() or "nearest"

    def when(self):
        return pq.parse_overflown_time(self.ed_time.text())

    # ── Cálculo ──────────────────────────────────────────────────────────────

    def refresh(self):
        r = self._reader
        self._res, self._step = None, None
        try:
            self._variation = float(self._variation_fn() or 0.0) if self._variation_fn else 0.0
        except Exception:
            self._variation = 0.0
        self.lbl_geo.setText("" if self.lat is None else f"lat {self.lat:.2f}, lon {self.lon:.2f}")
        if r is None:
            self.lbl_step.setText("Sin archivo abierto")
            self._fill_table(None)
            return
        when = self.when()
        if when is None:
            self.lbl_step.setText("hora inválida (YYMMDDHHMM, UTC)")
            self._fill_table(None)
            return
        idx, inside = r.step_for_time(when)
        if idx is None:
            self.lbl_step.setText("el archivo no tiene pasos")
            self._fill_table(None)
            return
        step = r.steps[idx]
        self._step = (idx, step, inside)
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        txt = f"paso [{idx}] {hs} · validez {pq.fmt_dt(step.valid)} UTC"
        if not inside:
            txt += " · fuera de las ventanas: el más cercano"
        self.lbl_step.setText(txt)
        fl = self.fl()
        from ..grib_reader import fl_to_hpa
        self.lbl_fl.setText(f"F{fl:03d} = {fl_to_hpa(fl):.1f} hPa ISA")
        if self.lat is None:
            self.lbl_cell.setText("")
            self._fill_table(None)
            return
        self._res = r.point_query(idx, fl, self.lat, self.lon, self.cell())
        if self._res is None:
            self.lbl_cell.setText("fuera de la grilla del archivo")
        else:
            self.lbl_cell.setText(f"{pq.geodesic_ddmm(self._res['lat'], self._res['lon'])}  "
                                  f"(lat {self._res['lat']:.2f}, lon {self._res['lon']:.2f})")
        self._fill_table(self._res)

    def _fill_table(self, res):
        layers = (None, None, None)
        if res is not None:
            layers = (res.get("upper"), res.get("value"), res.get("lower"))
        for r, layer in enumerate(layers):
            self.table.item(r, 1).setText(pq.layer_name(layer))
            self.table.item(r, 2).setText(pq.wind_text(layer, self._variation))
            self.table.item(r, 3).setText(pq.temp_text(layer))
        fl = self.fl()
        self.table.item(1, 0).setText(f"Nivel F{fl:03d}")
        self.lbl_mode.setText("" if res is None else f"Nivel F{fl:03d}: {pq.mode_text(res)}")
        self.btn_copy.setEnabled(res is not None)
        if self.isVisible():
            self._fit_table()

    def report_text(self):
        idx, step, inside = self._step if self._step else (None, None, False)
        return pq.report_text(self.lat, self.lon, self.ed_time.text().strip(), self.fl(),
                              step, idx, inside, self._res, self._variation, self.cell())

    def copy_text(self):
        if self.lat is None:
            return
        QGuiApplication.clipboard().setText(self.report_text())
