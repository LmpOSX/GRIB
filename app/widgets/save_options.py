# -*- coding: utf-8 -*-
"""Bloque «Archivo a guardar»: las mismas opciones en Preferencias (valores
por defecto), Obtener datos, Exportar a WAFS, Generar GRIB y Guardar como…:
perfil (NOAA GFS, WAFS WAFC Washington, WAFS WAFC London, FDP), regrillado,
viento, decimales del viento y de la temperatura, etiqueta de capa (por
Nivel), empaquetado y centro y subcentro generadores, versión de tablas, orden de las celdas,
filas intercaladas y primera longitud de una grilla global. `values()` devuelve
{wind, dec_wind, dec_temp, label, packing, centre, scan, rows, lons, regrid,
tables}
más el motor del regrillado; `config_values()` las del bloque con el
prefijo `save_`."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QGridLayout, QLabel, QComboBox, QSpinBox

from .. import fl_table as flt
from .. import grib_encode as ge
from ..grib_centres import CENTRES_C11, centre_text
from .. import wind_format as wfm


class SaveOptionsBox(QWidget):
    changed = pyqtSignal()              # cualquier opción del bloque
    profile_chosen = pyqtSignal(str)    # el usuario eligió un perfil (no «Personalizado»)

    def __init__(self, parent=None, cfg=None, show_decimals=True, show_label=True,
                 show_packing=True, show_centre=True, compact=False, rows=False,
                 show_regrid=True):
        """`rows`: disposición apaisada (tres pares rótulo + combo por fila)
        para los diálogos de descarga y generación; si no, un renglón por
        opción, como en Preferencias y Guardar como. Sin `show_regrid`
        (Generar GRIB, donde la grilla la define la tabla) no se regrilla."""
        super().__init__(parent)
        self._cfg = cfg or {}
        self._show_regrid = show_regrid
        self._show_centre = show_centre
        self._build(show_decimals, show_label, show_packing, show_centre, compact, rows)
        self.set_values(ge.options_from_config(self._cfg))
        # Arranca en «Personalizado» aunque los valores guardados coincidan
        # con un perfil: un perfil se muestra sólo cuando se lo elige
        self.cb_profile.setCurrentIndex(0)
        for cb in self._option_combos():
            if isinstance(cb, QSpinBox):
                cb.valueChanged.connect(self._on_option_changed)
            else:
                cb.currentIndexChanged.connect(self._on_option_changed)
        self.cb_profile.activated.connect(self._on_profile)

    def _option_combos(self):
        return (self.cb_regrid, self.cb_wind, self.cb_dec_wind, self.cb_dec_temp, self.cb_label,
                self.cb_packing, self.cb_centre, self.sp_sub_centre, self.cb_tables, self.cb_scan, self.cb_rows,
                self.cb_lons)

    def _combos(self):
        self.cb_profile = QComboBox()
        self.cb_profile.addItem("Personalizado", None)
        for key, text, _vals in ge.PROFILES:
            self.cb_profile.addItem(text, key)
        self.cb_profile.setToolTip("Carga de una vez los valores de un formato conocido; después se "
                                   "puede cambiar cualquiera (queda «Personalizado»). NOAA GFS: U/V, "
                                   "filas de norte a sur, desde Greenwich. WAFS WAFC Washington y WAFS "
                                   "WAFC London: 0,25° con la etiqueta ISA exacta; Washington desde "
                                   "180°W (−180…180) y London desde Greenwich (0…360). FDP: como los "
                                   "boletines GTS YUXM/YTXJ de EGRR: 1,25°, de sur a norte, desde "
                                   "Greenwich, 1 decimal, JPEG 2000 sin pérdida, tablas versión 4 y "
                                   "etiqueta nominal (OACI17, OACI56, INDRA14). Ningún perfil cambia "
                                   "el centro: dice quién hizo el dato.")
        self.cb_regrid = QComboBox()
        for key, text in ge.REGRIDS:
            self.cb_regrid.addItem(text, key)
        self.cb_regrid.setToolTip(self._regrid_tip())
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
        for code, _abbr, _desc in CENTRES_C11:
            self.cb_centre.addItem(centre_text(code), str(code))
        self.cb_centre.setMaxVisibleItems(20)
        self.cb_centre.setToolTip("Centro generador de la sección 1 (tabla común C-11 de la OMM): "
                                  "7 NCEP, 41 Buenos Aires, 74 Met Office (EGRR), 98 ECMWF… «Sin "
                                  "centro» graba 65535, el valor faltante: el archivo no es de un "
                                  "modelo. Ojo: el centro dice quién produjo el dato.")
        self.sp_sub_centre = QSpinBox()
        self.sp_sub_centre.setRange(-1, 65535)
        self.sp_sub_centre.setSpecialValueText("Como el origen")
        self.sp_sub_centre.setToolTip("Subcentro de la sección 1: lo asigna cada centro (no hay tabla "
                                      "común; los boletines de WAFC London graban 5). 65535 es el "
                                      "valor faltante. «Como el origen» no lo toca.")
        self.cb_tables = QComboBox()
        for key, text in ge.TABLES:
            self.cb_tables.addItem(text, key)
        self.cb_tables.setToolTip("Versión de la tabla maestra (sección 1): con qué edición de las "
                                  "tablas OMM se codificó el archivo. El GFS graba 2, los boletines "
                                  "GTS de WAFC London 4 y Exportar a WAFS 25; U, V y T son los mismos "
                                  "en todas. Al fijarla, los parámetros estándar quedan sin tablas "
                                  "locales (0). El centro y el subcentro no se tocan.")
        self.cb_scan = QComboBox()
        for key, text in ge.SCANS:
            self.cb_scan.addItem(text, key)
        self.cb_scan.setToolTip("Orden de las celdas en el archivo (modo de barrido de la sección 3): "
                                "filas de norte a sur o de sur a norte y, dentro de cada fila, de "
                                "oeste a este o de este a oeste. El GFS y el WAFS de WAFC Washington van N→S, "
                                "O→E; el WAFS de WAFC London, S→N, O→E (los lectores deben mirar el "
                                "octeto 72 de la sección 3, no suponerlo). Se reordenan los valores y se "
                                "corrigen las esquinas de la grilla; el dato no cambia.")
        self.cb_rows = QComboBox()
        for key, text in ge.ROWS:
            self.cb_rows.addItem(text, key)
        self.cb_rows.setToolTip("Filas todas en el mismo sentido, o intercaladas (bustrofedón, bit 4 del "
                                "barrido): la segunda fila corre al revés que la primera, y así. El "
                                "visor las lee en los dos casos.")
        self.cb_lons = QComboBox()
        for key, text in ge.LONS:
            self.cb_lons.addItem(text, key)
        self.cb_lons.setToolTip("Dónde empieza una grilla que da la vuelta al mundo: en 180°W (como el "
                                "GFS recortado a −180…180) o en Greenwich, 0…358,75 (como el WAFS de WAFC "
                                "London). Se rotan las columnas; el dato no cambia. En una grilla "
                                "regional no hace nada: GRIB2 graba siempre las longitudes de 0 a 360.")

    def _regrid_tip(self):
        from ..regrid import wgrib2_can_regrid
        if self._cfg.get("engine") == "wgrib2" and wgrib2_can_regrid(self._cfg.get("wgrib2_path", "")):
            how = "con wgrib2 -new_grid (bilineal de NCEPLIBS-ip; el viento como vector)"
        else:
            how = "con el bilineal propio (ecCodes)"
            if self._cfg.get("engine") == "wgrib2":
                how += "; este wgrib2 no tiene la interpolación (IPOLATES)"
        return ("Interpolación bilineal a puntos múltiplos de la resolución; una grilla global da la "
                "vuelta completa (a 1,25°: 288 × 145). Se hace antes que lo demás. Regrilla " + how +
                ", según Preferencias ▸ motor de lectura. El GFS se publica a 0,25, 0,50 y 1,00°: "
                "para 1,25° conviene bajarlo a 0,25°.")

    def _build_rows(self, show_decimals, show_label, show_packing, show_centre, compact):
        """Apaisado: pares (rótulo, combo) de a tres por fila, sólo los visibles."""
        self._combos()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        pairs = [("Perfil", self.cb_profile, True),
                 ("Regrillar", self.cb_regrid, self._show_regrid),
                 ("Viento", self.cb_wind, True),
                 ("Decimales viento", self.cb_dec_wind, show_decimals),
                 ("temperatura", self.cb_dec_temp, show_decimals),
                 ("Etiqueta de capa", self.cb_label, show_label),
                 ("Empaquetado", self.cb_packing, show_packing),
                 ("Centro", self.cb_centre, show_centre),
                 ("Subcentro", self.sp_sub_centre, show_centre),
                 ("Tablas", self.cb_tables, True),
                 ("Orden de las celdas", self.cb_scan, True),
                 ("filas", self.cb_rows, True),
                 ("Longitudes", self.cb_lons, True)]
        self._dec_widgets, self._label_widgets, self._packing_widgets, self._centre_widgets = [], [], [], []
        k = 0
        for text, cb, shown in pairs:
            lbl = QLabel(text)
            lbl.setObjectName("FieldNote" if compact else "")
            if isinstance(cb, QComboBox):
                cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                cb.setMinimumContentsLength(12)
            if cb in (self.cb_dec_wind, self.cb_dec_temp):
                self._dec_widgets += [lbl, cb]
            elif cb is self.cb_label:
                self._label_widgets = [lbl, cb]
            elif cb is self.cb_packing:
                self._packing_widgets = [lbl, cb]
            elif cb in (self.cb_centre, self.sp_sub_centre):
                self._centre_widgets += [lbl, cb]
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

        g.addWidget(label("Perfil"), row, 0)
        g.addWidget(self.cb_profile, row, 1, 1, 3)
        row += 1

        lbl = label("Regrillar")
        g.addWidget(lbl, row, 0)
        g.addWidget(self.cb_regrid, row, 1, 1, 3)
        lbl.setVisible(self._show_regrid)
        self.cb_regrid.setVisible(self._show_regrid)
        row += 1

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
        g.addWidget(self.cb_centre, row, 1)
        g.addWidget(label("subcentro"), row, 2)
        g.addWidget(self.sp_sub_centre, row, 3)
        self._centre_widgets = [g.itemAtPosition(row, c).widget() for c in range(4)]
        row += 1

        g.addWidget(label("Versión de tablas"), row, 0)
        g.addWidget(self.cb_tables, row, 1, 1, 3)
        row += 1

        g.addWidget(label("Orden de las celdas"), row, 0)
        g.addWidget(self.cb_scan, row, 1)
        g.addWidget(label("filas"), row, 2)
        g.addWidget(self.cb_rows, row, 3)
        row += 1

        g.addWidget(label("Longitudes"), row, 0)
        g.addWidget(self.cb_lons, row, 1, 1, 3)
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
        """Lo elegido, con el motor del regrillado de Preferencias. Sin el
        combo de regrillado a la vista no se regrilla; sin el del centro, no
        se toca el centro."""
        o = self._combo_values()
        if not self._show_regrid:
            o["regrid"] = "origen"
        if not self._show_centre:                 # Generar: siempre 65535, sin subcentro propio
            o["centre"], o["sub_centre"] = "origen", None
        for k in ("engine", "wgrib2_path"):
            if self._cfg.get(k):
                o[k] = self._cfg[k]
        return o

    def _combo_values(self):
        return ge.normalize({"regrid": self.cb_regrid.currentData(),
                             "wind": self.cb_wind.currentData(),
                             "dec_wind": self.cb_dec_wind.currentData(),
                             "dec_temp": self.cb_dec_temp.currentData(),
                             "label": self.cb_label.currentData(),
                             "packing": self.cb_packing.currentData(),
                             "centre": self.cb_centre.currentData(),
                             "sub_centre": self.sp_sub_centre.value(),
                             "tables": self.cb_tables.currentData(),
                             "scan": self.cb_scan.currentData(),
                             "rows": self.cb_rows.currentData(),
                             "lons": self.cb_lons.currentData()})

    def config_values(self):
        o = self._combo_values()
        return {"save_" + k: o[k] for k in ge.KEYS}

    def set_values(self, opts):
        o = ge.normalize(opts)
        for cb in self._option_combos():
            cb.blockSignals(True)
        try:
            self._set_combos(o)
        finally:
            for cb in self._option_combos():
                cb.blockSignals(False)
        self._sync_profile()
        self.changed.emit()

    def _set_combos(self, o):
        self.cb_regrid.setCurrentIndex(max(0, self.cb_regrid.findData(o["regrid"])))
        self.cb_wind.setCurrentIndex(max(0, self.cb_wind.findData(o["wind"])))
        self.cb_dec_wind.setCurrentIndex(max(0, self.cb_dec_wind.findData(o["dec_wind"])))
        self.cb_dec_temp.setCurrentIndex(max(0, self.cb_dec_temp.findData(o["dec_temp"])))
        self.cb_label.setCurrentIndex(max(0, self.cb_label.findData(o["label"])))
        self.cb_packing.setCurrentIndex(max(0, self.cb_packing.findData(o["packing"])))
        self.cb_centre.setCurrentIndex(max(0, self.cb_centre.findData(o["centre"])))
        self.sp_sub_centre.setValue(-1 if o["sub_centre"] is None else o["sub_centre"])
        self.cb_tables.setCurrentIndex(max(0, self.cb_tables.findData(o["tables"])))
        self.cb_scan.setCurrentIndex(max(0, self.cb_scan.findData(o["scan"])))
        self.cb_rows.setCurrentIndex(max(0, self.cb_rows.findData(o["rows"])))
        self.cb_lons.setCurrentIndex(max(0, self.cb_lons.findData(o["lons"])))

    def profile(self):
        return self.cb_profile.currentData()

    def set_profile(self, key):
        vals = ge.profile_values(key)
        if vals is not None:
            self.set_values(vals)

    def _on_profile(self, _i):
        key = self.cb_profile.currentData()
        if key is None:
            return                       # «Personalizado»: se queda como está
        self.set_profile(key)
        self.profile_chosen.emit(key)

    def _on_option_changed(self, _i):
        self._sync_profile()
        self.changed.emit()

    def _sync_profile(self):
        """El combo de perfil muestra el que coincide con lo elegido."""
        key = ge.profile_of(self._combo_values())
        self.cb_profile.blockSignals(True)
        self.cb_profile.setCurrentIndex(0 if key is None else max(0, self.cb_profile.findData(key)))
        self.cb_profile.blockSignals(False)

    def wind_format(self):
        return wfm.normalize(self.cb_wind.currentData())

    def set_labeled(self, labeled, note=None):
        """La etiqueta de capa sólo tiene sentido en un archivo por Nivel."""
        for w in self._label_widgets:
            w.setEnabled(bool(labeled))
        if note is not None:
            self.cb_label.setToolTip(note)
