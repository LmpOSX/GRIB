# -*- coding: utf-8 -*-
"""«Exportar a WAFS…»: escribe lo cargado en el visor como GRIB2 WAFS, con
selección de plazos, niveles y variables, recorte, regrillado bilineal,
un archivo por plazo (gfs.tHHz.wafs_0p25.fFFF.grib2) o uno solo, el .idx
junto a cada archivo y la verificación de lo escrito."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QCheckBox,
    QComboBox, QLineEdit, QMessageBox, QRadioButton, QButtonGroup, QDoubleSpinBox,
    QSpinBox, QProgressBar, QFileDialog, QScrollArea, QWidget, QSizePolicy,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import wafs_format as wf
from .. import fl_table as flt


class _Worker(QThread):
    progress = pyqtSignal(float, str)
    done = pyqtSignal(object, str)      # resultado, error

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self._kw = kwargs

    def run(self):
        try:
            res = wf.export_wafs(progress_cb=self.progress.emit, **self._kw)
            self.done.emit(res, "")
        except Exception as exc:  # pragma: no cover - imprevistos
            self.done.emit(None, f"{type(exc).__name__}: {exc}")


class ExportWafsDialog(GlassDialog):
    """`result` guarda el dict devuelto por `wafs_format.export_wafs` al terminar."""

    def __init__(self, parent=None, reader=None, cfg=None, dest_dir=".", region=None,
                 provenance=None):
        super().__init__(parent)
        self._reader = reader
        self._cfg = cfg or {}
        self._dest_dir = dest_dir
        self._region = region           # extensión visible (lon0, lon1, lat0, lat1) o None
        self._prov = provenance or {}
        self._worker = None
        self.result = None
        self.setWindowTitle("Exportar a WAFS")
        self.setMinimumWidth(600)
        self._build_ui()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _sub(self, lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)

    def _build_ui(self):
        r = self._reader
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)

        title = QLabel("Exportar a WAFS")
        title.setObjectName("Heading")
        lay.addWidget(title)
        fls = sorted(getattr(r, "fl_levels", {}) or {})
        src_txt = os.path.basename(r.path) if r is not None else "—"
        if fls:
            lv_txt = f"FL{fls[0]:03d}–FL{fls[-1]:03d} ({len(fls)} niveles WAFS)"
        else:
            lv_txt = f"{len(r.levels)} niveles de presión (se convertirán a FL)"
        hint = QLabel(f"Archivo: {src_txt}   ·   {len(r.steps)} plazo(s)   ·   {lv_txt}")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # Plazos
        self._sub(lay, "Plazos")
        self.rb_all_steps = QRadioButton("Todos")
        self.rb_sel_steps = QRadioButton("Sólo:")
        self.rb_all_steps.setChecked(True)
        g = QButtonGroup(self)
        g.addButton(self.rb_all_steps)
        g.addButton(self.rb_sel_steps)
        row = QHBoxLayout()
        row.addWidget(self.rb_all_steps)
        row.addWidget(self.rb_sel_steps)
        self.step_checks = []
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        for s in r.steps:
            h = s.hours if s.hours is not None else 0
            c = QCheckBox(f"+{h:g} h")
            c.setChecked(True)
            c.setProperty("hours", float(h))
            self.step_checks.append(c)
            wl.addWidget(c)
        wl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(wrap)
        scroll.setFixedHeight(44)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        row.addWidget(scroll, 1)
        lay.addLayout(row)

        # Modo de etiquetado
        self._sub(lay, "Modo de etiquetado de los niveles")
        row = QHBoxLayout()
        self.cb_mode = QComboBox()
        for m in flt.MODES:
            self.cb_mode.addItem(flt.MODE_LABELS[m], m)
        self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(
            str(self._cfg.get("wafs_mode", flt.DEFAULT_MODE)).upper())))
        self.cb_mode.setToolTip("INDRA: 14 FL del FDP; OACI: 17 FL del Anexo 3; OACI56: los 56 FL; "
                                "los tres con etiqueta nominal en hPa. WAFS: 56 FL con la presión ISA "
                                "en Pa, como NOAA. El dato se interpola siempre a la ISA exacta.")
        row.addWidget(self.cb_mode, 1)
        b = QPushButton("Ver tabla…")
        b.clicked.connect(self._show_fl_table)
        row.addWidget(b)
        lay.addLayout(row)
        mode_src = getattr(r, "fl_mode", None) if getattr(r, "fl_labeled", False) else None
        self.lbl_mode = QLabel(f"El archivo abierto está etiquetado en modo {mode_src}; se reetiqueta "
                               "si el modo elegido es otro." if mode_src else
                               "El archivo abierto está en niveles de presión: se convierte al modo elegido.")
        self.lbl_mode.setObjectName("Hint")
        self.lbl_mode.setWordWrap(True)
        lay.addWidget(self.lbl_mode)

        # Niveles
        self._sub(lay, "Niveles de vuelo")
        row = QHBoxLayout()
        self.rb_all_fl = QRadioButton("Todos")
        self.rb_range_fl = QRadioButton("Rango FL")
        self.rb_all_fl.setChecked(True)
        g2 = QButtonGroup(self)
        g2.addButton(self.rb_all_fl)
        g2.addButton(self.rb_range_fl)
        row.addWidget(self.rb_all_fl)
        row.addWidget(self.rb_range_fl)
        self.fl_min = QSpinBox()
        self.fl_min.setRange(0, 600)
        self.fl_min.setSingleStep(10)
        self.fl_min.setValue(fls[0] if fls else int(self._cfg.get("wafs_fl_min", 50)))
        self.fl_max = QSpinBox()
        self.fl_max.setRange(0, 600)
        self.fl_max.setSingleStep(10)
        self.fl_max.setValue(fls[-1] if fls else int(self._cfg.get("wafs_fl_max", 530)))
        row.addWidget(QLabel("de"))
        row.addWidget(self.fl_min)
        row.addWidget(QLabel("a"))
        row.addWidget(self.fl_max)
        row.addStretch()
        lay.addLayout(row)

        # Variables
        self._sub(lay, "Variables")
        row = QHBoxLayout()
        self.rb_basic = QRadioButton("Sólo viento (UGRD/VGRD o WDIR/WIND) y TMP")
        self.rb_all_vars = QRadioButton("Todas las disponibles")
        self.rb_basic.setChecked(True)
        g3 = QButtonGroup(self)
        g3.addButton(self.rb_basic)
        g3.addButton(self.rb_all_vars)
        row.addWidget(self.rb_basic)
        row.addWidget(self.rb_all_vars)
        row.addStretch()
        lay.addLayout(row)

        # Recorte
        self._sub(lay, "Recorte geográfico")
        self.chk_crop = QCheckBox("Recortar a la zona:")
        lay.addWidget(self.chk_crop)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        lats = r.lats
        lons = r.lons
        ext = self._region or (float(lons.min()), float(lons.max()), float(lats.min()), float(lats.max()))
        self.lat_n = self._coord(grid, "Norte", 0, 0, -90, 90, ext[3])
        self.lat_s = self._coord(grid, "Sur", 0, 2, -90, 90, ext[2])
        self.lon_w = self._coord(grid, "Oeste", 1, 0, -180, 360, ext[0])
        self.lon_e = self._coord(grid, "Este", 1, 2, -180, 360, ext[1])
        lay.addLayout(grid)
        self.chk_crop.toggled.connect(self._on_crop_toggled)
        self._on_crop_toggled(False)

        # Regrillado y salida
        self._sub(lay, "Grilla y archivos")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.addWidget(QLabel("Regrillar"), 0, 0)
        self.cb_regrid = QComboBox()
        for key, text in wf.EXPORT_REGRID:
            self.cb_regrid.addItem(text, key)
        grid.addWidget(self.cb_regrid, 0, 1, 1, 3)
        self.rb_per_step = QRadioButton("Un archivo por plazo (gfs.tHHz.wafs_0p25.fFFF.grib2)")
        self.rb_single = QRadioButton("Un único archivo multi-plazo")
        self.rb_per_step.setChecked(True)
        g4 = QButtonGroup(self)
        g4.addButton(self.rb_per_step)
        g4.addButton(self.rb_single)
        grid.addWidget(self.rb_per_step, 1, 0, 1, 4)
        grid.addWidget(self.rb_single, 2, 0, 1, 4)
        grid.addWidget(QLabel("Prefijo del modelo"), 3, 0)
        self.ed_model = QLineEdit(self._default_model())
        self.ed_model.setMaximumWidth(120)
        grid.addWidget(self.ed_model, 3, 1)
        grid.addWidget(QLabel("Nombre (archivo único)"), 3, 2)
        self.ed_name = QLineEdit("")
        self.ed_name.setPlaceholderText("vacío = modelo.tHHz.wafs_RES.fAAA-fBBB.grib2")
        grid.addWidget(self.ed_name, 3, 3)
        grid.addWidget(QLabel("Carpeta"), 4, 0)
        self.ed_dest = QLineEdit(self._dest_dir)
        grid.addWidget(self.ed_dest, 4, 1, 1, 2)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick_dir)
        grid.addWidget(b, 4, 3)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        self.chk_idx = QCheckBox("Generar el inventario .idx junto a cada archivo")
        self.chk_idx.setChecked(True)
        lay.addWidget(self.chk_idx)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("Hint")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_cancel = QPushButton("Cerrar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_export = QPushButton("Exportar")
        self.btn_export.setObjectName("AccentBtn")
        self.btn_export.clicked.connect(self._start)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_export)
        lay.addLayout(row)

    def _coord(self, grid, text, r, c, lo, hi, val):
        grid.addWidget(QLabel(text), r, c, alignment=Qt.AlignmentFlag.AlignRight)
        sb = QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(2)
        sb.setSingleStep(1.0)
        sb.setValue(val)
        grid.addWidget(sb, r, c + 1)
        return sb

    def _show_fl_table(self):
        from .fl_table_dialog import FlTableDialog
        FlTableDialog(self, mode=self.cb_mode.currentData() or flt.DEFAULT_MODE).exec()

    def _default_model(self):
        key = (self._prov or {}).get("fuente", "")
        return {"gfs": "gfs", "wafs": "gfs", "ecmwf": "ecmwf", "icon": "icon",
                "generica": "gen"}.get(key, "gfs")

    def _on_crop_toggled(self, on):
        for w in (self.lat_n, self.lat_s, self.lon_w, self.lon_e):
            w.setEnabled(on)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.ed_dest.text())
        if d:
            self.ed_dest.setText(d)

    # ── Exportación ──────────────────────────────────────────────────────────

    def options(self):
        """kwargs para `wafs_format.export_wafs` con lo elegido."""
        steps = None
        if self.rb_sel_steps.isChecked():
            steps = [c.property("hours") for c in self.step_checks if c.isChecked()]
        fls = None
        if self.rb_range_fl.isChecked():
            lo, hi = sorted((self.fl_min.value(), self.fl_max.value()))
            fls = list(range(lo - lo % 10, hi + 1, 10))
        region = None
        if self.chk_crop.isChecked():
            region = (self.lat_n.value(), self.lat_s.value(), self.lon_w.value(), self.lon_e.value())
        return dict(
            src=self._reader.path, dest_dir=self.ed_dest.text().strip() or ".",
            steps=steps, fls=fls,
            variables="basicas" if self.rb_basic.isChecked() else "todas",
            region=region, regrid=self.cb_regrid.currentData() or "ninguno",
            per_step=self.rb_per_step.isChecked(),
            model=(self.ed_model.text().strip() or "gfs"),
            basename=(self.ed_name.text().strip() or None),
            idx=self.chk_idx.isChecked(),
            convert_opts=wf.options_from_config(self._cfg) or {},
            provenance=dict(self._prov) if self._prov else None,
            mode=self.cb_mode.currentData() or flt.DEFAULT_MODE,
        )

    def _validate(self, opts):
        if opts["steps"] is not None and not opts["steps"]:
            return "Elegí al menos un plazo."
        if opts["region"] is not None:
            top, bottom, left, right = opts["region"]
            if bottom >= top:
                return "Latitud: el norte debe ser mayor que el sur."
            if left == right:
                return "Longitud: oeste y este no pueden ser iguales."
        if any(c in opts["model"] for c in '/\\:*?"<>| '):
            return "Prefijo del modelo inválido."
        return None

    def _set_busy(self, busy):
        for w in self.findChildren(QWidget):
            if w not in (self.btn_cancel, self.progress, self.lbl_status):
                if isinstance(w, (QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
                                  QComboBox, QLineEdit, QRadioButton)):
                    w.setEnabled(not busy)
        if not busy:
            self._on_crop_toggled(self.chk_crop.isChecked())

    def _start(self):
        opts = self.options()
        err = self._validate(opts)
        if err:
            QMessageBox.warning(self, "Exportar a WAFS", err)
            return
        self._set_busy(True)
        self.progress.setValue(0)
        self.lbl_status.setText("Exportando…")
        self._worker = _Worker(opts, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, frac, msg):
        self.progress.setValue(int(frac * 1000))
        self.lbl_status.setText(msg)

    def _on_done(self, res, error):
        self._set_busy(False)
        if error:
            self.progress.setValue(0)
            self.lbl_status.setText("Error: " + error)
            QMessageBox.critical(self, "Exportar a WAFS", error)
            return
        self.result = res
        self.progress.setValue(1000)
        # El resultado queda a la vista en el propio diálogo (sin ventana modal)
        self.lbl_status.setText(self.summary(res, long=True))
        self.btn_export.setText("Exportar de nuevo")

    @staticmethod
    def summary(res, long=False):
        """Texto del resultado: archivos, verificación y avisos del validador."""
        lines = []
        ok_all = all(v["ok"] for v in res["verificacion"])
        lines.append(("Verificación OK: " if ok_all else "Verificación con diferencias: ")
                     + f"{len(res['archivos'])} archivo(s) escrito(s).")
        for v in res["verificacion"]:
            dif = ", ".join(f"{wf.WAFS_SHORTNAMES.get(k, k)} {d:.3g}" for k, d in v["max_dif"].items())
            lines.append(f"  {os.path.basename(v['archivo'])}: {v['mensajes']} mensajes, "
                         f"{v['niveles']} niveles" + (f", máx. dif. {dif}" if dif else "")
                         + ("" if v["ok"] else "  ✗ " + "; ".join(v["detalle"])))
            if not long and len(lines) > 4:
                lines.append(f"  … y {len(res['verificacion']) - 3} más")
                break
        if res.get("avisos"):
            lines.append("Avisos del validador WAFS:")
            lines += ["  · " + a for a in res["avisos"][: 8 if long else 3]]
        return "\n".join(lines)

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        super().closeEvent(event)
