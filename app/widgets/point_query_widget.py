# -*- coding: utf-8 -*-
"""Bloque de consulta de un punto, la sección PUNTO de la ficha del clic
sobre el mapa: los tres campos editables (geodésico, hora de sobrevuelo,
nivel de sobrevuelo) y el perfil vertical de la celda (WindProfileWidget):
todos los niveles del archivo con el color de la velocidad, la barba y los
números, con el FL pedido intercalado (interpolado) y resaltado. Las tres
capas al estilo del FDP (inferior, FL pedido, superior) siguen disponibles
en rows() y en el texto que se copia.

El dato es el del origen (esquina suroeste) de la celda de la grilla que
contiene al punto, como en el FDP. No conoce la ventana principal: recibe
el lector con set_reader y un callable que devuelve la variación magnética
vigente (norte magnético). Los colores y tamaños salen del tema
(QFrame#PointQuery, QLabel#PopupMono, QLabel#PopupHint).
"""
from PyQt6.QtCore import Qt, QRegularExpression, QEvent
from PyQt6.QtGui import QRegularExpressionValidator, QGuiApplication
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox

from .. import point_query as pq
from .wind_profile_widget import WindProfileWidget

ROWS = ("Capa superior", "Nivel pedido", "Capa inferior")


def _mono_label(text=""):
    lab = QLabel(text)
    lab.setObjectName("PopupMono")
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class PointQueryWidget(QFrame):
    def __init__(self, parent=None, variation_fn=None):
        super().__init__(parent)
        self.setObjectName("PointQuery")
        self._reader = None
        self._variation_fn = variation_fn
        self._variation = 0.0
        self.lat = self.lon = None
        self._res = None            # último point_query
        self._step = None           # (índice, GribStep, dentro de ventana)
        self._fl_touched = False
        self._rows = [(n, "—", "—", "—") for n in ROWS]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ── Campos: geodésico · hora · FL, en una fila ──
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_mono_label("Geodésico"))
        self.ed_geo = QLineEdit()
        self.ed_geo.setPlaceholderText("3125S06411W")
        self.ed_geo.setMaxLength(13)
        self.ed_geo.setToolTip("Grados y minutos, DDMM[N|S]DDDMM[E|W]; se consulta al completar")
        self.ed_geo.textChanged.connect(self._geo_edited)
        row.addWidget(self.ed_geo)
        row.addSpacing(10)
        row.addWidget(_mono_label("Hora UTC"))
        self.ed_time = QLineEdit()
        self.ed_time.setPlaceholderText("2510221300")
        self.ed_time.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,12}"), self))
        self.ed_time.setMaxLength(12)
        self.ed_time.setToolTip("Hora de sobrevuelo YYMMDDHHMM (UTC): se usa el paso cuya ventana "
                                "de validez la contiene")
        self.ed_time.textChanged.connect(lambda _t: self.refresh())
        row.addWidget(self.ed_time)
        row.addSpacing(10)
        row.addWidget(_mono_label("FL"))
        self.sp_fl = QSpinBox()
        self.sp_fl.setRange(0, 999)
        self.sp_fl.setSingleStep(10)
        self.sp_fl.setValue(300)
        self.sp_fl.setToolTip("Nivel de sobrevuelo (banda, sin F): si no es un nivel del archivo se "
                              "interpola en ln(p) entre la capa de abajo y la de arriba (no se extrapola)")
        self.sp_fl.valueChanged.connect(self._fl_changed)
        row.addWidget(self.sp_fl)
        row.addStretch(1)
        lay.addLayout(row)

        # ── Origen de celda y paso ──
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.lbl_cell = _mono_label()
        row2.addWidget(self.lbl_cell)
        self.lbl_step = _mono_label()
        row2.addWidget(self.lbl_step)
        row2.addStretch(1)
        lay.addLayout(row2)

        # ── Perfil vertical de la celda ──
        self.profile = WindProfileWidget(self)
        lay.addWidget(self.profile)
        self._column = []
        self.lbl_mode = QLabel("")
        self.lbl_mode.setObjectName("PopupHint")
        lay.addWidget(self.lbl_mode)
        self._fill_rows(None)

    # ── Tamaño de los campos según el tipo de letra vigente ──────────────────

    def _fit_fields(self):
        fm = self.ed_geo.fontMetrics()
        self.ed_geo.setFixedWidth(fm.horizontalAdvance("0" * 11) + 22)
        self.ed_time.setFixedWidth(fm.horizontalAdvance("0" * 12) + 22)
        self.sp_fl.setFixedWidth(fm.horizontalAdvance("000") + 44)

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_fields()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_fields()

    # ── Entradas ─────────────────────────────────────────────────────────────

    def set_reader(self, reader):
        """Lector abierto (o None al cerrar el archivo)."""
        self._reader = reader
        self.refresh()

    def set_defaults(self, when=None, fl=None, force=False):
        """Hora y FL iniciales (el paso y el FL del panel). Sin `force`, sólo
        si el usuario todavía no cargó los suyos (la ventana los conserva);
        con `force` siempre (la ficha del clic muestra lo actual)."""
        if when is not None and (force or not self.ed_time.text().strip()):
            self.ed_time.blockSignals(True)
            self.ed_time.setText(pq.format_overflown_time(when))
            self.ed_time.blockSignals(False)
        if fl is not None and (force or not self._fl_touched):
            self.sp_fl.blockSignals(True)
            self.sp_fl.setValue(int(fl))
            self.sp_fl.blockSignals(False)
            if force:
                self._fl_touched = False
        self.refresh()

    def set_point(self, lat, lon):
        """Punto del clic."""
        self.lat, self.lon = float(lat), float(lon)
        self.ed_geo.blockSignals(True)
        self.ed_geo.setText(pq.geodesic_ddmm(self.lat, self.lon))
        self.ed_geo.blockSignals(False)
        self.refresh()

    def _fl_changed(self, _v):
        self._fl_touched = True
        self.refresh()

    def _geo_edited(self, _text=None):
        """El punto escrito a mano se consulta en cuanto está completo."""
        parsed = pq.parse_geodesic(self.ed_geo.text())
        if parsed is None:
            self.lbl_cell.setText("geodésico: DDMM N/S DDDMM E/W (3125S06411W)")
            return
        self.lat, self.lon = parsed
        self.refresh()

    def fl(self):
        return int(self.sp_fl.value())

    @staticmethod
    def cell():
        return "origin"

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
        self._column = []
        if r is None:
            self.lbl_cell.setText("")
            self.lbl_step.setText("Sin archivo abierto")
            self._fill_rows(None)
            return
        when = self.when()
        if when is None:
            self.lbl_cell.setText("")
            self.lbl_step.setText("hora inválida (YYMMDDHHMM, UTC)")
            self._fill_rows(None)
            return
        idx, inside = r.step_for_time(when)
        if idx is None:
            self.lbl_cell.setText("")
            self.lbl_step.setText("el archivo no tiene pasos")
            self._fill_rows(None)
            return
        step = r.steps[idx]
        self._step = (idx, step, inside)
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        txt = f"paso [{idx}] {hs}  {pq.fmt_dt(step.valid)} UTC"
        if not inside:
            txt += "  (fuera de las ventanas: el más cercano)"
        self.lbl_step.setText(txt)
        if self.lat is None:
            self.lbl_cell.setText("")
            self._fill_rows(None)
            return
        self._res = r.point_query(idx, self.fl(), self.lat, self.lon, self.cell())
        self._column = r.column_query(idx, self.lat, self.lon, self.cell()) or []
        if self._res is None:
            self.lbl_cell.setText("origen de celda: fuera de la grilla del archivo  ·")
        else:
            self.lbl_cell.setText(f"origen de celda {pq.geodesic_ddmm(self._res['lat'], self._res['lon'])} "
                                  f"({self._res['lat']:.2f}, {self._res['lon']:.2f})  ·")
        self._fill_rows(self._res)

    def _fill_rows(self, res):
        from ..grib_reader import fl_to_hpa
        fl = self.fl()
        layers = (None, None, None)
        if res is not None:
            layers = (res.get("upper"), res.get("value"), res.get("lower"))
        names = (ROWS[0], f"Nivel F{fl:03d}", ROWS[2])
        self._rows = [(n, pq.layer_name(l), pq.wind_text(l, self._variation), pq.temp_text(l))
                      for n, l in zip(names, layers)]
        column = self._column if res is not None else []
        self.profile.set_layers(column, value=layers[1] if column else None,
                                variation=self._variation,
                                southern=(self.lat is not None and self.lat < 0))
        self.profile.setVisible(bool(column))
        if res is None:
            self.lbl_mode.setText(f"F{fl:03d} = {fl_to_hpa(fl):.1f} hPa ISA")
        else:
            self.lbl_mode.setText(f"F{fl:03d} = {fl_to_hpa(fl):.1f} hPa ISA · {pq.mode_text(res)}")

    def rows(self):
        """[(capa, nivel, viento, temperatura)] de las tres filas, en texto."""
        return list(self._rows)

    def has_result(self):
        return self._res is not None

    def report_text(self):
        idx, step, inside = self._step if self._step else (None, None, False)
        return pq.report_text(self.lat, self.lon, self.ed_time.text().strip(), self.fl(),
                              step, idx, inside, self._res, self._variation, self.cell(),
                              column=self._column)

    def copy_text(self):
        if self.lat is None:
            return
        QGuiApplication.clipboard().setText(self.report_text())
