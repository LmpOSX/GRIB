# -*- coding: utf-8 -*-
"""Diálogo «Obtener datos…»: fuente, corrida y plazos entre los que la fuente
ofrece, variables, niveles (si es de altura), parámetros propios de la
fuente, zona y destino. La descarga corre en un hilo con caché, progreso y
cancelación; al terminar puede abrir el archivo."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit,
    QProgressBar, QFileDialog, QMessageBox, QWidget,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..sources import (DownloadJob, DownloadError, DownloadCancelled, enabled_sources,
                       get_source, source_config, source_label, all_sources)
from ..sources.cache import DownloadCache
from ..widgets.params_form import ParamsForm


class _Worker(QThread):
    progress = pyqtSignal(int, int, str, float)
    done = pyqtSignal(list, str)     # rutas escritas, mensaje de error ('' si ok)

    def __init__(self, source, job, cache, parent=None):
        super().__init__(parent)
        self._src, self._job, self._cache = source, job, cache
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            paths = self._src.download(self._job, progress_cb=self.progress.emit,
                                       cancel=lambda: self._cancel, cache=self._cache)
            self.done.emit(paths, "")
        except DownloadCancelled:
            self.done.emit([], "cancelada")
        except DownloadError as exc:
            self.done.emit([], str(exc))
        except Exception as exc:          # pragma: no cover - imprevistos
            self.done.emit([], f"{type(exc).__name__}: {exc}")


class DownloadDialog(GlassDialog):
    """Devuelve en `downloaded_paths` las rutas bajadas si se aceptó."""

    def __init__(self, parent=None, cfg=None, dest_dir=".", region=None, source_key=None):
        super().__init__(parent)
        self.setWindowTitle("Obtener datos")
        self.setMinimumWidth(700)
        self._cfg = cfg or {}
        self.downloaded_paths = []
        self.open_after = True
        self._worker = None
        self._dest_dir = dest_dir
        self._region = region
        self._domain_region = None
        self.source = None
        self._build_ui()
        key = source_key or self._cfg.get("source") or "gfs"
        idx = self.cb_source.findData(key)
        self.cb_source.setCurrentIndex(max(0, idx))
        self._on_source_changed()
        if region is not None:
            self.set_region(*region)

    # ── Construcción ─────────────────────────────────────────────────────────

    def _section(self, lay, title):
        lbl = QLabel(title)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)
        return lbl

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

        # ── Fuente ──
        row = QHBoxLayout()
        title = QLabel("Obtener datos")
        title.setObjectName("Heading")
        row.addWidget(title)
        row.addStretch()
        row.addWidget(QLabel("Fuente"))
        self.cb_source = QComboBox()
        sources = enabled_sources(self._cfg) or all_sources()
        for s in sources:
            self.cb_source.addItem(source_label(s), s.key)
        self.cb_source.currentIndexChanged.connect(self._on_source_changed)
        row.addWidget(self.cb_source)
        lay.addLayout(row)
        self.lbl_model = QLabel("")
        self.lbl_model.setObjectName("Hint")
        self.lbl_model.setWordWrap(True)
        lay.addWidget(self.lbl_model)

        # ── Corrida y plazos ──
        self._section(lay, "Corrida y plazos (los que ofrece la fuente)")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Corrida (UTC)"), 0, 0)
        self.cb_run = QComboBox()
        g.addWidget(self.cb_run, 0, 1, 1, 3)
        b = QPushButton("Última")
        b.clicked.connect(lambda: self.cb_run.setCurrentIndex(0))
        g.addWidget(b, 0, 4)
        g.addWidget(QLabel("Plazos: desde"), 1, 0)
        self.h_from = QSpinBox()
        g.addWidget(self.h_from, 1, 1)
        g.addWidget(QLabel("hasta"), 1, 2)
        self.h_to = QSpinBox()
        g.addWidget(self.h_to, 1, 3)
        row = QHBoxLayout()
        row.addWidget(QLabel("cada"))
        self.h_step = QSpinBox()
        self.h_step.setRange(1, 24)
        self.h_step.setSuffix(" h")
        row.addWidget(self.h_step)
        row.addStretch()
        g.addLayout(row, 1, 4)
        lay.addLayout(g)
        self.lbl_steps = QLabel("")
        self.lbl_steps.setObjectName("Hint")
        lay.addWidget(self.lbl_steps)
        for w in (self.h_from, self.h_to, self.h_step):
            w.valueChanged.connect(lambda _v: self._refresh_steps_hint())

        # ── Variables ──
        self._section(lay, "Variables")
        self.var_box = QWidget()
        self.var_grid = QGridLayout(self.var_box)
        self.var_grid.setContentsMargins(0, 0, 0, 0)
        self.var_grid.setHorizontalSpacing(12)
        self.var_grid.setVerticalSpacing(2)
        self.var_checks = {}
        lay.addWidget(self.var_box)

        # ── Parámetros de la fuente ──
        self.lbl_params = self._section(lay, "Opciones de la fuente")
        self.params_box = QWidget()
        self.params_lay = QVBoxLayout(self.params_box)
        self.params_lay.setContentsMargins(0, 0, 0, 0)
        self.form = None
        lay.addWidget(self.params_box)

        # ── Niveles ──
        self.lbl_levels = self._section(lay, "Niveles de presión (hPa)")
        self.levels_box = QWidget()
        lv_lay = QVBoxLayout(self.levels_box)
        lv_lay.setContentsMargins(0, 0, 0, 0)
        lv_lay.setSpacing(4)
        self.level_grid_w = QWidget()
        self.level_grid = QGridLayout(self.level_grid_w)
        self.level_grid.setContentsMargins(0, 0, 0, 0)
        self.level_grid.setHorizontalSpacing(6)
        self.level_grid.setVerticalSpacing(2)
        self.level_checks = {}
        lv_lay.addWidget(self.level_grid_w)
        row = QHBoxLayout()
        for text, fn in (("Los del visor", self._set_viewer_levels),
                         ("Todos", lambda: self._set_levels(self.source.levels)),
                         ("Ninguno", lambda: self._set_levels([]))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lv_lay.addLayout(row)
        lay.addWidget(self.levels_box)

        # ── Zona ──
        self.lbl_zone = self._section(lay, "Zona geográfica (grados; longitudes −180…180)")
        self.zone_box = QWidget()
        g = QGridLayout(self.zone_box)
        g.setContentsMargins(0, 0, 0, 0)
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
        self.btn_domain.clicked.connect(
            lambda: self._domain_region and self.set_region(*self._domain_region))
        g.addWidget(self.btn_domain, 1, 4, 2, 1)
        lay.addWidget(self.zone_box)

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
        self.name.setPlaceholderText("(automático según fuente, corrida y resolución)")
        g.addWidget(self.name, 1, 1)
        self.chk_merge = QCheckBox("Unir los plazos en un solo archivo")
        self.chk_merge.setChecked(bool(self._cfg.get("download_merge", True)))
        g.addWidget(self.chk_merge, 2, 1)
        self.chk_open = QCheckBox("Abrir en el visor al terminar")
        self.chk_open.setChecked(bool(self._cfg.get("download_open", True)))
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

    @staticmethod
    def _clear_layout(lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    # ── Fuente ───────────────────────────────────────────────────────────────

    def _on_source_changed(self, *_):
        key = self.cb_source.currentData()
        src = get_source(key)
        if src is None:
            return
        self.source = src
        stored = source_config(self._cfg, key)
        kind = "altura (niveles de presión)" if src.kind == "altura" else "superficie"
        self.lbl_model.setText(f"{src.model}  ·  {kind}"
                               + ("  ·  ✓ niveles OACI por FL" if src.flight_levels else ""))
        # Corridas
        self.cb_run.clear()
        for day, cyc in src.available_runs(count=12):
            self.cb_run.addItem(f"{day:%Y-%m-%d} {cyc:02d}Z", (day, cyc))
        # Plazos
        steps = src.steps(stored["params"])
        self.h_from.setRange(steps[0], steps[-1])
        self.h_to.setRange(steps[0], steps[-1])
        self.h_from.setValue(int(self._cfg.get("download_h_from", 6)))
        self.h_to.setValue(int(self._cfg.get("download_h_to", 12)))
        self.h_step.setValue(int(self._cfg.get("download_h_step", 3)))
        # Variables
        self._clear_layout(self.var_grid)
        self.var_checks = {}
        for k, (vk, name) in enumerate(src.variables):
            c = QCheckBox(name)
            c.setChecked(vk in src.default_variables)
            self.var_checks[vk] = c
            self.var_grid.addWidget(c, k // 3, k % 3)
        self.var_box.setVisible(bool(src.variables))
        # Parámetros propios
        self._clear_layout(self.params_lay)
        self.form = None
        if src.params:
            self.form = ParamsForm(src.params, stored["params"])
            self.form.changed.connect(self._refresh_levels)
            self.params_lay.addWidget(self.form)
        self.lbl_params.setVisible(bool(src.params))
        self.params_box.setVisible(bool(src.params))
        # Niveles
        self._clear_layout(self.level_grid)
        self.level_checks = {}
        is_alt = src.kind == "altura" and bool(src.levels)
        if is_alt:
            cols = 10
            for k, lv in enumerate(src.levels):
                c = QCheckBox(f"{lv}")
                self.level_checks[lv] = c
                self.level_grid.addWidget(c, k // cols, k % cols)
            self._set_viewer_levels()
        self.lbl_levels.setVisible(is_alt)
        self.levels_box.setVisible(is_alt)
        self._refresh_levels()
        # Zona (la fuente puede proponer su dominio si no se pidió otra)
        has_zone = src.region_filter != "ninguno"
        self.lbl_zone.setVisible(has_zone)
        self.zone_box.setVisible(has_zone)
        default_region = getattr(src, "default_region", None)
        if has_zone and default_region and self._region is None:
            self.set_region(*default_region)
        self._refresh_steps_hint()
        self.adjustSize()

    def params(self):
        return self.form.values() if self.form is not None else {}

    def _refresh_levels(self):
        """Habilita cada casilla de nivel según los parámetros actuales
        (por ejemplo, intermedios sólo si se pidieron)."""
        if not self.level_checks:
            return
        p = self.source.merged_params(self.params())
        for lv, c in self.level_checks.items():
            ok = self.source.level_enabled(lv, p)
            c.setEnabled(ok)
            if not ok:
                c.setChecked(False)

    def _refresh_steps_hint(self):
        if self.source is None:
            return
        offered = set(self.source.steps(self.params()))
        chosen = self.hours()
        bad = [h for h in chosen if h not in offered]
        if bad:
            self.lbl_steps.setText(f"La fuente no ofrece los plazos: {', '.join(str(b) for b in bad)}")
        else:
            self.lbl_steps.setText(f"{len(chosen)} plazo(s): "
                                   + ", ".join(f"+{h}" for h in chosen[:12])
                                   + (" …" if len(chosen) > 12 else ""))

    def _set_viewer_levels(self):
        p = self.source.merged_params(self.params())
        fn = getattr(self.source, "viewer_levels_for", None)
        levels = fn(p) if fn else list(self.source.viewer_levels)
        self._set_levels(levels)

    def _set_levels(self, levels):
        p = self.source.merged_params(self.params())
        for lv, c in self.level_checks.items():
            c.setChecked(lv in levels and self.source.level_enabled(lv, p))

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
        self._domain_region = tuple(region)
        self.btn_domain.setEnabled(True)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.dest.text())
        if d:
            self.dest.setText(d)

    def hours(self):
        a, b, s = self.h_from.value(), self.h_to.value(), self.h_step.value()
        if b < a:
            a, b = b, a
        return list(range(a, b + 1, s))

    def job(self):
        """DownloadJob con lo elegido en el diálogo."""
        day, cyc = self.cb_run.currentData() or self.source.latest_run()
        region = None
        if self.source.region_filter != "ninguno" and not self.chk_global.isChecked():
            region = (self.lat_n.value(), self.lat_s.value(),
                      self.lon_w.value(), self.lon_e.value())
        return DownloadJob(
            run_date=day, cycle=cyc, steps=self.hours(),
            variables=[k for k, c in self.var_checks.items() if c.isChecked()],
            levels=[lv for lv, c in self.level_checks.items() if c.isChecked()],
            region=region, dest_dir=self.dest.text().strip() or ".",
            basename=self.name.text().strip() or None, merge=self.chk_merge.isChecked(),
            params=self.params(),
        )

    # ── Descarga ─────────────────────────────────────────────────────────────

    def _set_busy(self, busy):
        for w in self.findChildren(QWidget):
            if w not in (self.btn_cancel, self.progress, self.lbl_status):
                if isinstance(w, (QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
                                  QComboBox, QLineEdit)):
                    w.setEnabled(not busy)
        if not busy:
            self._on_global_toggled(self.chk_global.isChecked())
            self._refresh_levels()
            self.btn_domain.setEnabled(self._domain_region is not None)
        self.btn_cancel.setText("Cancelar" if busy else "Cerrar")

    def _cache(self):
        return DownloadCache(max_mb=float(self._cfg.get("cache_max_mb", 500)),
                             max_days=float(self._cfg.get("cache_max_days", 3)))

    def _start(self):
        job = self.job()
        err = self.source.validate(job)
        if err:
            QMessageBox.warning(self, "Obtener datos", err)
            return
        existing = [p for p in job.file_paths(self.source) if os.path.exists(p)]
        if existing:
            r = QMessageBox.question(
                self, "Obtener datos",
                f"Ya existe {os.path.basename(existing[0])}"
                + (f" y {len(existing) - 1} más" if len(existing) > 1 else "")
                + ". ¿Reemplazar?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self.downloaded_paths = []
        self._set_busy(True)
        self.progress.setValue(0)
        self.lbl_status.setText(f"Conectando con {self.source.name}…")
        self._worker = _Worker(self.source, job, self._cache(), self)
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
            QMessageBox.critical(self, "Obtener datos", error)
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
