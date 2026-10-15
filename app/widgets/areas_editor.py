# -*- coding: utf-8 -*-
"""Widgets de las áreas de descarga (ver app/areas.py):

* `CoordEdit`: campo de latitud o longitud que acepta grados decimales con
  signo o grados-minutos con hemisferio y muestra el valor en el formato
  elegido en la configuración.
* `AreasEditor`: tabla editable con una fila por área (código, nombre,
  N/S/W/E, habilitada, a verificar), alta y baja de filas, margen, formato,
  exportar/importar y «copiar extremos de la capa FIR». Lo usa la pestaña
  Áreas / FIR de Preferencias y el diálogo de descarga.
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QCheckBox, QDoubleSpinBox, QComboBox, QFileDialog,
    QMessageBox, QAbstractItemView, QHeaderView,
)

from .. import areas as A


class CoordEdit(QLineEdit):
    """Latitud o longitud; `value()` en grados decimales, texto en el
    formato elegido (`set_format`). Un texto inválido vuelve al valor
    anterior y se avisa por `invalid`."""
    value_changed = pyqtSignal(float)
    invalid = pyqtSignal(str)

    def __init__(self, kind="lat", value=0.0, fmt="decimal", parent=None):
        super().__init__(parent)
        self.kind = kind
        self._fmt = fmt
        self._value = float(value)
        self.setMaximumWidth(120)
        self.setPlaceholderText("-34.03 o 34°02'S" if kind == "lat" else "-58.5 o 058°30'W")
        self.editingFinished.connect(self._commit)
        self._render()

    def value(self):
        return self._value

    def set_value(self, v):
        self._value = float(v)
        self._render()

    def set_format(self, fmt):
        self._fmt = fmt
        self._render()

    def _render(self):
        self.setText(A.format_coord(self._value, self.kind, self._fmt))

    def _commit(self):
        try:
            v = A.parse_coord(self.text(), self.kind)
        except A.CoordError as exc:
            self.invalid.emit(str(exc))
            self._render()
            return
        changed = abs(v - self._value) > 1e-9
        self._value = v
        self._render()
        if changed:
            self.value_changed.emit(v)


class AreasEditor(QWidget):
    """Tabla de áreas. `areas()` devuelve la lista (Area) y `errors()` los
    mensajes de validación; `changed` se emite ante cualquier edición."""
    changed = pyqtSignal()

    COLS = ("Código", "Nombre", "Lat norte", "Lat sur", "Lon oeste", "Lon este", "Habilitada",
            "A verificar")
    C_CODE, C_NAME, C_N, C_S, C_W, C_E, C_EN, C_VER = range(8)

    def __init__(self, cfg=None, parent=None, regions_fn=None):
        super().__init__(parent)
        self._cfg = cfg or {}
        self._fmt = self._cfg.get("areas_coord_format", "decimal")
        self._updating = False
        self._regions_fn = regions_fn     # callable → dict código → fir.FirRegion (capa FIR)
        self._build()
        self.set_areas(A.areas_from_config(self._cfg))

    # ── Construcción ─────────────────────────────────────────────────────────

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.C_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(190)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("StatusWarn")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        lay.addWidget(self.lbl_error)

        row = QHBoxLayout()
        self.btn_add = QPushButton("Agregar área")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del = QPushButton("Borrar")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_reset = QPushButton("Las cinco FIR por defecto")
        self.btn_reset.setToolTip("Vuelve a cargar SARR, SACF, SAMF, SAEF y SAVF con los valores "
                                  "iniciales (a verificar contra el AIP ENR 2.1)")
        self.btn_reset.clicked.connect(self.reset_defaults)
        self.btn_from_fir = QPushButton("Extremos de la capa FIR")
        self.btn_from_fir.setToolTip("Copia a la fila seleccionada los extremos del polígono de esa "
                                     "FIR (fuente de la capa FIR: VATSpy u otra; no es oficial)")
        self.btn_from_fir.clicked.connect(self.fill_from_fir)
        self.btn_from_fir.setVisible(self._regions_fn is not None)
        for b in (self.btn_add, self.btn_del, self.btn_reset, self.btn_from_fir):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Margen de seguridad"), 0, 0)
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 10.0)
        self.spin_margin.setDecimals(2)
        self.spin_margin.setSingleStep(0.25)
        self.spin_margin.setSuffix("°")
        self.spin_margin.setValue(float(self._cfg.get("areas_margin_deg", A.DEFAULT_MARGIN_DEG)))
        self.spin_margin.setToolTip("Se suma por fuera a cada límite al usar el área; no se guarda "
                                    "sumado en la tabla")
        self.spin_margin.valueChanged.connect(lambda _v: self.changed.emit())
        g.addWidget(self.spin_margin, 0, 1)
        g.addWidget(QLabel("Formato de coordenadas"), 0, 2)
        self.cb_format = QComboBox()
        for key, text in A.COORD_FORMATS:
            self.cb_format.addItem(text, key)
        self.cb_format.setCurrentIndex(max(0, self.cb_format.findData(self._fmt)))
        self.cb_format.currentIndexChanged.connect(self._on_format_changed)
        g.addWidget(self.cb_format, 0, 3)
        g.setColumnStretch(4, 1)
        lay.addLayout(g)

        row = QHBoxLayout()
        self.btn_export = QPushButton("Exportar tabla…")
        self.btn_export.clicked.connect(self.export_table)
        self.btn_import = QPushButton("Importar tabla…")
        self.btn_import.clicked.connect(self.import_table)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_import)
        row.addStretch()
        lay.addLayout(row)
        hint = QLabel("Las latitudes y longitudes las cargás vos: grados decimales con signo (S y W "
                      "negativos) o grados-minutos con hemisferio (22°15'S, 06240W). Las cinco FIR "
                      "argentinas vienen precargadas «a verificar contra AIP ENR 2.1». Norte > sur y "
                      "oeste < este.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

    # ── Filas ────────────────────────────────────────────────────────────────

    def _coord_item(self, value, kind):
        it = QTableWidgetItem(A.format_coord(value, kind, self._fmt))
        it.setData(Qt.ItemDataRole.UserRole, float(value))
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return it

    def _check_item(self, on, tip=""):
        it = QTableWidgetItem("")
        it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable)
        it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        if tip:
            it.setToolTip(tip)
        return it

    def _set_row(self, r, area):
        self.table.setItem(r, self.C_CODE, QTableWidgetItem(area.code))
        self.table.setItem(r, self.C_NAME, QTableWidgetItem(area.name))
        self.table.setItem(r, self.C_N, self._coord_item(area.north, "lat"))
        self.table.setItem(r, self.C_S, self._coord_item(area.south, "lat"))
        self.table.setItem(r, self.C_W, self._coord_item(area.west, "lon"))
        self.table.setItem(r, self.C_E, self._coord_item(area.east, "lon"))
        self.table.setItem(r, self.C_EN, self._check_item(area.enabled,
                                                          "Aparece en el bloque Área de «Obtener datos…»"))
        self.table.setItem(r, self.C_VER, self._check_item(area.verify, A.VERIFY_NOTE))

    def set_areas(self, areas):
        self._updating = True
        try:
            self.table.setRowCount(0)
            for a in areas:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self._set_row(r, a)
        finally:
            self._updating = False
        self._validate()

    def _row_area(self, r):
        def coord(c):
            it = self.table.item(r, c)
            v = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
            return float(v) if v is not None else 0.0
        return A.Area(
            (self.table.item(r, self.C_CODE).text() if self.table.item(r, self.C_CODE) else ""),
            (self.table.item(r, self.C_NAME).text() if self.table.item(r, self.C_NAME) else ""),
            coord(self.C_N), coord(self.C_S), coord(self.C_W), coord(self.C_E),
            self.table.item(r, self.C_EN).checkState() == Qt.CheckState.Checked,
            self.table.item(r, self.C_VER).checkState() == Qt.CheckState.Checked)

    def areas(self):
        return [self._row_area(r) for r in range(self.table.rowCount())]

    def margin(self):
        return float(self.spin_margin.value())

    def coord_format(self):
        return self.cb_format.currentData() or "decimal"

    def errors(self):
        return A.validate_areas(self.areas())

    def values(self):
        """Claves de configuración que administra."""
        return {"areas": A.areas_to_config(self.areas()), "areas_margin_deg": self.margin(),
                "areas_coord_format": self.coord_format()}

    def add_row(self, code="", name=""):
        self._updating = True
        try:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._set_row(r, A.Area(code or "", name or "", -20.0, -40.0, -75.0, -50.0,
                                    enabled=True, verify=False))
        finally:
            self._updating = False
        self.table.setCurrentCell(r, self.C_CODE)
        self.table.editItem(self.table.item(r, self.C_CODE))
        self._validate()
        self.changed.emit()
        return r

    def delete_row(self):
        r = self.table.currentRow()
        if r < 0:
            return
        self.table.removeRow(r)
        self._validate()
        self.changed.emit()

    def reset_defaults(self):
        cur = {a.code: a for a in self.areas()}
        out = []
        for d in A.DEFAULT_AREAS:
            out.append(A.Area.from_dict(d))
        for code, a in cur.items():
            if code not in A.ARGENTINA_CODES:
                out.append(a)
        self.set_areas(out)
        self.changed.emit()

    def fill_from_fir(self):
        """Copia los extremos del polígono de la capa FIR a la fila actual."""
        r = self.table.currentRow()
        if r < 0 or self._regions_fn is None:
            return
        code = self._row_area(r).code
        try:
            regions = self._regions_fn() or {}
        except Exception:
            regions = {}
        region = regions.get(code)
        ext = region.extremes() if region is not None else None
        if ext is None:
            QMessageBox.information(self, "Áreas", f"La capa FIR no tiene un polígono para {code or '(sin código)'}.")
            return
        a = self._row_area(r)
        a.north, a.south, a.west, a.east = ext["norte"], ext["sur"], ext["oeste"], ext["este"]
        a.verify = not bool(getattr(region, "official", False))
        if not a.name:
            a.name = region.name
        self._updating = True
        try:
            self._set_row(r, a)
        finally:
            self._updating = False
        self._validate()
        self.changed.emit()

    # ── Edición ──────────────────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._updating:
            return
        c = item.column()
        self._updating = True
        try:
            if c in (self.C_N, self.C_S, self.C_W, self.C_E):
                kind = "lat" if c in (self.C_N, self.C_S) else "lon"
                try:
                    v = A.parse_coord(item.text(), kind)
                except A.CoordError as exc:
                    old = item.data(Qt.ItemDataRole.UserRole)
                    self._show_error(f"Coordenada inválida: {exc}")
                    item.setText(A.format_coord(old if old is not None else 0.0, kind, self._fmt))
                    return
                item.setData(Qt.ItemDataRole.UserRole, v)
                item.setText(A.format_coord(v, kind, self._fmt))
            elif c == self.C_CODE:
                item.setText(item.text().strip().upper()[:4])
        finally:
            self._updating = False
        self._validate()
        self.changed.emit()

    def _on_format_changed(self, _i):
        self._fmt = self.coord_format()
        self._updating = True
        try:
            for r in range(self.table.rowCount()):
                for c, kind in ((self.C_N, "lat"), (self.C_S, "lat"), (self.C_W, "lon"), (self.C_E, "lon")):
                    it = self.table.item(r, c)
                    if it is not None:
                        it.setText(A.format_coord(it.data(Qt.ItemDataRole.UserRole) or 0.0, kind, self._fmt))
        finally:
            self._updating = False
        self.changed.emit()

    def _show_error(self, text):
        self.lbl_error.setText(text)
        self.lbl_error.setVisible(bool(text))

    def _validate(self):
        errs = self.errors()
        self._show_error("\n".join(errs[:4]) if errs else "")
        return not errs

    # ── Exportar / importar ──────────────────────────────────────────────────

    def export_table(self):
        start = os.path.join(self._cfg.get("last_directory") or os.path.expanduser("~"), "areas_fir.json")
        path, _f = QFileDialog.getSaveFileName(self, "Exportar tabla de áreas", start,
                                               "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            A.export_areas(path, self.areas(), margin=self.margin())
        except OSError as exc:
            QMessageBox.critical(self, "Exportar tabla", f"No se pudo escribir:\n{exc}")

    def import_table(self):
        start = self._cfg.get("last_directory") or os.path.expanduser("~")
        path, _f = QFileDialog.getOpenFileName(self, "Importar tabla de áreas", start,
                                               "Tablas (*.json *.csv);;Todos (*)")
        if not path:
            return
        self.load_file(path)

    def load_file(self, path):
        try:
            areas, margin = A.import_areas(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Importar tabla", str(exc))
            return False
        self.set_areas(areas)
        if margin is not None:
            self.spin_margin.setValue(float(margin))
        self.changed.emit()
        return True
