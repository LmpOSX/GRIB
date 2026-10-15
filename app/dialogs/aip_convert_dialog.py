# -*- coding: utf-8 -*-
"""Conversor de texto del AIP (ENR 2.1) a GeoJSON: se pega la lista de
vértices (o se abre un archivo de texto), se elige el código de la FIR y
se guarda el GeoJSON. Los tramos descriptos con palabras («a lo largo del
límite internacional», «por la costa») se informan como pendientes."""
import json
import os

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QComboBox, QLineEdit, QPlainTextEdit,
    QFileDialog, QMessageBox, QCheckBox,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import fir as firmod
from .. import fir_aip

EXAMPLE = ("Ejemplo de texto admitido:\n"
           "3917S06307W - 4600S04500W - siguiendo el paralelo 46°00'S hasta 4600S01000W -\n"
           "9000S01000W - 9000S07000W - a lo largo del límite internacional hasta 3917S06307W")


class AipConvertDialog(GlassDialog):
    def __init__(self, parent=None, start_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Convertir texto del AIP")
        self.setMinimumWidth(680)
        self._start_dir = start_dir
        self._feature = None
        self.saved_path = None
        self.use_as_user_file = False
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)

        title = QLabel("AIP ENR 2.1 → GeoJSON")
        title.setObjectName("Heading")
        lay.addWidget(title)
        hint = QLabel("Pegá la lista de vértices del límite lateral tal como figura en el AIP Argentina "
                      "(AIS de EANA/ANAC). Se reconocen 2215S06240W, 221530S0624015W, 22°15'S 062°40'W, "
                      "22 15 S 062 40 W, decimales con hemisferio y parejas con signo (una por línea). "
                      "Los tramos «a lo largo del límite…» o «por la costa» quedan marcados para "
                      "completarlos a mano.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("FIR"))
        self.cb_code = QComboBox()
        self.cb_code.setEditable(True)
        for code, name in firmod.ARGENTINA_FIRS + firmod.NEIGHBOR_FIRS:
            self.cb_code.addItem(f"{code}  {name}", code)
        row.addWidget(self.cb_code, 1)
        row.addWidget(QLabel("Nombre"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("(según el código)")
        row.addWidget(self.ed_name, 1)
        lay.addLayout(row)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(EXAMPLE)
        self.text.setMinimumHeight(160)
        lay.addWidget(self.text, 1)

        row = QHBoxLayout()
        b = QPushButton("Abrir archivo de texto…")
        b.clicked.connect(self._open_text)
        row.addWidget(b)
        self.btn_convert = QPushButton("Convertir")
        self.btn_convert.clicked.connect(self.convert)
        row.addWidget(self.btn_convert)
        row.addStretch()
        lay.addLayout(row)

        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMinimumHeight(110)
        self.report.setPlaceholderText("Informe de la conversión")
        lay.addWidget(self.report)

        self.chk_use = QCheckBox("Usar el GeoJSON guardado como archivo propio de la capa")
        self.chk_use.setChecked(True)
        lay.addWidget(self.chk_use)

        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Cerrar")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        self.btn_save = QPushButton("Guardar GeoJSON…")
        self.btn_save.setObjectName("AccentBtn")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    def code(self):
        data = self.cb_code.currentData()
        txt = self.cb_code.currentText().strip().upper()
        return (data if data and txt.startswith(data) else txt.split()[0] if txt else "")

    def _open_text(self):
        path, _ = QFileDialog.getOpenFileName(self, "Texto con los vértices", self._start_dir,
                                              "Texto (*.txt *.csv);;Todos los archivos (*)")
        if path:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                self.text.setPlainText(fh.read())

    def convert(self):
        """Arma la feature y muestra el informe. Devuelve True si se pudo."""
        code = self.code()
        if not code or len(code) != 4:
            QMessageBox.warning(self, "Convertir", "Indicá el código OACI de la FIR (cuatro letras).")
            return False
        try:
            self._feature = fir_aip.aip_to_feature(self.text.toPlainText(), code,
                                                   self.ed_name.text().strip() or None)
        except fir_aip.AipParseError as exc:
            self._feature = None
            self.report.setPlainText(f"Error: {exc}")
            self.btn_save.setEnabled(False)
            return False
        self.report.setPlainText(fir_aip.report(self._feature))
        self.btn_save.setEnabled(True)
        return True

    def geojson(self):
        if self._feature is None:
            return None
        return {"type": "FeatureCollection", "features": [self._feature],
                "_visor": {"fuente": fir_aip.AIP_SOURCE, "oficial": True,
                           "aviso": "Convertido del texto del AIP; revisar los tramos pendientes."}}

    def _save(self):
        if self._feature is None and not self.convert():
            return
        default = os.path.join(self._start_dir or "", f"fir_{self._feature['properties']['id']}.geojson")
        path, _ = QFileDialog.getSaveFileName(self, "Guardar GeoJSON", default, "GeoJSON (*.geojson)")
        if not path:
            return
        if not path.lower().endswith(".geojson"):
            path += ".geojson"
        self.save_to(path)
        self.accept()

    def save_to(self, path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.geojson(), fh, ensure_ascii=False, indent=1)
        self.saved_path = path
        self.use_as_user_file = self.chk_use.isChecked()
        return path
