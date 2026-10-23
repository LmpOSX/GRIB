# -*- coding: utf-8 -*-
"""Bloque «Archivo a guardar»: las mismas opciones en Preferencias (valores
por defecto), Obtener datos, Generar GRIB y Guardar como…: viento, decimales
del viento y de la temperatura, etiqueta de capa (por Nivel), empaquetado y
centro generador. `values()` devuelve {wind, dec_wind, dec_temp, label,
packing, centre}; `config_values()` lo mismo con el prefijo `save_`."""
from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox

from .. import fl_table as flt
from .. import grib_encode as ge
from .. import wind_format as wfm


class SaveOptionsBox(QWidget):
    def __init__(self, parent=None, cfg=None, show_decimals=True, show_label=True,
                 show_packing=True, show_centre=True, compact=False, rows=False):
        """`rows`: disposición apaisada (tres pares rótulo + combo por fila)
        para los diálogos de descarga y generación; si no, un renglón por
        opción, como en Preferencias y Guardar como."""
        super().__init__(parent)
        self._cfg = cfg or {}
        self._build(show_decimals, show_label, show_packing, show_centre, compact, rows)
        self.set_values(ge.options_from_config(self._cfg))

    def _combos(self):
        self.cb_wind = QComboBox()
        for key, text in wfm.FORMATS:
            self.cb_wind.addItem(text, key)
        self.cb_wind.setToolTip("Los modelos publican las componentes U (este) y V (norte). Con "
                                "«Dirección y velocidad» cada par U/V se graba como WDIR (grados "
                                "verdaderos, de dónde sopla) y WIND (m/s). El visor lee los dos; el "
                                "WAFS operativo lleva U/V.")
        self.cb_dec_wind = QComboBox()
        self.cb_dec_temp = QComboBox()
        for cb in (self.cb_dec_wind, self.cb_dec_temp):
            for key, text in ge.DECIMALS:
                cb.addItem(text, key)
            cb.setToolTip("Decimales con los que se graba el campo (factor decimal D con escala "
                          "binaria 0, así se respetan exactamente). «Como el origen» no toca el "
                          "empaquetado del modelo. Un campo constante se graba exacto.")
        self.cb_label = QComboBox()
        for key, text in flt.LABELS:
            self.cb_label.addItem(text, key)
        self.cb_label.setToolTip("Presión que se graba como capa de cada FL en un archivo por Nivel: "
                                 "la del modo de etiquetado (nominal en INDRA/OACI/OACI56, ISA en WAFS), "
                                 "o forzada. El dato está siempre en la presión ISA exacta. En un "
                                 "archivo de capas crudas no se toca.")
        self.cb_packing = QComboBox()
        for key, text in ge.PACKINGS:
            self.cb_packing.addItem(text, key)
        self.cb_packing.setToolTip("Simple: valor de referencia más N bits por punto (lo habitual). "
                                   "IEEE: un float de 32 bits por celda, sin escalas; ocupa más y "
                                   "cualquier lector lo decodifica tal cual.")
        self.cb_centre = QComboBox()
        for key, text in ge.CENTRES:
            self.cb_centre.addItem(text, key)
        self.cb_centre.setToolTip("Centro generador de la sección 1 (tabla C-11). «Sin centro» graba "
                                  "65535, el valor faltante: el archivo no es de un modelo.")

    def _build_rows(self, show_decimals, show_label, show_packing, show_centre, compact):
        """Apaisado: pares (rótulo, combo) de a tres por fila, sólo los visibles."""
        self._combos()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        pairs = [("Viento", self.cb_wind, True),
                 ("Decimales viento", self.cb_dec_wind, show_decimals),
                 ("temperatura", self.cb_dec_temp, show_decimals),
                 ("Etiqueta de capa", self.cb_label, show_label),
                 ("Empaquetado", self.cb_packing, show_packing),
                 ("Centro", self.cb_centre, show_centre)]
        self._dec_widgets, self._label_widgets, self._packing_widgets, self._centre_widgets = [], [], [], []
        k = 0
        for text, cb, shown in pairs:
            lbl = QLabel(text)
            lbl.setObjectName("FieldNote" if compact else "")
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
            if cb in (self.cb_dec_wind, self.cb_dec_temp):
                self._dec_widgets += [lbl, cb]
            elif cb is self.cb_label:
                self._label_widgets = [lbl, cb]
            elif cb is self.cb_packing:
                self._packing_widgets = [lbl, cb]
            elif cb is self.cb_centre:
                self._centre_widgets = [lbl, cb]
            lbl.setVisible(shown)
            cb.setVisible(shown)
            if not shown:
                continue
            g.addWidget(lbl, k // 3, (k % 3) * 2)
            g.addWidget(cb, k // 3, (k % 3) * 2 + 1)
            k += 1
        for c in (1, 3, 5):
            g.setColumnStretch(c, 1)

    def _build(self, show_decimals, show_label, show_packing, show_centre, compact, rows):
        if rows:
            self._build_rows(show_decimals, show_label, show_packing, show_centre, compact)
            return
        self._combos()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        row = 0

        def label(text):
            lbl = QLabel(text)
            lbl.setObjectName("FieldNote" if compact else "")
            return lbl

        g.addWidget(label("Viento"), row, 0)
        g.addWidget(self.cb_wind, row, 1, 1, 3)
        row += 1

        g.addWidget(label("Decimales del viento"), row, 0)
        g.addWidget(self.cb_dec_wind, row, 1)
        g.addWidget(label("de la temperatura"), row, 2)
        g.addWidget(self.cb_dec_temp, row, 3)
        self._dec_widgets = [g.itemAtPosition(row, c).widget() for c in range(4)]
        row += 1

        g.addWidget(label("Etiqueta de capa"), row, 0)
        g.addWidget(self.cb_label, row, 1, 1, 3)
        self._label_widgets = [g.itemAtPosition(row, 0).widget(), self.cb_label]
        row += 1

        g.addWidget(label("Empaquetado"), row, 0)
        g.addWidget(self.cb_packing, row, 1, 1, 3)
        self._packing_widgets = [g.itemAtPosition(row, 0).widget(), self.cb_packing]
        row += 1

        g.addWidget(label("Centro generador"), row, 0)
        g.addWidget(self.cb_centre, row, 1, 1, 3)
        self._centre_widgets = [g.itemAtPosition(row, 0).widget(), self.cb_centre]
        g.setColumnStretch(4, 1)

        for w in self._dec_widgets:
            w.setVisible(show_decimals)
        for w in self._label_widgets:
            w.setVisible(show_label)
        for w in self._packing_widgets:
            w.setVisible(show_packing)
        for w in self._centre_widgets:
            w.setVisible(show_centre)

    # ── Valores ──────────────────────────────────────────────────────────

    def values(self):
        return ge.normalize({"wind": self.cb_wind.currentData(),
                             "dec_wind": self.cb_dec_wind.currentData(),
                             "dec_temp": self.cb_dec_temp.currentData(),
                             "label": self.cb_label.currentData(),
                             "packing": self.cb_packing.currentData(),
                             "centre": self.cb_centre.currentData()})

    def config_values(self):
        return {"save_" + k: v for k, v in self.values().items()}

    def set_values(self, opts):
        o = ge.normalize(opts)
        self.cb_wind.setCurrentIndex(max(0, self.cb_wind.findData(o["wind"])))
        self.cb_dec_wind.setCurrentIndex(max(0, self.cb_dec_wind.findData(o["dec_wind"])))
        self.cb_dec_temp.setCurrentIndex(max(0, self.cb_dec_temp.findData(o["dec_temp"])))
        self.cb_label.setCurrentIndex(max(0, self.cb_label.findData(o["label"])))
        self.cb_packing.setCurrentIndex(max(0, self.cb_packing.findData(o["packing"])))
        self.cb_centre.setCurrentIndex(max(0, self.cb_centre.findData(o["centre"])))

    def wind_format(self):
        return wfm.normalize(self.cb_wind.currentData())

    def set_labeled(self, labeled, note=None):
        """La etiqueta de capa sólo tiene sentido en un archivo por Nivel."""
        for w in self._label_widgets:
            w.setEnabled(bool(labeled))
        if note is not None:
            self.cb_label.setToolTip(note)
