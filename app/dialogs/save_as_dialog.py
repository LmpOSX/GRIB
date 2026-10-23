# -*- coding: utf-8 -*-
"""«Guardar como…»: el archivo abierto recodificado entero según el bloque
«Archivo a guardar» (viento U/V o dirección y velocidad, decimales del
viento y de la temperatura, etiqueta de capa si está por Nivel, empaquetado
simple o IEEE, centro generador), con su `.json` de procedencia y su `.idx`.
No selecciona ni regrilla: para eso está Exportar a WAFS."""
import datetime as dt
import json
import os

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QLineEdit, QCheckBox,
    QFileDialog, QMessageBox,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.save_options import SaveOptionsBox
from .. import grib_encode as ge


def default_save_name(path, opts):
    """`nombre_rec.grib2`, con `_dirvel` si el viento va en dirección y velocidad."""
    base, _ext = os.path.splitext(os.path.basename(path))
    for suf in ("_rec", "_dirvel"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    base += "_rec"
    if ge.normalize(opts)["wind"] == "dirspeed":
        base += "_dirvel"
    return base + ".grib2"


def save_recoded(src_path, dst_path, opts, labeled=False, mode=None, provenance=None, idx=True):
    """Lee `src_path`, aplica el bloque y escribe `dst_path` con .json y .idx.
    Devuelve info de la recodificación."""
    with open(src_path, "rb") as fh:
        data = fh.read()
    out, info = ge.recode(data, opts, labeled=labeled, mode=mode)
    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
    with open(dst_path, "wb") as fh:
        fh.write(out)
    prov = dict(provenance or {})
    prov.setdefault("fuente", "archivo local")
    prov.setdefault("nombre", "archivo local")
    prov["archivo_original"] = os.path.abspath(src_path)
    prov["guardado"] = dict({k: info[k] for k in ge.KEYS}, descripcion=ge.describe(opts),
                            etiqueta_aplicada=bool(info.get("etiqueta_aplicada")))
    prov["viento"] = info["wind"]
    prov["por_nivel"] = bool(labeled)
    prov["recodificado"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(dst_path + ".json", "w", encoding="utf-8") as fh:
        json.dump(prov, fh, ensure_ascii=False, indent=2)
    if idx:
        try:
            from ..wafs_format import write_idx
            write_idx(dst_path)
        except Exception:
            pass
    info["bytes"] = len(out)
    info["bytes_origen"] = len(data)
    return info


class SaveAsDialog(GlassDialog):
    def __init__(self, parent=None, path="", reader=None, cfg=None, dest_dir=None, provenance=None):
        super().__init__(parent)
        self._path = path
        self._reader = reader
        self._cfg = cfg or {}
        self._prov = provenance or {}
        self.saved_path = None
        self.open_after = False
        self.setWindowTitle("Guardar como…")
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        title = QLabel("Guardar como…")
        title.setObjectName("Heading")
        lay.addWidget(title)
        hint = QLabel("Graba el archivo abierto entero, recodificado según este bloque. Para elegir "
                      "plazos y niveles, recortar o regrillar está Exportar a WAFS.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        labeled = bool(getattr(reader, "fl_labeled", False))
        self.save_box = SaveOptionsBox(cfg=self._cfg)
        self.save_box.set_labeled(labeled, None if labeled else
                                  "El archivo está en capas crudas (no por Nivel): la etiqueta no se toca.")
        lay.addWidget(self.save_box)
        src = QLabel(f"Origen: {os.path.basename(path)}" + ("" if labeled else "  (capas crudas)")
                     + (f"  · modo {reader.fl_mode}" if labeled and getattr(reader, 'fl_mode', None) else ""))
        src.setObjectName("Hint")
        lay.addWidget(src)

        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo"))
        self.ed_path = QLineEdit(os.path.join(dest_dir or os.path.dirname(path) or ".",
                                              default_save_name(path, self.save_box.values())))
        row.addWidget(self.ed_path, 1)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick)
        row.addWidget(b)
        lay.addLayout(row)
        self.save_box.cb_wind.currentIndexChanged.connect(self._refresh_name)
        self.chk_open = QCheckBox("Abrir el archivo guardado")
        self.chk_open.setChecked(True)
        lay.addWidget(self.chk_open)

        btns = QHBoxLayout()
        btns.addStretch()
        c = QPushButton("Cancelar")
        c.clicked.connect(self.reject)
        btns.addWidget(c)
        self.btn_save = QPushButton("Guardar")
        self.btn_save.setObjectName("AccentBtn")
        self.btn_save.clicked.connect(self._save)
        btns.addWidget(self.btn_save)
        lay.addLayout(btns)

    def _refresh_name(self, _i=None):
        cur = self.ed_path.text().strip()
        folder = os.path.dirname(cur) or os.path.dirname(self._path) or "."
        self.ed_path.setText(os.path.join(folder, default_save_name(self._path, self.save_box.values())))

    def _pick(self):
        p, _ = QFileDialog.getSaveFileName(self, "Guardar como", self.ed_path.text(),
                                           "GRIB2 (*.grib2 *.grb2 *.grib)")
        if p:
            self.ed_path.setText(p)

    def output_path(self):
        p = self.ed_path.text().strip()
        if p and not p.lower().endswith((".grib2", ".grb2", ".grib")):
            p += ".grib2"
        return p

    def _save(self):
        dst = self.output_path()
        if not dst:
            QMessageBox.warning(self, "Guardar como", "Indicá el archivo de salida.")
            return
        if os.path.abspath(dst) == os.path.abspath(self._path):
            QMessageBox.warning(self, "Guardar como", "Elegí otro nombre: no se sobreescribe el archivo abierto.")
            return
        if os.path.exists(dst):
            r = QMessageBox.question(self, "Guardar como", f"Ya existe {os.path.basename(dst)}. ¿Reemplazar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            save_recoded(self._path, dst, self.save_box.values(),
                         labeled=bool(getattr(self._reader, "fl_labeled", False)),
                         mode=getattr(self._reader, "fl_mode", None), provenance=self._prov)
        except Exception as exc:
            QMessageBox.critical(self, "Guardar como", f"No se pudo guardar:\n{exc}")
            return
        self._cfg.update(self.save_box.config_values())
        self.saved_path = dst
        self.open_after = self.chk_open.isChecked()
        self.accept()
