# -*- coding: utf-8 -*-
"""Diálogo «Obtener datos…»: fuente, corrida y plazos entre los que la fuente
ofrece, variables, niveles (si es de altura), parámetros propios de la
fuente, área y destino. La descarga corre en un hilo con caché, progreso y
cancelación; al terminar puede abrir el archivo.

El bloque **Área** tiene dos modos excluyentes (ver app/areas.py): *manual*
(cuatro campos) y *por FIR* (una casilla por área habilitada en la
configuración; los campos se recalculan solos como la envolvente de las
marcadas más el margen y quedan bloqueados). Se recuerdan el último modo y
las casillas marcadas.

El bloque **Niveles** tiene cuatro botones excluyentes, INDRA, OACI, OACI56 y
WAFS, que tildan los niveles de presión que ese modo necesita
(fl_table.download_levels) y fijan el modo de conversión de esta descarga;
el que arranca es el de Preferencias ▸ WAFS. INDRA y OACI sin «Convertir a
WAFS» bajan los nominales tal cual, sin interpolar; con la casilla, o en
OACI56 y WAFS (56 FL que ningún modelo tiene: siempre interpolados, la
casilla queda tildada y bloqueada), se baja el rango completo de la fuente
para interpolar cada FL entre dos capas. Lo tildado a mano se suma; «Todos»
y «Ninguno» salen del modo."""
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QLineEdit, QRadioButton,
    QButtonGroup, QProgressBar, QFileDialog, QMessageBox, QWidget,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..sources import (DownloadJob, DownloadError, DownloadCancelled, enabled_sources,
                       get_source, source_config, source_label, all_sources)
from ..sources.cache import DownloadCache
from ..widgets.params_form import ParamsForm
from ..widgets.areas_editor import CoordEdit
from .. import areas as A
from .. import fl_table as flt

MODE_BUTTONS = {"INDRA": "INDRA (14)", "OACI": "OACI (17)", "OACI56": "OACI (56)", "WAFS": "WAFS (56)"}
WAFS_CHECK_TEXT = "Convertir a WAFS (FL cada 1000 ft, interpolado a presiones reales)"


class _Worker(QThread):
    progress = pyqtSignal(int, int, str, float)
    done = pyqtSignal(list, str)     # rutas escritas, mensaje de error ('' si ok)

    def __init__(self, source, job, cache, parent=None, wafs=None):
        super().__init__(parent)
        self._src, self._job, self._cache = source, job, cache
        self._wafs = wafs
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            paths = self._src.download(self._job, progress_cb=self.progress.emit,
                                       cancel=lambda: self._cancel, cache=self._cache,
                                       wafs=self._wafs)
            self.done.emit(paths, "")
        except DownloadCancelled:
            self.done.emit([], "cancelada")
        except DownloadError as exc:
            self.done.emit([], str(exc))
        except Exception as exc:          # pragma: no cover - imprevistos
            self.done.emit([], f"{type(exc).__name__}: {exc}")


class DownloadDialog(GlassDialog):
    """Devuelve en `downloaded_paths` las rutas bajadas si se aceptó."""

    def __init__(self, parent=None, cfg=None, dest_dir=".", region=None, source_key=None,
                 regions_fn=None):
        super().__init__(parent)
        self.setWindowTitle("Obtener datos")
        self.setMinimumWidth(700)
        self._cfg = cfg if cfg is not None else {}
        self.downloaded_paths = []
        self.open_after = True
        self.wafs_requested = True    # False: se bajó sin «Convertir a WAFS»
        self.last_provenance = None
        self._worker = None
        self._dest_dir = dest_dir
        self._region = region
        self._domain_region = None
        self._regions_fn = regions_fn       # capa FIR (para «Extremos de la capa FIR»)
        self._areas = [a for a in A.areas_from_config(self._cfg)]
        self._area_checks = {}
        self._area_updating = False
        self.source = None
        self._build_ui()
        key = source_key or self._cfg.get("source") or "gfs"
        idx = self.cb_source.findData(key)
        self.cb_source.setCurrentIndex(max(0, idx))
        self._on_source_changed()
        if region is not None:
            self.set_region(*region)
        self._refresh_area()

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
        self.mode_row_w = QWidget()
        row = QHBoxLayout(self.mode_row_w)
        row.setContentsMargins(0, 0, 0, 0)
        self.mode_buttons = {}
        self._mode = None            # modo elegido con los botones, o None (a mano)
        self._applying = False
        for m in flt.MODES:
            b = QPushButton(MODE_BUTTONS[m])
            b.setCheckable(True)
            b.setToolTip(flt.MODE_LABELS[m] + ". Tilda los niveles que necesita y fija el modo "
                         "de conversión de esta descarga.")
            b.clicked.connect(lambda _on, m=m: self._on_mode_clicked(m))
            self.mode_buttons[m] = b
            row.addWidget(b)
        row.addSpacing(16)
        for text, fn in (("Todos", lambda: self._set_manual(self.source.levels)),
                         ("Ninguno", lambda: self._set_manual([]))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lv_lay.addWidget(self.mode_row_w)
        self.lbl_levels_hint = QLabel("")
        self.lbl_levels_hint.setObjectName("Hint")
        self.lbl_levels_hint.setWordWrap(True)
        # Reserva dos renglones: el texto cambia de largo según el modo y lo
        # de abajo no tiene que moverse
        self.lbl_levels_hint.setMinimumHeight(2 * self.lbl_levels_hint.fontMetrics().lineSpacing() + 4)
        lv_lay.addWidget(self.lbl_levels_hint)
        lay.addWidget(self.levels_box)
        # Conversión a WAFS: va con los niveles porque decide cuáles se piden
        self.chk_wafs = QCheckBox(WAFS_CHECK_TEXT)
        self.chk_wafs.setChecked(bool(self._cfg.get("wafs_convert", True)))
        self.chk_wafs.toggled.connect(self._on_wafs_toggled)
        wrow = QHBoxLayout()
        wrow.addWidget(self.chk_wafs, 1)
        self.btn_wafs_prefs = QPushButton("Preferencias WAFS…")
        self.btn_wafs_prefs.setToolTip("Modo con el que arranca el diálogo, rango de FL, "
                                       "extrapolación y el valor por defecto de la casilla "
                                       "(Preferencias ▸ WAFS).")
        self.btn_wafs_prefs.clicked.connect(self._open_wafs_prefs)
        wrow.addWidget(self.btn_wafs_prefs)
        lay.addLayout(wrow)

        # ── Área ──
        self.lbl_zone = self._section(lay, "Área (grados; longitudes −180…180)")
        self.zone_box = QWidget()
        zl = QVBoxLayout(self.zone_box)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(4)
        row = QHBoxLayout()
        self.rb_manual = QRadioButton("Manual")
        self.rb_fir = QRadioButton("Por FIR")
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.rb_manual)
        self._mode_group.addButton(self.rb_fir)
        (self.rb_fir if self._cfg.get("download_area_mode", "fir") == "fir" else self.rb_manual).setChecked(True)
        self.rb_manual.toggled.connect(self._on_mode_changed)
        row.addWidget(self.rb_manual)
        row.addWidget(self.rb_fir)
        row.addSpacing(12)
        self.btn_areas = QPushButton("Configurar áreas…")
        self.btn_areas.clicked.connect(self._configure_areas)
        row.addWidget(self.btn_areas)
        row.addStretch()
        self.chk_draw = QCheckBox("Mostrar el área en el mapa")
        self.chk_draw.setChecked(bool(self._cfg.get("download_area_draw", False)))
        row.addWidget(self.chk_draw)
        zl.addLayout(row)
        # Casillas por FIR (una fila de cinco)
        self.fir_box = QWidget()
        fl = QVBoxLayout(self.fir_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(2)
        self.area_grid_w = QWidget()
        self.area_grid = QGridLayout(self.area_grid_w)
        self.area_grid.setContentsMargins(0, 0, 0, 0)
        self.area_grid.setHorizontalSpacing(10)
        self.area_grid.setVerticalSpacing(2)
        fl.addWidget(self.area_grid_w)
        row = QHBoxLayout()
        self.btn_all = QPushButton("Todas")
        self.btn_all.clicked.connect(lambda: self._set_all_areas(True))
        self.btn_none = QPushButton("Ninguna")
        self.btn_none.clicked.connect(lambda: self._set_all_areas(False))
        row.addWidget(self.btn_all)
        row.addWidget(self.btn_none)
        row.addSpacing(12)
        row.addWidget(QLabel("Margen"))
        self.spin_margin = QDoubleSpinBox()
        self.spin_margin.setRange(0.0, 10.0)
        self.spin_margin.setDecimals(2)
        self.spin_margin.setSingleStep(0.25)
        self.spin_margin.setSuffix("°")
        self.spin_margin.setValue(float(self._cfg.get("areas_margin_deg", A.DEFAULT_MARGIN_DEG)))
        self.spin_margin.setToolTip("Se suma por fuera a cada límite de la envolvente")
        self.spin_margin.valueChanged.connect(lambda _v: self._refresh_area())
        row.addWidget(self.spin_margin)
        row.addStretch()
        fl.addLayout(row)
        zl.addWidget(self.fir_box)
        self._build_area_checks()
        # Modo manual: todo el globo / dominio del archivo
        self.manual_box = QWidget()
        row = QHBoxLayout(self.manual_box)
        row.setContentsMargins(0, 0, 0, 0)
        self.chk_global = QCheckBox("Todo el globo")
        self.chk_global.toggled.connect(self._on_global_toggled)
        row.addWidget(self.chk_global)
        self.btn_domain = QPushButton("Dominio del archivo abierto")
        self.btn_domain.setEnabled(False)
        self.btn_domain.clicked.connect(
            lambda: self._domain_region and self.set_region(*self._domain_region))
        row.addWidget(self.btn_domain)
        row.addStretch()
        zl.addWidget(self.manual_box)
        # Cuatro campos en una fila (editables en manual, bloqueados por FIR)
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(6)
        fmt = self._cfg.get("areas_coord_format", "decimal")
        mr = self._cfg.get("download_manual_region") or [4.0, -64.0, -90.0, -22.0]
        self.lat_n = self._coord(g, "Lat N", 0, 0, "lat", float(mr[0]), fmt)
        self.lat_s = self._coord(g, "Lat S", 0, 2, "lat", float(mr[1]), fmt)
        self.lon_w = self._coord(g, "Lon W", 0, 4, "lon", float(mr[2]), fmt)
        self.lon_e = self._coord(g, "Lon E", 0, 6, "lon", float(mr[3]), fmt)
        g.setColumnStretch(8, 1)
        zl.addLayout(g)
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("Hint")
        self.lbl_size.setWordWrap(True)
        zl.addWidget(self.lbl_size)
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

    def _coord(self, grid, text, r, c, kind, val, fmt="decimal"):
        grid.addWidget(QLabel(text), r, c, alignment=Qt.AlignmentFlag.AlignRight)
        ed = CoordEdit(kind, val, fmt)
        ed.value_changed.connect(lambda _v: self._refresh_area())
        ed.invalid.connect(lambda msg: self.lbl_size.setText("Coordenada inválida: " + msg))
        grid.addWidget(ed, r, c + 1)
        return ed

    # ── Área ─────────────────────────────────────────────────────────────────

    def _build_area_checks(self):
        """Una casilla por área habilitada en la configuración."""
        self._clear_layout(self.area_grid)
        self._area_checks = {}
        wanted = set(self._cfg.get("download_area_codes") or A.ARGENTINA_CODES)
        enabled = [a for a in self._areas if a.enabled]
        cols = 5
        for k, a in enumerate(enabled):
            c = QCheckBox(f"{a.code}  {a.name}".strip())
            if a.verify:
                c.setToolTip(A.VERIFY_NOTE)
            c.setChecked(a.code in wanted)
            c.toggled.connect(lambda _on: self._refresh_area())
            self._area_checks[a.code] = c
            self.area_grid.addWidget(c, k // cols, k % cols)
        if not enabled:
            self.area_grid.addWidget(QLabel("No hay áreas habilitadas: Configurar áreas…"), 0, 0)

    def area_mode(self):
        return "fir" if self.rb_fir.isChecked() else "manual"

    def selected_codes(self):
        """Códigos marcados, en el orden de la tabla."""
        return [a.code for a in self._areas if a.code in self._area_checks
                and self._area_checks[a.code].isChecked()]

    def margin(self):
        return float(self.spin_margin.value())

    def fir_envelope(self):
        """Envolvente de las áreas marcadas más el margen, o None."""
        codes = set(self.selected_codes())
        return A.envelope([a for a in self._areas if a.code in codes], self.margin())

    def _set_all_areas(self, on):
        self._area_updating = True
        try:
            for c in self._area_checks.values():
                c.setChecked(on)
        finally:
            self._area_updating = False
        self._refresh_area()

    def _on_mode_changed(self, _checked):
        manual = self.rb_manual.isChecked()
        if manual:
            # Los campos calculados quedan como punto de partida
            env = self.fir_envelope() if not self.chk_global.isChecked() else None
            if env is not None:
                self._set_fields(env)
        self._refresh_area()

    def _set_fields(self, region):
        top, bottom, left, right = region
        for ed, v in ((self.lat_n, top), (self.lat_s, bottom), (self.lon_w, left), (self.lon_e, right)):
            ed.set_value(v)

    def _refresh_area(self):
        """Recalcula los campos (modo por FIR), habilita lo que corresponde
        y muestra el tamaño resultante."""
        if self._area_updating or not hasattr(self, "lbl_size"):
            return
        fir = self.area_mode() == "fir"
        self.fir_box.setVisible(fir)
        self.manual_box.setVisible(not fir)
        if fir:
            env = self.fir_envelope()
            if env is not None:
                self._set_fields(env)
        glob = (not fir) and self.chk_global.isChecked()
        for ed in (self.lat_n, self.lat_s, self.lon_w, self.lon_e):
            ed.setEnabled(not fir and not glob)
        region = self.region()
        if fir and not self.selected_codes():
            self.lbl_size.setText("Marcá al menos una FIR (o pasá a modo manual).")
        elif region is None:
            self.lbl_size.setText("Todo el globo.")
        else:
            res = self.source.grid_resolution(self.params()) if self.source is not None else None
            n_msgs = self._n_messages()
            txt = A.describe_size(region, res, n_msgs)
            notes = []
            if A.reaches_pole(region):
                notes.append("llega al polo")
            if A.crosses_greenwich(region):
                notes.append("cruza el meridiano de Greenwich")
            if fir:
                notes.append(f"margen {self.margin():g}° incluido")
            if notes:
                txt += "  ·  " + ", ".join(notes)
            self.lbl_size.setText(txt)

    def _n_messages(self):
        """Campos (variable × nivel × plazo) que se van a bajar, para la
        estimación de tamaño."""
        n_var = max(1, sum(1 for c in self.var_checks.values() if c.isChecked()))
        n_lev = max(1, sum(1 for c in self.level_checks.values() if c.isChecked())) \
            if self.level_checks else 1
        return n_var * n_lev * max(1, len(self.hours()))

    def region(self):
        """Zona (top, bottom, left, right) con lo elegido, o None (global /
        fuente sin zona)."""
        if self.source is not None and self.source.region_filter == "ninguno":
            return None
        if self.area_mode() == "fir":
            return self.fir_envelope()
        if self.chk_global.isChecked():
            return None
        return (self.lat_n.value(), self.lat_s.value(), self.lon_w.value(), self.lon_e.value())

    def _configure_areas(self):
        from .areas_dialog import AreasDialog
        dlg = AreasDialog(self, cfg=self._cfg, regions_fn=self._regions_fn)
        if dlg.exec():
            self._cfg.update(dlg.values())
            self._areas = A.areas_from_config(self._cfg)
            self._cfg["download_area_codes"] = self.selected_codes()
            self._build_area_checks()
            self.spin_margin.setValue(float(self._cfg.get("areas_margin_deg", A.DEFAULT_MARGIN_DEG)))
            fmt = self._cfg.get("areas_coord_format", "decimal")
            for ed in (self.lat_n, self.lat_s, self.lon_w, self.lon_e):
                ed.set_format(fmt)
            self._refresh_area()

    def area_state(self):
        """Claves de configuración con la última selección del bloque Área."""
        return {"download_area_mode": self.area_mode(),
                "download_area_codes": self.selected_codes(),
                "download_manual_region": [self.lat_n.value(), self.lat_s.value(),
                                           self.lon_w.value(), self.lon_e.value()],
                "download_area_draw": self.chk_draw.isChecked(),
                "areas_margin_deg": self.margin()}

    def _sync_area_to_cfg(self):
        self._cfg.update(self.area_state())

    def done(self, result):
        """Se recuerdan modo, casillas y zona manual aunque se cierre sin bajar."""
        try:
            self._sync_area_to_cfg()
        except Exception:
            pass
        super().done(result)

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
        self._refresh_wafs_check()
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
            c.toggled.connect(lambda _on: self._refresh_area())
            self.var_checks[vk] = c
            self.var_grid.addWidget(c, k // 5, k % 5)
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
            cols = 14
            for k, lv in enumerate(src.levels):
                c = QCheckBox(f"{lv}")
                c.toggled.connect(self._on_level_toggled)
                self.level_checks[lv] = c
                self.level_grid.addWidget(c, k // cols, k % cols)
        self.mode_row_w.setVisible(is_alt and not src.flight_levels)
        self.lbl_levels.setVisible(is_alt)
        self.levels_box.setVisible(is_alt)
        self._mode = flt.normalize_mode(self._cfg.get("wafs_mode", flt.DEFAULT_MODE))
        self._apply_mode()
        self._refresh_levels()
        # Zona (la fuente puede proponer su dominio si no se pidió otra)
        has_zone = src.region_filter != "ninguno"
        self.lbl_zone.setVisible(has_zone)
        self.zone_box.setVisible(has_zone)
        default_region = getattr(src, "default_region", None)
        if has_zone and default_region and self._region is None:
            self._set_fields(default_region)
        self._refresh_steps_hint()
        self._refresh_area()
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
        self._refresh_area()
        self._refresh_levels_hint()

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
        self._refresh_area()

    def _set_viewer_levels(self):
        """Vuelve a la selección del modo elegido (o a la sugerida por la
        fuente si no hay modo)."""
        if self._mode is not None and not self.source.flight_levels:
            self._apply_mode()
            return
        p = self.source.merged_params(self.params())
        fn = getattr(self.source, "viewer_levels_for", None)
        levels = fn(p) if fn else list(self.source.viewer_levels)
        self._set_levels(levels)

    def _set_levels(self, levels):
        p = self.source.merged_params(self.params())
        for lv, c in self.level_checks.items():
            c.setChecked(lv in levels and self.source.level_enabled(lv, p))
        self._refresh_levels_hint()

    def _set_manual(self, levels):
        """«Todos» / «Ninguno»: se sale del modo; la casilla WAFS se libera."""
        self._mode = None
        for b in self.mode_buttons.values():
            b.setChecked(False)
        self._refresh_wafs_check()
        self._set_levels(levels)

    def _on_mode_clicked(self, mode):
        self._mode = mode
        self._apply_mode()

    def _on_level_toggled(self, _on):
        self._refresh_area()
        self._refresh_levels_hint()

    def _on_wafs_toggled(self, _on):
        # Con o sin conversión cambian los niveles que necesita el modo
        if not self._applying and self._mode is not None and self.level_checks:
            self._apply_mode()
        self._refresh_levels_hint()

    def _wanted_levels(self):
        """Lo que pide el modo elegido a esta fuente (fl_table.download_levels)."""
        cfg = self._cfg
        return flt.download_levels(self._mode, self.source.levels, self.wafs_enabled(),
                                   fl_min=int(cfg.get("wafs_fl_min", flt.FL_LOWEST)),
                                   fl_max=int(cfg.get("wafs_fl_max", 530)),
                                   extend=bool(cfg.get("wafs_fl_extend", True)))

    def _apply_mode(self):
        """Tilda los niveles que necesita el modo elegido, enciende el
        parámetro de niveles extra de la fuente (intermedios del GFS) si
        hacen falta y se pueden pedir, y bloquea «Convertir a WAFS» en OACI56
        y WAFS, que sin conversión no existen."""
        if self._applying:
            return
        self._applying = True
        try:
            for m, b in self.mode_buttons.items():
                b.setChecked(m == self._mode)
            self._refresh_wafs_check()
            src = self.source
            if not self.level_checks:
                return
            if src.flight_levels or self._mode is None:
                self._set_levels(list(src.viewer_levels))
                return
            want = self._wanted_levels()["levels"]
            key = getattr(src, "extra_levels_param", None)
            w = self.form.widget(key) if (key and self.form is not None) else None
            if w is not None and not w.isChecked():
                p = src.merged_params(self.params())
                if any(not src.level_enabled(lv, p) for lv in want):
                    w.setChecked(True)          # dispara _refresh_levels
                    p = src.merged_params(self.params())
                    if any(not src.level_enabled(lv, p) for lv in want):
                        w.setChecked(False)     # la resolución no los permite
            self._set_levels(want)
        finally:
            self._applying = False
            self._refresh_levels_hint()

    def _refresh_levels_hint(self):
        """Qué se baja y qué sale: modo, cantidad de niveles, y los FL que
        quedan sin nivel (nominal que la fuente no tiene o que se destildó)."""
        if self.source is None or not self.level_checks or self.source.flight_levels:
            self.lbl_levels_hint.setText("")
            return
        on = [lv for lv, c in self.level_checks.items() if c.isChecked()]
        n = len(on)
        rng = f" ({max(on):g}–{min(on):g} hPa)" if on else ""
        if self._mode is None:
            txt = f"{n} nivel(es) elegido(s) a mano{rng}"
            txt += (" · se interpola a los FL del modo de Preferencias" if self.wafs_enabled()
                    else " · sin conversión: el archivo queda en esos niveles, sin interpolar")
            self.lbl_levels_hint.setText(txt)
            return
        want = self._wanted_levels()
        fls = flt.mode_fls(self._mode)
        if want["interpolated"]:
            txt = (f"Modo {MODE_BUTTONS[self._mode]}: {n} nivel(es){rng} para interpolar {len(fls)} FL a su "
                   f"presión ISA" + (" (etiqueta nominal)" if self._mode != "WAFS"
                                     else " (etiqueta = ISA en Pa)"))
            faltan = [lv for lv in want["levels"] if lv not in on]
            if faltan:
                txt += (f" · faltan {len(faltan)} de los {len(want['levels'])} niveles: "
                        f"los FL afectados se interpolan entre capas más separadas")
        else:
            txt = (f"Modo {MODE_BUTTONS[self._mode]} sin convertir: {n} nivel(es) nominales{rng} tal cual, "
                   f"sin interpolar; el archivo queda en la presión del modelo")
            miss = list(want["missing"]) + [fl for fl in fls if flt.nominal_hpa(fl) in want["levels"]
                                            and flt.nominal_hpa(fl) not in on]
            if miss:
                txt += " · sin nivel para " + ", ".join(flt.fl_label(fl) for fl in sorted(miss))
        self.lbl_levels_hint.setText(txt)

    def _on_global_toggled(self, _on):
        self._refresh_area()

    def set_region(self, top, bottom, left, right):
        """Zona manual explícita: pasa al modo manual con esos valores."""
        self.rb_manual.setChecked(True)      # (al pasar a manual se copia la envolvente)
        self._set_fields((top, bottom, left, right))
        self.chk_global.setChecked(False)
        self._refresh_area()

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
        region = self.region()
        mode = self.area_mode() if region is not None else "manual"
        return DownloadJob(
            run_date=day, cycle=cyc, steps=self.hours(),
            variables=[k for k, c in self.var_checks.items() if c.isChecked()],
            levels=[lv for lv, c in self.level_checks.items() if c.isChecked()],
            region=region, dest_dir=self.dest.text().strip() or ".",
            basename=self.name.text().strip() or None, merge=self.chk_merge.isChecked(),
            params=self.params(),
            suffix="_wafs" if self._wafs_options() is not None else "",
            area_mode=mode, area_codes=self.selected_codes() if mode == "fir" else [],
            area_margin=self.margin() if mode == "fir" else 0.0,
        )

    # ── Descarga ─────────────────────────────────────────────────────────────

    def _set_busy(self, busy):
        for w in self.findChildren(QWidget):
            if w not in (self.btn_cancel, self.progress, self.lbl_status):
                if isinstance(w, (QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox,
                                  QComboBox, QLineEdit, QRadioButton)):
                    w.setEnabled(not busy)
        if not busy:
            self._refresh_levels()
            self._refresh_area()
            self._refresh_wafs_check()
            self.btn_domain.setEnabled(self._domain_region is not None)
        self.btn_cancel.setText("Cancelar" if busy else "Cerrar")

    def _open_wafs_prefs(self):
        """Preferencias limitadas a la pestaña WAFS (las demás bloqueadas).
        Por la ventana principal si la hay (aplica y guarda); si no, el
        diálogo solo sobre la configuración recibida. Al aplicar, la casilla
        toma el nuevo «Convertir a WAFS por defecto»."""
        parent = self.parent()
        if parent is not None and hasattr(parent, "_open_settings"):
            applied = parent._open_settings(tab="WAFS", parent=self, only=True)   # sobre este diálogo
        else:
            from .settings_dialog import SettingsDialog
            dlg = SettingsDialog(self, cfg=self._cfg)
            dlg.lock_tab("WAFS")
            applied = bool(dlg.exec())
            if applied:
                self._cfg.update(dlg.values())
        if applied:
            if self.chk_wafs.isEnabled():
                self.chk_wafs.setChecked(bool(self._cfg.get("wafs_convert", True)))
            if self.level_checks and not self.source.flight_levels:
                self._mode = flt.normalize_mode(self._cfg.get("wafs_mode", flt.DEFAULT_MODE))
                self._apply_mode()

    def _refresh_wafs_check(self):
        """La casilla «Convertir a WAFS» sólo tiene sentido en fuentes de altura
        en niveles de presión; lo que ya viene por FL no se toca."""
        src = self.source
        self.chk_wafs.setText(WAFS_CHECK_TEXT)
        if src.kind != "altura":
            self.chk_wafs.setEnabled(False)
            self.chk_wafs.setToolTip("No aplica: fuente de superficie.")
        elif src.flight_levels:
            self.chk_wafs.setEnabled(False)
            self.chk_wafs.setToolTip("Ya viene por FL: no se toca.")
        elif self._mode in ("OACI56", "WAFS"):
            # 56 FL que ningún modelo tiene: sin conversión no existen
            self.chk_wafs.setChecked(True)
            self.chk_wafs.setEnabled(False)
            self.chk_wafs.setToolTip("OACI (56) y WAFS (56) son 56 FL que ningún modelo publica: "
                                     "siempre se interpolan.")
        else:
            self.chk_wafs.setEnabled(True)
            self.chk_wafs.setToolTip("El valor inicial es «Convertir a WAFS por defecto» de "
                                     "Preferencias ▸ WAFS. Sin marcar, el archivo queda en los "
                                     "niveles de presión de la fuente, sin interpolar.")

    def wafs_enabled(self):
        """True si esta descarga se convierte a WAFS: la casilla del diálogo
        (que arranca con «Convertir a WAFS por defecto» de Preferencias) en
        una fuente de altura en niveles de presión."""
        return (self.chk_wafs.isChecked() and self.source.kind == "altura"
                and not self.source.flight_levels)

    def _wafs_options(self):
        """Opciones de conversión a WAFS (rango y extrapolación de
        Preferencias ▸ WAFS; el modo, el del botón elegido), o None si la
        casilla del diálogo está sin marcar."""
        from ..wafs_format import options_from_config
        if not self.wafs_enabled():
            return None
        opts = options_from_config(dict(self._cfg, wafs_convert=True))
        if self._mode is not None:
            opts["mode"] = self._mode
        return opts

    def _cache(self):
        return DownloadCache(max_mb=float(self._cfg.get("cache_max_mb", 500)),
                             max_days=float(self._cfg.get("cache_max_days", 3)))

    def _start(self):
        if self.area_mode() == "fir" and self.source.region_filter != "ninguno" \
                and not self.selected_codes():
            QMessageBox.warning(self, "Obtener datos",
                                "Marcá al menos una FIR en el bloque Área, o pasá a modo manual.")
            return
        job = self.job()
        err = self.source.validate(job)
        if err:
            QMessageBox.warning(self, "Obtener datos", err)
            return
        self._sync_area_to_cfg()
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
        self._worker = _Worker(self.source, job, self._cache(), self, wafs=self._wafs_options())
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
        self.wafs_requested = self.wafs_enabled()
        self.lbl_status.setText("Descarga completa: " + ", ".join(os.path.basename(p) for p in paths))
        from ..sources import read_provenance
        self.last_provenance = read_provenance(paths[0]) if paths else None
        aviso = ((self.last_provenance or {}).get("area") or {}).get("aviso")
        if aviso:
            QMessageBox.warning(self, "Obtener datos", aviso)
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
