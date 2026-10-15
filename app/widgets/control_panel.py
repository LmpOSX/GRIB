# -*- coding: utf-8 -*-
"""Panel derecho de controles del visor, imitando el panel de un sistema ATC:
franja STATUS (la ventana la pega al mapa) y secciones TIME, LEVEL, VARIABLE, VIENTO y MAPA.

No conoce el lector ni el mapa: expone señales y el estado seleccionado; la
ventana principal decide qué dibujar. Cualquier cambio de radio, botón de
nivel, combo o checkbox emite su señal para que la ventana redibuje sola.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QRadioButton, QButtonGroup, QPushButton, QComboBox, QCheckBox, QSpinBox,
    QLineEdit, QSizePolicy,
)

from ..grib_reader import FLIGHT_LEVELS, fl_to_hpa
from ..wind_plot import PROJECTIONS, HAVE_CARTOPY, WIND_STYLES, GRID_STEPS


class ControlPanel(QWidget):
    step_changed = pyqtSignal(int)          # índice del paso elegido
    level_changed = pyqtSignal()            # FL o nivel de presión
    variable_changed = pyqtSignal(str)      # 'viento' | 'temperatura' | 'ambos'
    options_changed = pyqtSignal()          # Viento / Extra Info / Grilla / Fondo / Densidad
    update_clicked = pyqtSignal()
    layer_toggled = pyqtSignal()            # Disable / Enable
    extent_applied = pyqtSignal(float, float, float, float)   # lon0, lon1, lat0, lat1
    full_extent_clicked = pyqtSignal()
    extent_invalid = pyqtSignal(str)        # mensaje para la ventana
    projection_changed = pyqtSignal(str)    # clave de PROJECTIONS
    fir_toggled = pyqtSignal(bool)          # capa de límites de FIR
    fir_neighbors_toggled = pyqtSignal(bool)
    fir_config_clicked = pyqtSignal()       # botón «FIR…»

    TIME_LABELS = ["Current (+0)", "Next (+1)", "Advanced (+2)"]
    P_COMBO_NONE = "(interpolar por FL)"            # archivo en niveles de presión
    P_COMBO_NONE_WAFS = "(el FL del botón elegido)"  # archivo WAFS: no se interpola
    P_LABEL = "Nivel de presión:"
    P_LABEL_WAFS = "Otro FL del archivo:"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level_mode = "fl"      # 'fl', 'p' o 'sfc' (fuente de superficie)
        self.surface = False
        self.wafs = False           # archivo WAFS: los FL son niveles exactos
        self.sel_fl = 300
        self.sel_p = None
        self._levels = []           # niveles de presión del archivo (hPa)
        self._updating = False      # evita señales mientras se llenan controles
        self._build()

    # ── Construcción ─────────────────────────────────────────────────────────

    def _section(self, title: str):
        frame = QFrame()
        frame.setObjectName("GlassPanel")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 5, 10, 7)
        lay.setSpacing(3)
        lbl = QLabel(title)
        lbl.setObjectName("PanelTitle")
        lay.addWidget(lbl)
        self._root.addWidget(frame)
        if not hasattr(self, "_sections"):
            self._sections = {}
        self._sections[title] = frame
        return lay

    @staticmethod
    def _sep(lay):
        """Línea fina entre grupos de una misma sección."""
        f = QFrame()
        f.setObjectName("PanelSep")
        f.setFixedHeight(1)
        lay.addSpacing(1)
        lay.addWidget(f)
        lay.addSpacing(1)

    @staticmethod
    def _sub(lay, text):
        lbl = QLabel(text)
        lbl.setObjectName("SubHeading")
        lay.addWidget(lbl)

    @staticmethod
    def _compact(cb):
        """El combo no impone su ancho al panel: el texto largo se recorta y
        el desplegable muestra las opciones completas."""
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(8)
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return cb

    def _build_status(self):
        """Franja STATUS: la ventana la coloca pegada al mapa (no va dentro
        del panel de controles)."""
        self.status = QFrame()
        self.status.setObjectName("StatusStrip")
        grid = QGridLayout(self.status)
        grid.setContentsMargins(10, 6, 10, 6)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(1)
        self.lbl_source = QLabel("FUENTE: --")
        self.lbl_run = QLabel("RUN: --")
        self.lbl_step = QLabel("STEP: --")
        self.lbl_valid_utc = QLabel("VALIDITY [--:-- – --:--] UTC")
        self.lbl_valid_loc = QLabel("LOCAL    [--:-- – --:--]")
        self.lbl_level = QLabel("LEVEL: --")
        for w in (self.lbl_source, self.lbl_run, self.lbl_step, self.lbl_valid_utc,
                  self.lbl_valid_loc, self.lbl_level):
            w.setObjectName("StatusMono")
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_source.setWordWrap(False)
        self.lbl_level.setWordWrap(True)
        # Columna 1: fuente (hasta tres renglones); columna 2: corrida y paso;
        # columna 3: validez; la última fila, el nivel, cruza las tres.
        grid.addWidget(self.lbl_source, 0, 0, 2, 1, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(self.lbl_run, 0, 1)
        grid.addWidget(self.lbl_step, 1, 1)
        grid.addWidget(self.lbl_valid_utc, 0, 2)
        grid.addWidget(self.lbl_valid_loc, 1, 2)
        grid.addWidget(self.lbl_level, 2, 0, 1, 3)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)

    def _build(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(6)
        self._build_status()

        # ── TIME ──
        lay = self._section("TIME")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        self._time_group = QButtonGroup(self)
        self.rb_time = []
        self.lbl_time = []
        for i, txt in enumerate(self.TIME_LABELS):
            rb = QRadioButton(txt)
            self._time_group.addButton(rb, i)
            lb = QLabel("--")
            lb.setObjectName("StatusMono")
            grid.addWidget(rb, i, 0)
            grid.addWidget(lb, i, 1)
            self.rb_time.append(rb)
            self.lbl_time.append(lb)
        self.rb_time[0].setChecked(True)
        self._time_group.idClicked.connect(self._on_time_radio)
        lay.addLayout(grid)
        self._steps_row = QWidget()
        row = QHBoxLayout(self._steps_row)
        row.setContentsMargins(0, 2, 0, 0)
        row.addWidget(QLabel("Todos los pasos:"))
        self.cb_steps = self._compact(QComboBox())
        self.cb_steps.currentIndexChanged.connect(self._on_step_combo)
        row.addWidget(self.cb_steps, 1)
        lay.addWidget(self._steps_row)
        self._steps_row.setVisible(False)

        # ── LEVEL ──
        lay = self._section("LEVEL")
        grid = QGridLayout()
        grid.setSpacing(3)
        self._fl_group = QButtonGroup(self)
        self._fl_group.setExclusive(True)
        self._fl_buttons = {}
        for k, fl in enumerate(FLIGHT_LEVELS):
            b = QPushButton(f"F{fl:03d}")
            b.setObjectName("FLBtn")
            b.setCheckable(True)
            b.setMinimumWidth(0)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            self._fl_group.addButton(b, fl)
            grid.addWidget(b, k // 4, k % 4)
            self._fl_buttons[fl] = b
        for c in range(4):
            grid.setColumnStretch(c, 1)
        self._fl_buttons[self.sel_fl].setChecked(True)
        self._fl_group.idClicked.connect(self._on_fl_clicked)
        lay.addLayout(grid)
        self._sep(lay)
        row = QHBoxLayout()
        self.lbl_press = QLabel(self.P_LABEL)
        row.addWidget(self.lbl_press)
        self.cb_press = self._compact(QComboBox())
        self.cb_press.addItem(self.P_COMBO_NONE)
        self.cb_press.currentIndexChanged.connect(self._on_press_combo)
        row.addWidget(self.cb_press, 1)
        lay.addLayout(row)
        self.lbl_fl_p = QLabel("")
        self.lbl_fl_p.setObjectName("SubHeading")
        self.lbl_fl_p.setWordWrap(True)
        lay.addWidget(self.lbl_fl_p)

        # ── VARIABLE ──
        lay = self._section("VARIABLE")
        row = QHBoxLayout()
        self._var_group = QButtonGroup(self)
        self._var_values = ["viento", "temperatura", "ambos"]
        self.rb_var = []
        for i, txt in enumerate(("Viento", "Temperatura", "Viento + Temp.")):
            rb = QRadioButton(txt)
            self._var_group.addButton(rb, i)
            row.addWidget(rb)
            self.rb_var.append(rb)
        row.addStretch()
        self.rb_var[0].setChecked(True)
        self._var_group.idClicked.connect(
            lambda i: self._emit_if_live(self.variable_changed, self._var_values[i]))
        lay.addLayout(row)

        # ── VIENTO: cómo se dibuja la capa de datos ──
        lay = self._section("VIENTO")
        row = QHBoxLayout()
        row.addWidget(QLabel("Estilo:"))
        self.cb_style = self._compact(QComboBox())
        for key, name in WIND_STYLES:
            self.cb_style.addItem(name, key)
        self.cb_style.setToolTip("Representación del viento: barbas, flechas (sólo dirección, "
                                 "color por velocidad) o curvas (líneas de corriente)")
        self.cb_style.currentIndexChanged.connect(lambda _i: self._emit_if_live(self.options_changed))
        row.addWidget(self.cb_style, 1)
        row.addSpacing(6)
        lbl = QLabel("cada")
        lbl.setToolTip("Densidad: dibujar un punto de grilla cada N (en curvas baja la "
                       "densidad de líneas)")
        row.addWidget(lbl)
        self.spin_stride = QSpinBox()
        self.spin_stride.setRange(1, 10)
        self.spin_stride.setValue(1)
        self.spin_stride.setToolTip(lbl.toolTip())
        self.spin_stride.valueChanged.connect(lambda _=0: self._emit_if_live(self.options_changed))
        row.addWidget(self.spin_stride)
        row.addWidget(QLabel("pts"))
        lay.addLayout(row)
        self._sep(lay)
        self._sub(lay, "Capas adicionales")
        self.chk_extra = QCheckBox("Extra Info (kt / °C junto a cada punto)")
        self.chk_fill = QCheckBox("Fondo de velocidad (contornos rellenos)")
        for c in (self.chk_extra, self.chk_fill):
            c.toggled.connect(lambda _=False: self._emit_if_live(self.options_changed))
            lay.addWidget(c)

        # ── MAPA: proyección, grilla y recuadro ──
        lay = self._section("MAPA")
        row = QHBoxLayout()
        row.addWidget(QLabel("Proyección:"))
        self.cb_proj = self._compact(QComboBox())
        for key, name in PROJECTIONS:
            self.cb_proj.addItem(name, key)
        if not HAVE_CARTOPY:
            self.cb_proj.setEnabled(False)
            self.cb_proj.setToolTip("Las proyecciones requieren cartopy")
        self.cb_proj.currentIndexChanged.connect(
            lambda i: self._emit_if_live(self.projection_changed, self.cb_proj.itemData(i)))
        row.addWidget(self.cb_proj, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Grilla de grados:"))
        self.cb_grid_step = self._compact(QComboBox())
        for val, name in GRID_STEPS:
            self.cb_grid_step.addItem(name, val)
        self.cb_grid_step.setToolTip("Meridianos y paralelos: cada 10°; cada 5° (secundarias a "
                                     "rayas); o cada 1° (principales cada 5°, secundarias punteadas)")
        self.cb_grid_step.currentIndexChanged.connect(
            lambda _i: self._emit_if_live(self.options_changed))
        row.addWidget(self.cb_grid_step, 1)
        self.chk_grid = QCheckBox("+ la del archivo")
        self.chk_grid.setToolTip("Grilla lat/lon del archivo (cada punto de la grilla), punteada")
        self.chk_grid.toggled.connect(lambda _=False: self._emit_if_live(self.options_changed))
        row.addWidget(self.chk_grid)
        lay.addLayout(row)
        # Límites de FIR: la ventana carga los polígonos y guarda la elección
        row = QHBoxLayout()
        self.chk_fir = QCheckBox("FIR Argentina")
        self.chk_fir.setToolTip("Dibujar los límites de las FIR Resistencia, Córdoba, Mendoza, "
                                "Ezeiza y Comodoro Rivadavia (Ctrl+Shift+F)")
        self.chk_fir.toggled.connect(lambda v: self._emit_if_live(self.fir_toggled, bool(v)))
        row.addWidget(self.chk_fir)
        self.chk_fir_nb = QCheckBox("+ vecinas")
        self.chk_fir_nb.setToolTip("Incluir, más tenues, las FIR limítrofes (Montevideo, Asunción, "
                                   "La Paz, Santiago, Punta Arenas, Curitiba, Brasilia, Atlántico, "
                                   "Johannesburgo Oceánico)")
        self.chk_fir_nb.toggled.connect(lambda v: self._emit_if_live(self.fir_neighbors_toggled, bool(v)))
        row.addWidget(self.chk_fir_nb)
        row.addStretch()
        self.btn_fir = QPushButton("FIR…")
        self.btn_fir.setFixedHeight(20)
        self.btn_fir.setToolTip("Elegir FIR, estilo, extremos y cobertura, y de dónde salen los límites")
        self.btn_fir.clicked.connect(self.fir_config_clicked.emit)
        row.addWidget(self.btn_fir)
        lay.addLayout(row)
        self._sep(lay)
        self._sub(lay, "Recuadro (lat/lon, Enter aplica)")
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self.ent_latmin = self._coord_entry(grid, "lat min", 0, 0, -90, 90)
        self.ent_latmax = self._coord_entry(grid, "lat max", 0, 2, -90, 90)
        self.ent_lonmin = self._coord_entry(grid, "lon min", 1, 0, -180, 180)
        self.ent_lonmax = self._coord_entry(grid, "lon max", 1, 2, -180, 180)
        lay.addLayout(grid)
        row = QHBoxLayout()
        btn_apply = QPushButton("Aplicar recuadro")
        btn_apply.clicked.connect(self._apply_extent)
        btn_full = QPushButton("Todo el dominio")
        btn_full.setToolTip("Volver a la grilla completa (Ctrl+Shift+0)")
        btn_full.clicked.connect(self.full_extent_clicked.emit)
        row.addWidget(btn_apply)
        row.addWidget(btn_full)
        row.addStretch()
        lay.addLayout(row)

        # Acciones globales: la ventana las coloca en la barra de acciones
        self.btn_update = QPushButton("Actualizar")
        self.btn_update.setToolTip("Redibujar el mapa (F5)")
        self.btn_update.clicked.connect(self.update_clicked.emit)
        self.btn_disable = QPushButton("Ocultar capa")
        self.btn_disable.setToolTip("Ocultar / mostrar la capa de datos (Ctrl+D)")
        self.btn_disable.clicked.connect(self.layer_toggled.emit)

        self._update_level_hint()

    def _coord_entry(self, grid, text, r, c, lo, hi):
        grid.addWidget(QLabel(text), r, c, alignment=Qt.AlignmentFlag.AlignRight)
        e = QLineEdit()
        v = QDoubleValidator(lo, hi, 4, e)
        v.setNotation(QDoubleValidator.Notation.StandardNotation)
        e.setValidator(v)
        e.setMaximumWidth(90)
        e.setMinimumWidth(40)
        e.returnPressed.connect(self._apply_extent)
        grid.addWidget(e, r, c + 1)
        return e

    def _emit_if_live(self, signal, *args):
        if not self._updating:
            signal.emit(*args)

    # ── Pasos ────────────────────────────────────────────────────────────────

    def populate(self, reader):
        """Llena pasos y niveles según el inventario del archivo."""
        self._updating = True
        try:
            steps = reader.steps
            n = len(steps)
            for i in range(3):
                if i < n:
                    self.rb_time[i].setEnabled(True)
                    self.lbl_time[i].setText(steps[i].label())
                else:
                    self.rb_time[i].setEnabled(False)
                    self.lbl_time[i].setText("--")
            self.rb_time[0].setChecked(True)
            self.cb_steps.clear()
            self.cb_steps.addItems([f"[{i}] {s.label()}" for i, s in enumerate(steps)])
            if n:
                self.cb_steps.setCurrentIndex(0)
            self._steps_row.setVisible(n > 3)

            self._levels = list(reader.levels)
            self.wafs = bool(getattr(reader, "is_wafs", False))
            # En WAFS cada botón de FL es un nivel exacto del archivo: el combo
            # sólo sirve para elegir alguno de los FL que no tienen botón.
            self.lbl_press.setText(self.P_LABEL_WAFS if self.wafs else self.P_LABEL)
            self.cb_press.clear()
            self.cb_press.addItem(self.P_COMBO_NONE_WAFS if self.wafs else self.P_COMBO_NONE)
            self.cb_press.setToolTip(
                "Los botones de FL caen en niveles exactos del archivo WAFS; acá se eligen "
                "los demás FL del archivo" if self.wafs else
                "Nivel del archivo sin interpolar; los botones de FL interpolan en ln(p)")
            label = getattr(reader, "level_label", None) or (lambda lv: f"{lv:g} hPa")
            self.cb_press.addItems([label(lv) for lv in self._levels])
            self.cb_press.setCurrentIndex(0)
            # Fuentes de superficie (viento 10 m / T 2 m): sin selector de nivel
            self.surface = getattr(reader, "kind", "altura") == "superficie"
            self._sections["LEVEL"].setVisible(not self.surface)
            self.level_mode = "sfc" if self.surface else "fl"
            self.sel_p = None
            self._fl_buttons[self.sel_fl].setChecked(True)
            self.set_extent_entries([float(reader.lons.min()), float(reader.lons.max()),
                                     float(reader.lats.min()), float(reader.lats.max())])
        finally:
            self._updating = False
        self._update_level_hint()

    def step_index(self) -> int:
        if self._steps_row.isVisible() or self.cb_steps.count() > 3:
            idx = self.cb_steps.currentIndex()
            if idx >= 0:
                return idx
        return max(0, self._time_group.checkedId())

    def _on_time_radio(self, idx: int):
        if self._updating:
            return
        self._updating = True
        try:
            if idx < self.cb_steps.count():
                self.cb_steps.setCurrentIndex(idx)
        finally:
            self._updating = False
        self.step_changed.emit(idx)

    def _on_step_combo(self, idx: int):
        if self._updating or idx < 0:
            return
        self._updating = True
        try:
            if idx < 3:
                self.rb_time[idx].setChecked(True)
            else:
                # Ningún radio corresponde: se destilda el que estuviera marcado
                self._time_group.setExclusive(False)
                for rb in self.rb_time:
                    rb.setChecked(False)
                self._time_group.setExclusive(True)
        finally:
            self._updating = False
        self.step_changed.emit(idx)

    # ── Niveles ──────────────────────────────────────────────────────────────

    def select_fl(self, fl: int):
        """Selección programática de un FL (equivale al clic)."""
        self._fl_buttons[fl].setChecked(True)
        self._on_fl_clicked(fl)

    def _on_fl_clicked(self, fl: int):
        self.sel_fl = fl
        self.level_mode = "fl"
        self.sel_p = None
        self._updating = True
        try:
            self.cb_press.setCurrentIndex(0)
        finally:
            self._updating = False
        self._update_level_hint()
        self.level_changed.emit()

    def select_pressure_index(self, idx: int):
        """Selección programática del combo de niveles (0 = el FL del botón)."""
        self.cb_press.setCurrentIndex(idx)

    def _on_press_combo(self, idx: int):
        if self._updating:
            return
        if idx <= 0 or idx - 1 >= len(self._levels):
            self.level_mode = "fl"
            self.sel_p = None
            self._fl_buttons[self.sel_fl].setChecked(True)
        else:
            self.level_mode = "p"
            self.sel_p = self._levels[idx - 1]
            # Sin FL seleccionado mientras se usa un nivel del archivo
            self._fl_group.setExclusive(False)
            for b in self._fl_buttons.values():
                b.setChecked(False)
            self._fl_group.setExclusive(True)
        self._update_level_hint()
        self.level_changed.emit()

    def _update_level_hint(self):
        if self.level_mode == "sfc":
            self.lbl_fl_p.setText("Superficie: viento 10 m, temperatura 2 m")
        elif self.level_mode == "fl":
            if getattr(self, "wafs", False):
                self.lbl_fl_p.setText(f"F{self.sel_fl:03d} = {fl_to_hpa(self.sel_fl):.1f} hPa (nivel WAFS)")
            else:
                self.lbl_fl_p.setText(f"F{self.sel_fl:03d} ≈ {fl_to_hpa(self.sel_fl):.1f} hPa (ISA)")
        elif getattr(self, "wafs", False):
            self.lbl_fl_p.setText(f"{self._fl_text(self.sel_p)} (nivel WAFS)")
        else:
            self.lbl_fl_p.setText(f"Nivel del archivo: {self.sel_p:g} hPa (sin interpolar)")

    @staticmethod
    def _fl_text(p_hpa):
        """'F200 = 46.6 hPa' si la presión es la de un FL entero, si no '46.6 hPa'."""
        from ..wafs_format import fl_from_hpa
        fl = fl_from_hpa(p_hpa)
        return f"F{fl:03d} = {p_hpa:g} hPa" if fl is not None else f"{p_hpa:g} hPa"

    # ── Variable y opciones ──────────────────────────────────────────────────

    def mode(self) -> str:
        return self._var_values[max(0, self._var_group.checkedId())]

    def set_mode(self, value: str):
        self._updating = True
        try:
            self.rb_var[self._var_values.index(value)].setChecked(True)
        finally:
            self._updating = False

    def options(self) -> dict:
        return {
            "wind_style": self.cb_style.currentData() or "barbas",
            "extra_info": self.chk_extra.isChecked(),
            "grid": self.chk_grid.isChecked(),
            "grid_step": int(self.cb_grid_step.currentData() or 10),
            "fill": self.chk_fill.isChecked(),
            "stride": int(self.spin_stride.value()),
        }

    def set_options(self, opts: dict):
        """Fija Viento / Extra Info / Grilla / Fondo / Densidad sin emitir
        señales (valores iniciales de la configuración o de Preferencias)."""
        self._updating = True
        try:
            if "wind_style" in opts:
                self.cb_style.setCurrentIndex(max(0, self.cb_style.findData(opts["wind_style"])))
            if "extra_info" in opts:
                self.chk_extra.setChecked(bool(opts["extra_info"]))
            if "grid" in opts:
                self.chk_grid.setChecked(bool(opts["grid"]))
            if "grid_step" in opts:
                self.cb_grid_step.setCurrentIndex(max(0, self.cb_grid_step.findData(int(opts["grid_step"]))))
            if "fill" in opts:
                self.chk_fill.setChecked(bool(opts["fill"]))
            if "stride" in opts:
                self.spin_stride.setValue(max(1, min(10, int(opts["stride"]))))
        finally:
            self._updating = False

    def set_fir_options(self, enabled: bool, neighbors: bool):
        """Casillas de FIR sin emitir señales (estado de la configuración)."""
        self._updating = True
        try:
            self.chk_fir.setChecked(bool(enabled))
            self.chk_fir_nb.setChecked(bool(neighbors))
            self.chk_fir_nb.setEnabled(bool(enabled))
        finally:
            self._updating = False

    def projection(self) -> str:
        return self.cb_proj.currentData() or "platecarree"

    def set_projection(self, key: str):
        """Selección programática (no emite la señal)."""
        idx = self.cb_proj.findData(key)
        if idx < 0:
            idx = 0
        self._updating = True
        try:
            self.cb_proj.setCurrentIndex(idx)
        finally:
            self._updating = False

    def set_layer_enabled(self, enabled: bool):
        self.btn_disable.setText("Ocultar capa" if enabled else "Mostrar capa")

    # ── STATUS ───────────────────────────────────────────────────────────────

    def set_status_texts(self, run: str, step: str, valid_utc: str, valid_local: str,
                         level: str, source: str = None):
        if source is not None:
            self.lbl_source.setText(source)
        self.lbl_run.setText(run)
        self.lbl_step.setText(step)
        self.lbl_valid_utc.setText(valid_utc)
        self.lbl_valid_loc.setText(valid_local)
        self.lbl_level.setText(level)

    # ── Recuadro ─────────────────────────────────────────────────────────────

    def set_extent_entries(self, extent):
        lon0, lon1, lat0, lat1 = extent
        for ent, val in ((self.ent_latmin, lat0), (self.ent_latmax, lat1),
                         (self.ent_lonmin, lon0), (self.ent_lonmax, lon1)):
            ent.setText(f"{val:.2f}")

    def _apply_extent(self):
        try:
            lat0 = float(self.ent_latmin.text().replace(",", "."))
            lat1 = float(self.ent_latmax.text().replace(",", "."))
            lon0 = float(self.ent_lonmin.text().replace(",", "."))
            lon1 = float(self.ent_lonmax.text().replace(",", "."))
        except ValueError:
            self.extent_invalid.emit("Ingresá valores numéricos en lat/lon mín/máx.")
            return
        if lat1 <= lat0 or lon1 <= lon0:
            self.extent_invalid.emit("Los máximos deben ser mayores que los mínimos.")
            return
        self.extent_applied.emit(lon0, lon1, lat0, lat1)
