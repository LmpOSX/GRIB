# -*- coding: utf-8 -*-
"""Tabla de grillas con nombre (ver areas.Grid): una fila por grilla con
nombre, N/S/W/E, resolución (vacía = la de la fuente), los puntos que
resultan (calculados), habilitada y nota. Las de fábrica (FDP Arg) se
editan y renombran pero no se borran: se ocultan; «Restaurar de fábrica»
las devuelve. La usan la pestaña Áreas / FIR de Preferencias y el diálogo
«Configurar áreas…» de Obtener datos."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView,
)

from .. import areas as A


class GridsEditor(QWidget):
    changed = pyqtSignal()

    COLS = ("Nombre", "Lat norte", "Lat sur", "Lon oeste", "Lon este", "Resolución", "Puntos",
            "Habilitada", "Nota")
    C_NAME, C_N, C_S, C_W, C_E, C_RES, C_PTS, C_EN, C_NOTE = range(9)

    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self._cfg = cfg or {}
        self._fmt = self._cfg.get("areas_coord_format", "decimal")
        self._updating = False
        self._build()
        self.set_grids(A.grids_from_config(self._cfg))

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
        hh.setSectionResizeMode(self.C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(110)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._refresh_buttons)
        lay.addWidget(self.table, 1)
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("StatusWarn")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        lay.addWidget(self.lbl_error)
        row = QHBoxLayout()
        self.btn_add = QPushButton("Agregar grilla")
        self.btn_add.clicked.connect(lambda: self.add_row())
        self.btn_dup = QPushButton("Duplicar")
        self.btn_dup.clicked.connect(self.duplicate_row)
        self.btn_del = QPushButton("Borrar")
        self.btn_del.setToolTip("Una grilla de fábrica no se borra: se oculta con «Habilitada»")
        self.btn_del.clicked.connect(self.delete_row)
        self.btn_restore = QPushButton("Restaurar de fábrica")
        self.btn_restore.setToolTip("Vuelve a los valores iniciales de la grilla de fábrica elegida")
        self.btn_restore.clicked.connect(self.restore_row)
        self.btn_restore_all = QPushButton("Restaurar todas")
        self.btn_restore_all.setToolTip("Las de fábrica vuelven a sus valores; las propias se conservan")
        self.btn_restore_all.clicked.connect(self.restore_all)
        for b in (self.btn_add, self.btn_dup, self.btn_del, self.btn_restore, self.btn_restore_all):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        hint = QLabel("Una grilla con nombre es un recuadro exacto más, si se quiere, la resolución: "
                      "se usa tal cual, sin margen. «Puntos» es lo que resulta a esa resolución "
                      "(el FDP de INDRA exige 51 × 36 a 1°). Aparece como botón «Grilla» en Obtener "
                      "datos, Generar y Exportar a WAFS, y un perfil puede elegirla sola.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

    # ── Filas ────────────────────────────────────────────────────────────────

    def _coord_item(self, value, kind):
        it = QTableWidgetItem(A.format_coord(value, kind, self._fmt))
        it.setData(Qt.ItemDataRole.UserRole, float(value))
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return it

    @staticmethod
    def _res_text(res):
        return "" if res is None else f"{res:g}"

    def _set_row(self, r, grid):
        name = QTableWidgetItem(grid.name)
        name.setData(Qt.ItemDataRole.UserRole, grid.id)
        name.setData(Qt.ItemDataRole.UserRole + 1, bool(grid.builtin))
        if grid.builtin:
            name.setToolTip("De fábrica" + (" (modificada)" if A.grid_is_modified(grid) else ""))
        self.table.setItem(r, self.C_NAME, name)
        self.table.setItem(r, self.C_N, self._coord_item(grid.north, "lat"))
        self.table.setItem(r, self.C_S, self._coord_item(grid.south, "lat"))
        self.table.setItem(r, self.C_W, self._coord_item(grid.west, "lon"))
        self.table.setItem(r, self.C_E, self._coord_item(grid.east, "lon"))
        res = QTableWidgetItem(self._res_text(grid.res))
        res.setData(Qt.ItemDataRole.UserRole, grid.res)
        res.setToolTip("Grados; vacío = la resolución que tenga la fuente")
        res.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(r, self.C_RES, res)
        pts = QTableWidgetItem("")
        pts.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        pts.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(r, self.C_PTS, pts)
        en = QTableWidgetItem("")
        en.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        en.setCheckState(Qt.CheckState.Checked if grid.enabled else Qt.CheckState.Unchecked)
        en.setToolTip("Aparece en el bloque Área de los diálogos")
        self.table.setItem(r, self.C_EN, en)
        self.table.setItem(r, self.C_NOTE, QTableWidgetItem(grid.note))
        self._refresh_points(r)

    def _refresh_points(self, r):
        g = self._row_grid(r)
        n = g.size()
        self.table.item(r, self.C_PTS).setText(f"{n[0]} × {n[1]}" if n else "—")

    def set_grids(self, grids):
        self._updating = True
        try:
            self.table.setRowCount(0)
            for g in grids:
                r = self.table.rowCount()
                self.table.insertRow(r)
                self._set_row(r, g)
        finally:
            self._updating = False
        self._validate()
        self._refresh_buttons()

    def _row_grid(self, r):
        def coord(c):
            it = self.table.item(r, c)
            v = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
            return float(v) if v is not None else 0.0
        name = self.table.item(r, self.C_NAME)
        res = self.table.item(r, self.C_RES)
        return A.Grid(name.data(Qt.ItemDataRole.UserRole) if name else "", name.text() if name else "",
                      coord(self.C_N), coord(self.C_S), coord(self.C_W), coord(self.C_E),
                      res.data(Qt.ItemDataRole.UserRole) if res else None,
                      self.table.item(r, self.C_NOTE).text() if self.table.item(r, self.C_NOTE) else "",
                      bool(name.data(Qt.ItemDataRole.UserRole + 1)) if name else False,
                      self.table.item(r, self.C_EN).checkState() == Qt.CheckState.Checked)

    def grids(self):
        return [self._row_grid(r) for r in range(self.table.rowCount())]

    def errors(self):
        return A.validate_grids(self.grids())

    def values(self):
        return {"grids": A.grids_to_config(self.grids())}

    def set_coord_format(self, fmt):
        self._fmt = fmt
        self._updating = True
        try:
            for r in range(self.table.rowCount()):
                for c, kind in ((self.C_N, "lat"), (self.C_S, "lat"), (self.C_W, "lon"), (self.C_E, "lon")):
                    it = self.table.item(r, c)
                    if it is not None:
                        it.setText(A.format_coord(it.data(Qt.ItemDataRole.UserRole) or 0.0, kind, self._fmt))
        finally:
            self._updating = False

    # ── Botones ──────────────────────────────────────────────────────────────

    def add_row(self, grid=None):
        g = grid or A.Grid(A.new_grid_id(), "Nueva grilla", -20.0, -55.0, -75.0, -25.0, 1.0)
        self._updating = True
        try:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._set_row(r, g)
        finally:
            self._updating = False
        self.table.setCurrentCell(r, self.C_NAME)
        self.table.editItem(self.table.item(r, self.C_NAME))
        self._validate()
        self.changed.emit()
        return r

    def duplicate_row(self):
        r = self.table.currentRow()
        if r < 0:
            return
        g = self._row_grid(r)
        g.id, g.builtin, g.enabled = A.new_grid_id(), False, True
        g.name = f"{g.name} (copia)"
        self.add_row(g)

    def delete_row(self):
        r = self.table.currentRow()
        if r < 0 or self._row_grid(r).builtin:
            return
        self.table.removeRow(r)
        self._validate()
        self.changed.emit()

    def restore_row(self):
        r = self.table.currentRow()
        if r < 0:
            return
        g = self._row_grid(r)
        f = A.factory_grid(g.id) if g.builtin else None
        if f is None:
            return
        f.enabled = g.enabled
        self._updating = True
        try:
            self._set_row(r, f)
        finally:
            self._updating = False
        self._validate()
        self.changed.emit()

    def restore_all(self):
        out = []
        for g in self.grids():
            f = A.factory_grid(g.id) if g.builtin else None
            if f is not None:
                f.enabled = g.enabled
            out.append(f or g)
        self.set_grids(out)
        self.changed.emit()

    def _refresh_buttons(self):
        r = self.table.currentRow()
        g = self._row_grid(r) if r >= 0 else None
        self.btn_dup.setEnabled(g is not None)
        self.btn_del.setEnabled(g is not None and not g.builtin)
        self.btn_restore.setEnabled(g is not None and g.builtin)

    # ── Edición ──────────────────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if self._updating:
            return
        r, c = item.row(), item.column()
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
            elif c == self.C_RES:
                txt = item.text().strip().replace(",", ".")
                if not txt:
                    item.setData(Qt.ItemDataRole.UserRole, None)
                else:
                    try:
                        v = float(txt)
                    except ValueError:
                        self._show_error("Resolución inválida: grados (0,25, 0,5, 1, 1,25) o vacío.")
                        item.setText(self._res_text(item.data(Qt.ItemDataRole.UserRole)))
                        return
                    item.setData(Qt.ItemDataRole.UserRole, v)
                    item.setText(self._res_text(v))
            elif c == self.C_NAME:
                item.setText(item.text().strip())
            if c != self.C_NOTE:
                self._refresh_points(r)
        finally:
            self._updating = False
        self._validate()
        self.changed.emit()

    def _show_error(self, text):
        self.lbl_error.setText(text)
        self.lbl_error.setVisible(bool(text))

    def _validate(self):
        errs = self.errors()
        self._show_error("\n".join(errs[:4]) if errs else "")
        return not errs
