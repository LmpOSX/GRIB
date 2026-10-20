# -*- coding: utf-8 -*-
"""Formulario armado automáticamente a partir de los `Param` de una fuente.
Lo usan el diálogo de configuración de la fuente (valores por defecto) y el
de descarga (valores de esa descarga), así sumar una fuente no toca la
interfaz."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit,
)


class ParamsForm(QWidget):
    changed = pyqtSignal()

    def __init__(self, params, values=None, parent=None, columns=1):
        """`columns` > 1 pone varios parámetros (rótulo y campo) por fila;
        los booleanos ocupan una fila entera."""
        super().__init__(parent)
        self._params = list(params)
        self._widgets = {}
        self._columns = max(1, int(columns))
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self._grid = grid
        row = col = 0
        for p in self._params:
            w = self._make(p)
            if p.help:
                w.setToolTip(p.help)
            if p.kind == "bool":
                if col:
                    row, col = row + 1, 0
                grid.addWidget(w, row, 0, 1, 2 * self._columns)
                row += 1
            else:
                lbl = QLabel(p.label)
                if p.help:
                    lbl.setToolTip(p.help)
                grid.addWidget(lbl, row, 2 * col)
                grid.addWidget(w, row, 2 * col + 1)
                col += 1
                if col >= self._columns:
                    row, col = row + 1, 0
            self._widgets[p.key] = w
        self._rows = row + (1 if col else 0)
        for c in range(self._columns):
            grid.setColumnStretch(2 * c + 1, 1)
        if values:
            self.set_values(values)

    def add_right(self, widget):
        """Un widget ajeno al formulario en su última fila, a la derecha (el
        diálogo de descarga pone ahí «Mostrar el área en el mapa»)."""
        self._grid.addWidget(widget, max(0, self._rows - 1), 2 * self._columns,
                             alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _make(self, p):
        if p.kind == "choice":
            w = QComboBox()
            for val, text in p.choices:
                w.addItem(text, val)
            w.setCurrentIndex(max(0, w.findData(p.default)))
            w.currentIndexChanged.connect(lambda _i: self.changed.emit())
        elif p.kind == "bool":
            w = QCheckBox(p.label)
            w.setChecked(bool(p.default))
            w.toggled.connect(lambda _v: self.changed.emit())
        elif p.kind == "int":
            w = QSpinBox()
            w.setRange(p.lo if p.lo is not None else -10**9, p.hi if p.hi is not None else 10**9)
            w.setValue(int(p.default))
            w.valueChanged.connect(lambda _v: self.changed.emit())
        elif p.kind == "float":
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(p.lo if p.lo is not None else -1e9, p.hi if p.hi is not None else 1e9)
            w.setValue(float(p.default))
            w.valueChanged.connect(lambda _v: self.changed.emit())
        else:
            w = QLineEdit(str(p.default or ""))
            w.textChanged.connect(lambda _t: self.changed.emit())
        return w

    def values(self):
        out = {}
        for p in self._params:
            w = self._widgets[p.key]
            if p.kind == "choice":
                out[p.key] = w.currentData()
            elif p.kind == "bool":
                out[p.key] = w.isChecked()
            elif p.kind in ("int", "float"):
                out[p.key] = w.value()
            else:
                out[p.key] = w.text()
        return out

    def set_values(self, values):
        self.blockSignals(True)
        try:
            for p in self._params:
                if p.key not in values:
                    continue
                w = self._widgets[p.key]
                v = values[p.key]
                if p.kind == "choice":
                    idx = w.findData(v)
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif p.kind == "bool":
                    w.setChecked(bool(v))
                elif p.kind in ("int", "float"):
                    w.setValue(v)
                else:
                    w.setText(str(v))
        finally:
            self.blockSignals(False)
        self.changed.emit()

    def widget(self, key):
        return self._widgets.get(key)
