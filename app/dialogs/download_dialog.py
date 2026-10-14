# -*- coding: utf-8 -*-
"""Diálogo «Descargar GFS…»: corrida, horas de pronóstico, variables,
niveles, resolución, zona geográfica y destino. La descarga corre en un
hilo con progreso y cancelación; al terminar puede abrir el archivo."""
import datetime as dt
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QDateEdit,
    QProgressBar, QFileDialog, QMessageBox, QWidget,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from .. import gfs_download as gfs


class _Worker(QThread):
    progress = pyqtSignal(int, int, str, float)
    done = pyqtSignal(list, str)     # rutas escritas, mensaje de error ('' si ok)

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self._spec = spec
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            paths = gfs.download(self._spec, progress_cb=self.progress.emit,
                                 cancel=lambda: self._cancel)
            self.done.emit(paths, "")
        except gfs.DownloadCancelled:
            self.done.emit([], "cancelada")
        except gfs.DownloadError as exc:
            self.done.emit([], str(exc))
        except Exception as exc:          # pragma: no cover - imprevistos
            self.done.emit([], f"{type(exc).__name__}: {exc}")


class DownloadDialog(GlassDialog):
    """Devuelve en `downloaded_paths` las rutas bajadas si se aceptó."""

    def __init__(self, parent=None, dest_dir=".", region=None, defaults=None):
        """defaults: claves download_* de la configuración (Preferencias ▸ Descarga)."""
        super().__init__(parent)
        self.setWindowTitle("Descargar GFS")
        self.setMinimumWidth(680)
        self.downloaded_paths = []
        self.open_after = True
        self._worker = None
        self._dest_dir = dest_dir
        self._defaults = dict(defaults or {})
        self._build_ui()
        self._apply_defaults()
        if region is not None:
            self.set_region(*region)
        self._set_latest_cycle()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _section(self, lay, title):
        lbl = QLabel(title)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = QLabel("Descargar GRIB2 del GFS (NOMADS / NOAA)")
        title.setObjectName("Heading")
        lay.addWidget(title)

        # ── Corrida y pasos ──
        self._section(lay, "Corrida y horas de pronóstico")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Fecha (UTC)"), 0, 0)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("yyyy-MM-dd")
        g.addWidget(self.date, 0, 1)
        g.addWidget(QLabel("Ciclo"), 0, 2)
        self.cycle = QComboBox()
        for c in gfs.CYCLES:
            self.cycle.addItem(f"{c:02d}Z", c)
        g.addWidget(self.cycle, 0, 3)
        btn_latest = QPushButton("Última disponible")
        btn_latest.clicked.connect(self._set_latest_cycle)
        g.addWidget(btn_latest, 0, 4)
        g.addWidget(QLabel("Horas: desde"), 1, 0)
        self.h_from = QSpinBox(); self.h_from.setRange(0, gfs.MAX_HOUR); self.h_from.setValue(6)
        g.addWidget(self.h_from, 1, 1)
        g.addWidget(QLabel("hasta"), 1, 2)
        self.h_to = QSpinBox(); self.h_to.setRange(0, gfs.MAX_HOUR); self.h_to.setValue(12)
        g.addWidget(self.h_to, 1, 3)
        row = QHBoxLayout()
        row.addWidget(QLabel("cada"))
        self.h_step = QSpinBox(); self.h_step.setRange(1, 24); self.h_step.setValue(3)
        self.h_step.setSuffix(" h")
        row.addWidget(self.h_step)
        row.addStretch()
        g.addLayout(row, 1, 4)
        lay.addLayout(g)

        # ── Variables y resolución ──
        self._section(lay, "Variables y resolución")
        vg = QGridLayout()
        vg.setHorizontalSpacing(12)
        vg.setVerticalSpacing(2)
        self.var_checks = {}
        for k, (key, name) in enumerate(gfs.VARIABLES):
            c = QCheckBox(name)
            c.setChecked(key in ("UGRD", "VGRD", "TMP"))
            self.var_checks[key] = c
            vg.addWidget(c, k // 3, k % 3)
        lay.addLayout(vg)
        row = QHBoxLayout()
        row.addWidget(QLabel("Resolución"))
        self.res = QComboBox()
        for r in gfs.RESOLUTIONS:
            self.res.addItem(r[1], r[0])
        self.res.currentIndexChanged.connect(self._on_res_changed)
        row.addWidget(self.res)
        self.chk_extra = QCheckBox("Incluir niveles intermedios cada 25 hPa (pgrb2b)")
        self.chk_extra.setToolTip("875 … 125 hPa: a 0,25° se bajan del producto pgrb2b y se "
                                  "unen al mismo archivo; a 0,50° vienen en pgrb2full; a "
                                  "1,00° no existen. Con ellos F320, F360 y F410 quedan a "
                                  "menos de 4 hPa de un nivel del archivo.")
        self.chk_extra.toggled.connect(self._on_extra_toggled)
        row.addWidget(self.chk_extra)
        row.addStretch()
        lay.addLayout(row)

        # ── Niveles ──
        self._section(lay, "Niveles de presión (hPa)")
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        self.level_checks = {}
        cols = 10
        for k, lv in enumerate(gfs.ALL_LEVELS):
            c = QCheckBox(f"{lv}")
            c.setChecked(lv in gfs.VIEWER_LEVELS)
            if lv in gfs.EXTRA_LEVELS:
                c.setObjectName("ExtraLevel")
                c.setEnabled(False)
            self.level_checks[lv] = c
            grid.addWidget(c, k // cols, k % cols)
        lay.addLayout(grid)
        row = QHBoxLayout()
        for text, fn in (("Los del visor", self._set_viewer_levels),
                         ("Todos", lambda: self._set_levels(gfs.ALL_LEVELS)),
                         ("Ninguno", lambda: self._set_levels([]))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        # ── Zona ──
        self._section(lay, "Zona geográfica (grados; longitudes −180…180)")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        self.chk_global = QCheckBox("Todo el globo")
        self.chk_global.toggled.connect(self._on_global_toggled)
        g.addWidget(self.chk_global, 0, 0, 1, 2)
        self.lat_n = self._coord(g, "Lat norte", 1, 0, -90, 90, 4.0)
        self.lat_s = self._coord(g, "Lat sur", 1, 2, -90, 90, -64.0)
        self.lon_w = self._coord(g, "Lon oeste", 2, 0, -180, 360, -90.0)
        self.lon_e = self._coord(g, "Lon este", 2, 2, -180, 360, -22.0)
        self.btn_domain = QPushButton("Dominio del archivo abierto")
        self.btn_domain.setEnabled(False)
        g.addWidget(self.btn_domain, 1, 4, 2, 1)
        lay.addLayout(g)

        # ── Destino ──
        self._section(lay, "Destino")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Carpeta"), 0, 0)
        self.dest = QLineEdit(self._dest_dir)
        g.addWidget(self.dest, 0, 1)
        b = QPushButton("Elegir…")
        b.clicked.connect(self._pick_dir)
        g.addWidget(b, 0, 2)
        g.addWidget(QLabel("Nombre"), 1, 0)
        self.name = QLineEdit()
        self.name.setPlaceholderText("(automático: gfs_FECHA_CICLOz_RES)")
        g.addWidget(self.name, 1, 1)
        self.chk_merge = QCheckBox("Unir los pasos en un solo archivo")
        self.chk_merge.setChecked(True)
        g.addWidget(self.chk_merge, 2, 1)
        self.chk_open = QCheckBox("Abrir en el visor al terminar")
        self.chk_open.setChecked(True)
        g.addWidget(self.chk_open, 3, 1)
        lay.addLayout(g)

        # ── Progreso y botones ──
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)
        self.lbl_status = QLabel("Listo para descargar.")
        self.lbl_status.setObjectName("SubHeading")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_cancel = QPushButton("Cerrar")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_download = QPushButton("Descargar")
        self.btn_download.setObjectName("AccentBtn")
        self.btn_download.clicked.connect(self._start)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_download)
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

    # ── Estado ───────────────────────────────────────────────────────────────

    def _set_latest_cycle(self):
        date, cyc = gfs.latest_cycle()
        self.date.setDate(QDate(date.year, date.month, date.day))
        self.cycle.setCurrentIndex(gfs.CYCLES.index(cyc))

    def _apply_defaults(self):
        d = self._defaults
        idx = self.res.findData(d.get("download_resolution", "0p25"))
        self.res.setCurrentIndex(max(0, idx))
        self.chk_extra.setChecked(bool(d.get("download_extra_levels", False)))
        self._set_viewer_levels()
        self.h_from.setValue(int(d.get("download_h_from", 6)))
        self.h_to.setValue(int(d.get("download_h_to", 12)))
        self.h_step.setValue(int(d.get("download_h_step", 3)))
        self.chk_merge.setChecked(bool(d.get("download_merge", True)))
        self.chk_open.setChecked(bool(d.get("download_open", True)))

    def extra_levels_enabled(self):
        return self.chk_extra.isChecked() and self.chk_extra.isEnabled()

    def _on_res_changed(self, *_):
        ok = gfs.extra_levels_available(self.res.currentData())
        self.chk_extra.setEnabled(ok)
        if not ok:
            self.chk_extra.setChecked(False)
        self._on_extra_toggled(self.chk_extra.isChecked())

    def _on_extra_toggled(self, on):
        """Las casillas de niveles intermedios sólo se pueden marcar si se
        pidieron; al desmarcar la opción quedan destildadas."""
        on = bool(on) and self.chk_extra.isEnabled()
        for lv in gfs.EXTRA_LEVELS:
            c = self.level_checks[lv]
            c.setEnabled(on)
            if not on:
                c.setChecked(False)

    def _set_viewer_levels(self):
        levels = list(gfs.VIEWER_LEVELS)
        if self.extra_levels_enabled():
            levels += gfs.VIEWER_EXTRA_LEVELS
        self._set_levels(levels)

    def _set_levels(self, levels):
        for lv, c in self.level_checks.items():
            c.setChecked(lv in levels and (c.isEnabled() or lv not in gfs.EXTRA_LEVELS))

    def _on_global_toggled(self, on):
        for sb in (self.lat_n, self.lat_s, self.lon_w, self.lon_e):
            sb.setEnabled(not on)

    def set_region(self, top, bottom, left, right):
        self.lat_n.setValue(top)
        self.lat_s.setValue(bottom)
        self.lon_w.setValue(left)
        self.lon_e.setValue(right)
        self.chk_global.setChecked(False)

    def enable_domain_button(self, region):
        """Botón «Dominio del archivo abierto» con la zona del archivo actual."""
        self.btn_domain.setEnabled(True)
        self.btn_domain.clicked.connect(lambda: self.set_region(*region))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.dest.text())
        if d:
            self.dest.setText(d)

    def hours(self):
        a, b, s = self.h_from.value(), self.h_to.value(), self.h_step.value()
        if b < a:
            a, b = b, a
        return list(range(a, b + 1, s))

    def spec(self):
        """DownloadSpec con lo elegido en el diálogo."""
        qd = self.date.date()
        region = None
        if not self.chk_global.isChecked():
            region = (self.lat_n.value(), self.lat_s.value(),
                      self.lon_w.value(), self.lon_e.value())
        return gfs.DownloadSpec(
            date=dt.date(qd.year(), qd.month(), qd.day()),
            cycle=self.cycle.currentData(),
            hours=self.hours(),
            variables=[k for k, c in self.var_checks.items() if c.isChecked()],
            levels=[lv for lv, c in self.level_checks.items() if c.isChecked()],
            resolution=self.res.currentData(),
            region=region,
            dest_dir=self.dest.text().strip() or ".",
            basename=self.name.text().strip() or None,
            merge=self.chk_merge.isChecked(),
        )

    # ── Descarga ─────────────────────────────────────────────────────────────

    def _set_busy(self, busy):
        for w in self.findChildren(QWidget):
            if w not in (self.btn_cancel, self.progress, self.lbl_status):
                if isinstance(w, (QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
                                  QComboBox, QLineEdit, QDateEdit)):
                    w.setEnabled(not busy)
        if not busy:
            self._on_global_toggled(self.chk_global.isChecked())
            self._on_res_changed()
        self.btn_cancel.setText("Cancelar" if busy else "Cerrar")

    def _start(self):
        spec = self.spec()
        err = spec.validate()
        if err:
            QMessageBox.warning(self, "Descargar GFS", err)
            return
        existing = [p for p in spec.file_paths() if os.path.exists(p)]
        if existing:
            r = QMessageBox.question(
                self, "Descargar GFS",
                f"Ya existe {os.path.basename(existing[0])}"
                + (f" y {len(existing) - 1} más" if len(existing) > 1 else "")
                + ". ¿Reemplazar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.downloaded_paths = []
        self._set_busy(True)
        self.progress.setValue(0)
        self.lbl_status.setText("Conectando con NOMADS…")
        self._worker = _Worker(spec, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_progress(self, _i, _n, msg, frac):
        self.progress.setValue(int(frac * 1000))
        self.lbl_status.setText(msg)

    def _on_done(self, paths, error):
        self._set_busy(False)
        if error == "cancelada":
            self.lbl_status.setText("Descarga cancelada.")
            self.progress.setValue(0)
            return
        if error:
            self.lbl_status.setText("Error: " + error.splitlines()[0])
            QMessageBox.critical(self, "Descargar GFS", error)
            return
        self.downloaded_paths = paths
        self.open_after = self.chk_open.isChecked()
        self.lbl_status.setText("Descarga completa: " + ", ".join(os.path.basename(p) for p in paths))
        self.accept()

    def _on_cancel(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.lbl_status.setText("Cancelando…")
            return
        self.reject()

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)

