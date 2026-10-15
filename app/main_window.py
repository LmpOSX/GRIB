# -*- coding: utf-8 -*-
"""Ventana principal del Visor GRIB (PyQt6).

Esqueleto tomado de la base gráfica: tema generado desde el color de acento,
zoom de fuente, menús, preferencias, bienvenida con recientes, geometría
persistida y un único atajo Escape. Sobre eso, el mapa matplotlib (QtAgg)
a la izquierda y el panel de controles ATC a la derecha.
"""
import csv
import os
import traceback

import numpy as np

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QApplication, QMessageBox, QMenuBar, QFileDialog, QStatusBar, QScrollArea,
    QLabel, QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QAction, QActionGroup, QCursor
from PyQt6.QtWidgets import QToolTip

from .config import (
    load_config, save_config, FONT_SIZE_MIN, FONT_SIZE_MAX,
    push_recent_file, remove_recent_file, working_dir, RECENT_FILES_MAX,
)
from .theme import build_stylesheet, generate_palette
from .grib_reader import KELVIN, fl_to_hpa, fmt_dt, speed_dir_from_uv
from .dialogs.settings_dialog import SettingsDialog
from . import areas as areasmod
from .widgets.welcome_widget import WelcomeWidget
from .widgets.control_panel import ControlPanel
from .wind_plot import PROJECTIONS, WIND_STYLES, GRID_STEPS
from .widgets.inventory_panel import InventoryPanel
from .sources import enabled_sources, all_sources, get_source, source_label, read_provenance
from . import fir as firmod

APP_TITLE = "Visor GRIB"
GRIB_FILTER = "GRIB (*.grib2 *.grb2 *.grib *.grb);;Todos los archivos (*)"
PANEL_WIDTH = 390


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg = load_config()
        self._reader = None            # GribReader del archivo abierto
        self._path: str | None = None  # ruta del archivo abierto
        self._current = None           # campos del paso/nivel dibujados (hover, CSV)
        self._layer_enabled = True     # capa de datos visible (Disable/Enable)
        self._provenance = None        # procedencia del archivo abierto (fuente, corrida…)
        self._fir_regions = {}         # código → fir.FirRegion cargadas para la capa
        self._fir_notes = []           # de dónde salió cada una (para el diálogo)

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._apply_theme(self._cfg["accent_color"])
        self._build_ui()
        self._restore_geometry()
        self._register_shortcuts()
        self._set_empty_state(True)
        self._update_title()
        self._on_theme_applied()

    # ── Tema ──────────────────────────────────────────────────────────────────

    def _apply_theme(self, accent: str = None, font_size: int = None,
                     opacity: int = None):
        """Único punto que aplica el tema (color de acento, tamaño de fuente y
        opacidad) a toda la aplicación."""
        if accent is not None:
            self._cfg["accent_color"] = accent
        if font_size is not None:
            self._cfg["font_size"] = font_size
        if opacity is not None:
            self._cfg["opacity"] = opacity
        QApplication.instance().setStyleSheet(
            build_stylesheet(self._cfg["accent_color"], self._cfg["font_size"],
                             self._cfg.get("opacity", 180))
        )
        app_font = QApplication.instance().font()
        app_font.setPointSize(self._cfg["font_size"])
        QApplication.instance().setFont(app_font)
        self._on_theme_applied()

    def _on_theme_applied(self):
        """El mapa no se estiliza por QSS: toma los colores de la paleta del
        tema y se redibuja si hay archivo abierto."""
        plot = getattr(self, "plot", None)
        if plot is None:
            return
        # El panel lateral crece con el tamaño de fuente para no cortarse
        scale = self._cfg.get("font_size", 13) / 13.0
        self._side.setFixedWidth(int(PANEL_WIDTH * scale))
        p = generate_palette(self._cfg["accent_color"])
        # Fuentes del mapa escaladas con el zoom de fuente (13 = tamaño base)
        plot.set_font_scale(self._cfg.get("font_size", 13) / 13.0)
        # Fondo del mapa con la misma transparencia que la ventana
        plot.set_opacity(self._cfg.get("opacity", 180) / 255.0)
        plot.set_palette(
            bg=p["bg_data"].name(), ax_bg=p["bg_data"].name(),
            text=p["text_bright"].name(), text_dim=p["text_dim"].name(),
            coast=p["text_bright"].name(), border=p["text_dim"].name(),
            grid=p["text_dim"].name(), grid_fine=p["mid"].name(),
            legend_bg=p["bg1"].name(), warn=p["accent_light"].name(),
        )
        if self._reader is not None:
            self.redraw()
        else:
            plot.draw_empty()

    def _register_shortcuts(self):
        for seq in ("Ctrl++", "Ctrl+=", "Alt++", "Alt+="):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_up)
        for seq in ("Ctrl+-", "Alt+-"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_down)
        for seq in ("Ctrl+0", "Alt+0"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_reset)
        # Único Escape de toda la ventana (otro en un hijo lo vuelve ambiguo)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._on_escape)

    def _font_size_up(self):
        sz = min(self._cfg["font_size"] + 1, FONT_SIZE_MAX)
        if sz != self._cfg["font_size"]:
            self._apply_theme(font_size=sz)
            save_config(self._cfg)

    def _font_size_down(self):
        sz = max(self._cfg["font_size"] - 1, FONT_SIZE_MIN)
        if sz != self._cfg["font_size"]:
            self._apply_theme(font_size=sz)
            save_config(self._cfg)

    def _font_size_reset(self):
        if self._cfg["font_size"] != 13:
            self._apply_theme(font_size=13)
            save_config(self._cfg)

    def _on_escape(self):
        """Único atajo Escape de la ventana: devuelve el foco al mapa (el pan
        por arrastre y el zoom con la rueda no tienen modo que cancelar)."""
        if self._reader is not None:
            self.plot.canvas.setFocus()

    # ── Interfaz ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("MainContainer")
        self.setCentralWidget(central)

        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ── Panel de controles (menús, barra de acciones y mapa usan partes suyas) ──
        self.panel = ControlPanel()
        self.panel.set_projection(self._cfg.get("projection", "platecarree"))
        self.panel.set_options(self._map_options_from_cfg())

        self._menubar = QMenuBar()
        self._menubar.setObjectName("AppMenuBar")
        root_lay.addWidget(self._menubar)
        self._setup_file_menu()
        self._setup_view_menu()
        self._setup_help_menu()

        # ── Barra de acciones ──
        root_lay.addWidget(self._build_action_bar())

        # ── Contenido ──
        self._content = QWidget()
        self._content.setObjectName("ContentPanel")
        content_lay = QVBoxLayout(self._content)
        content_lay.setContentsMargins(8, 6, 8, 6)
        content_lay.setSpacing(0)

        # Área principal: mapa + panel de controles
        self._main_area = QWidget()
        self._main_lay = QHBoxLayout(self._main_area)
        self._main_lay.setContentsMargins(0, 0, 0, 0)
        self._main_lay.setSpacing(8)
        self._build_main_area()

        # ── Bienvenida ──
        self._welcome = WelcomeWidget()
        self._welcome.open_clicked.connect(self._file_open)
        self._welcome.recent_clicked.connect(self._open_recent)

        content_lay.addWidget(self._main_area, 1)
        content_lay.addWidget(self._welcome, 1)
        root_lay.addWidget(self._content, 1)

        # ── Barra de estado ──
        self._statusbar = QStatusBar()
        self._statusbar.setSizeGripEnabled(False)
        self.setStatusBar(self._statusbar)
        self.set_status("Listo.")

    def _build_main_area(self):
        """Mapa (izquierda) y panel de controles con inventario (derecha)."""
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
        from .wind_plot import WindPlot

        # ── Mapa ──
        map_frame = QFrame()
        map_frame.setObjectName("GlassPanel")
        map_lay = QVBoxLayout(map_frame)
        map_lay.setContentsMargins(6, 6, 6, 6)
        map_lay.setSpacing(6)
        # STATUS pegado al mapa: describe lo que se ve
        map_lay.addWidget(self.panel.status)
        self.plot = WindPlot(map_frame)
        self.plot.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        map_lay.addWidget(self.plot.canvas, 1)
        # La toolbar de matplotlib implementa zoom/pan pero sus íconos negros
        # no se ven sobre fondo oscuro: queda oculta y se maneja con botones
        # propios en la barra de acciones.
        self._toolbar = NavigationToolbar2QT(self.plot.canvas, map_frame)
        self._toolbar.hide()
        # Sólo se usa su historial de vistas (Inicio); su manejador de
        # movimiento cambiaría el cursor que fija el pan por arrastre.
        try:
            self.plot.canvas.mpl_disconnect(self._toolbar._id_drag)
        except Exception:
            pass
        self.plot.on_view_push = self._toolbar.push_current
        self._main_lay.addWidget(map_frame, 1)

        # ── Panel derecho, fijo (sólo el inventario se desplaza) ──
        side = QWidget()
        side.setObjectName("SidePanel")
        side.setAutoFillBackground(False)
        side.setFixedWidth(PANEL_WIDTH)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(6)
        self.plot.set_projection(self.panel.projection())
        side_lay.addWidget(self.panel)
        inv_frame = QFrame()
        inv_frame.setObjectName("GlassPanel")
        inv_lay = QVBoxLayout(inv_frame)
        inv_lay.setContentsMargins(12, 6, 12, 8)
        inv_title = QLabel("INVENTARIO")
        inv_title.setObjectName("PanelTitle")
        inv_lay.addWidget(inv_title)
        self.inventory = InventoryPanel()
        inv_lay.addWidget(self.inventory)
        side_lay.addWidget(inv_frame, 1)        # el inventario absorbe el alto que sobra
        self._side = side
        self._main_lay.addWidget(side)

        # ── Señales del panel: cualquier cambio redibuja solo ──
        self._side.setVisible(bool(self._cfg.get("panel_visible", True)))
        self.panel.step_changed.connect(lambda _i: self.redraw())
        self.panel.level_changed.connect(self.redraw)
        self.panel.variable_changed.connect(lambda _m: self.redraw())
        self.panel.options_changed.connect(self._on_panel_options_changed)
        self.panel.update_clicked.connect(self.redraw)
        self.panel.layer_toggled.connect(self.toggle_layer)
        self.panel.extent_applied.connect(self.apply_extent)
        self.panel.full_extent_clicked.connect(self.full_extent)
        self.panel.extent_invalid.connect(
            lambda msg: QMessageBox.warning(self, "Recuadro", msg))
        self.panel.projection_changed.connect(self.set_projection)
        self.panel.fir_toggled.connect(self.set_fir_enabled)
        self.panel.fir_neighbors_toggled.connect(self.set_fir_neighbors)
        self.panel.fir_config_clicked.connect(self.open_fir_dialog)

        # ── Capa de límites de FIR ──
        self.plot.on_click = self._on_map_click
        self._load_fir_layer(redraw=False)
        self._apply_area_layer(redraw=False)

        # ── Eventos del canvas ──
        self.plot.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.plot.canvas.mpl_connect("draw_event", self._on_draw)
        self.plot.canvas.mpl_connect("scroll_event", self._on_scroll)

    def _map_options_from_cfg(self) -> dict:
        c = self._cfg
        return {"wind_style": c.get("map_wind_style", "barbas"),
                "extra_info": c.get("map_extra_info", False), "grid": c.get("map_grid", False),
                "grid_step": c.get("map_grid_step", 10),
                "fill": c.get("map_fill", False), "stride": c.get("map_stride", 1)}

    def _on_panel_options_changed(self):
        """VIENTO / MAPA del panel: se guarda como valor inicial y se redibuja."""
        o = self.panel.options()
        self._cfg.update({"map_wind_style": o["wind_style"], "map_extra_info": o["extra_info"],
                          "map_grid": o["grid"], "map_grid_step": o["grid_step"],
                          "map_fill": o["fill"], "map_stride": o["stride"]})
        save_config(self._cfg)
        self._sync_view_menu()
        self.redraw()

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ActionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(6)

        # Grupo «datos»: abrir, fuente y descarga
        open_btn = QPushButton("Abrir GRIB…")
        open_btn.setToolTip("Abrir un archivo GRIB2 (Ctrl+O)")
        open_btn.clicked.connect(self._file_open)
        lay.addWidget(open_btn)
        # «Fuente» y su selector forman un solo control con borde
        group = QFrame()
        group.setObjectName("SourceGroup")
        g_lay = QHBoxLayout(group)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.setSpacing(0)
        lbl = QLabel("Fuente")
        g_lay.addWidget(lbl)
        self.cb_source = QComboBox()
        self.cb_source.setToolTip("Fuente de datos; se configura en Preferencias ▸ Fuentes. "
                                  "✓ FL = publica los niveles OACI por nivel de vuelo")
        self._refresh_sources_combo()
        self.cb_source.currentIndexChanged.connect(self._on_source_combo)
        g_lay.addWidget(self.cb_source)
        lay.addWidget(group)
        dl_btn = QPushButton("Obtener datos…")
        dl_btn.setToolTip("Elegir corrida, plazos, variables, niveles y zona de la fuente "
                          "y descargar (Ctrl+Shift+D)")
        dl_btn.clicked.connect(self.get_data)
        lay.addWidget(dl_btn)

        # Acciones que dependen de un archivo abierto
        self._bar_file_area = QWidget()
        self._bar_file_lay = QHBoxLayout(self._bar_file_area)
        self._bar_file_lay.setContentsMargins(0, 0, 0, 0)
        self._bar_file_lay.setSpacing(6)
        self._bar_file_lay.addWidget(self._action_sep())
        self._build_file_actions(self._bar_file_lay)
        lay.addWidget(self._bar_file_area)

        lay.addStretch()

        self._btn_panel = QPushButton("▥")
        self._btn_panel.setCheckable(True)
        self._btn_panel.setChecked(bool(self._cfg.get("panel_visible", True)))
        self._btn_panel.setToolTip("Mostrar u ocultar el panel lateral (Ctrl+Shift+P); "
                                   "al ocultarlo el mapa ocupa todo el ancho")
        self._btn_panel.setFixedWidth(32)
        self._btn_panel.toggled.connect(self.set_panel_visible)
        lay.addWidget(self._btn_panel)
        settings_btn = QPushButton("⚙")
        settings_btn.setToolTip("Preferencias (Ctrl+,)")
        settings_btn.setFixedWidth(32)
        settings_btn.clicked.connect(self._open_settings)
        lay.addWidget(settings_btn)
        return bar

    def _refresh_sources_combo(self):
        """Fuentes habilitadas en el selector; conserva la elegida."""
        cb = self.cb_source
        cb.blockSignals(True)
        try:
            cb.clear()
            for src in (enabled_sources(self._cfg) or all_sources()):
                cb.addItem(source_label(src), src.key)
            idx = cb.findData(self._cfg.get("source", "gfs"))
            cb.setCurrentIndex(max(0, idx))
        finally:
            cb.blockSignals(False)

    def _on_source_combo(self, _idx):
        key = self.cb_source.currentData()
        if key:
            self._cfg["source"] = key
            save_config(self._cfg)

    @staticmethod
    def _action_sep() -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.Shape.NoFrame)
        s.setObjectName("ActionSep")
        s.setFixedSize(10, 22)
        return s

    def _build_file_actions(self, lay: QHBoxLayout):
        """Botones del mapa en la barra de acciones (reemplazan la toolbar de
        matplotlib, que queda oculta)."""
        self._btn_home = QPushButton("Inicio")
        self._btn_home.setToolTip("Volver a la vista inicial del mapa "
                                  "(arrastrar = pan, rueda = zoom)")
        self._btn_home.clicked.connect(self._map_home)
        self._btn_png = QPushButton("Guardar PNG")
        self._btn_png.setToolTip("Exportar la vista actual a PNG (Ctrl+E)")
        self._btn_png.clicked.connect(self.export_png)
        lay.addWidget(self._btn_home)
        lay.addWidget(self.panel.btn_update)
        lay.addWidget(self.panel.btn_disable)
        lay.addWidget(self._action_sep())
        lay.addWidget(self._btn_png)

    def _map_home(self):
        """Vista inicial (historial de la toolbar oculta de matplotlib)."""
        self._toolbar.home()

    # ── Menús ────────────────────────────────────────────────────────────────

    def _setup_file_menu(self):
        archivo = self._menubar.addMenu("Archivo")
        self._act_open = self._add_action(archivo, "Abrir GRIB…", self._file_open, "Ctrl+O")
        self._act_download = self._add_action(archivo, "Obtener datos…", self.get_data,
                                              "Ctrl+Shift+D")
        self._recent_menu = archivo.addMenu("Recientes")
        self._refresh_recent_menu()
        archivo.addSeparator()
        self._act_export_png = self._add_action(
            archivo, "Exportar PNG…", self.export_png, "Ctrl+E")
        self._act_export_csv = self._add_action(
            archivo, "Exportar CSV…", self.export_csv, "Ctrl+Shift+E")
        self._act_export_wafs = self._add_action(
            archivo, "Exportar a WAFS…", self.export_wafs, "Ctrl+Shift+W")
        archivo.addSeparator()
        self._act_close = self._add_action(archivo, "Cerrar archivo", self._file_close, "Ctrl+W")
        archivo.addSeparator()
        act_quit = self._add_action(archivo, "Salir", self.close, "Ctrl+Q")
        act_quit.setMenuRole(QAction.MenuRole.QuitRole)

    def _setup_view_menu(self):
        vista = self._menubar.addMenu("Vista")
        # Ctrl+0 queda para el tamaño de fuente; el dominio usa Ctrl+Shift+0
        self._act_full = self._add_action(vista, "Todo el dominio", self.full_extent,
                                          "Ctrl+Shift+0")
        self._act_update = self._add_action(vista, "Actualizar", self.redraw, "F5")
        self._act_layer = self._add_action(vista, "Capa de datos activada",
                                           self.toggle_layer, "Ctrl+D")
        self._act_layer.setCheckable(True)
        self._act_layer.setChecked(True)
        self._act_panel = self._add_action(vista, "Panel lateral", self.set_panel_visible,
                                           "Ctrl+Shift+P")
        self._act_panel.setCheckable(True)
        self._act_panel.setChecked(bool(self._cfg.get("panel_visible", True)))
        vista.addSeparator()
        # Mismas opciones que el panel (VIENTO / MAPA), sincronizadas
        self._menu_proj = vista.addMenu("Proyección")
        self._proj_actions = {}
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for key, name in PROJECTIONS:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setData(key)
            act.triggered.connect(lambda _c, k=key: self._menu_set_projection(k))
            grp.addAction(act)
            self._menu_proj.addAction(act)
            self._proj_actions[key] = act
        self._menu_style = vista.addMenu("Viento")
        self._style_actions = {}
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for key, name in WIND_STYLES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setData(key)
            act.triggered.connect(lambda _c, k=key: self._menu_set_option("wind_style", k))
            grp.addAction(act)
            self._menu_style.addAction(act)
            self._style_actions[key] = act
        self._act_extra = self._add_action(vista, "Extra Info",
                                           lambda c: self._menu_set_option("extra_info", c))
        self._act_fill = self._add_action(vista, "Fondo de velocidad",
                                          lambda c: self._menu_set_option("fill", c))
        self._menu_grid = vista.addMenu("Grilla de grados")
        self._grid_actions = {}
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for val, name in GRID_STEPS:
            act = QAction(name, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _c, v=val: self._menu_set_option("grid_step", v))
            grp.addAction(act)
            self._menu_grid.addAction(act)
            self._grid_actions[val] = act
        self._act_grid = self._add_action(vista, "Grilla lat/lon del archivo",
                                          lambda c: self._menu_set_option("grid", c))
        for act in (self._act_extra, self._act_fill, self._act_grid):
            act.setCheckable(True)
        # Límites de FIR
        self._menu_fir = vista.addMenu("FIR")
        self._act_fir = self._add_action(self._menu_fir, "Límites de FIR de Argentina",
                                         self.set_fir_enabled, "Ctrl+Shift+F")
        self._act_fir_nb = self._add_action(self._menu_fir, "Incluir FIR vecinas",
                                            self.set_fir_neighbors)
        for act in (self._act_fir, self._act_fir_nb):
            act.setCheckable(True)
        self._menu_fir.addSeparator()
        self._add_action(self._menu_fir, "Extremos y cobertura…", lambda: self.open_fir_dialog(1))
        self._add_action(self._menu_fir, "Configurar FIR…", lambda: self.open_fir_dialog(0))
        self._menu_fir.addSeparator()
        self._act_area = self._add_action(self._menu_fir, "Rectángulos del área de descarga",
                                          self.set_area_draw)
        self._act_area.setCheckable(True)
        self._add_action(self._menu_fir, "Áreas de descarga…", self.open_areas_dialog)
        self._sync_view_menu()
        vista.addSeparator()
        act_prefs = self._add_action(vista, "Preferencias…", self._open_settings, "Ctrl+,")
        act_prefs.setMenuRole(QAction.MenuRole.PreferencesRole)

    def set_panel_visible(self, visible: bool):
        """Muestra u oculta el panel lateral; el mapa ocupa el ancho que
        queda. Se guarda en la configuración."""
        visible = bool(visible)
        self._side.setVisible(visible)
        for w in (self._btn_panel, self._act_panel):
            w.blockSignals(True)
            w.setChecked(visible)
            w.blockSignals(False)
        if self._cfg.get("panel_visible", True) != visible:
            self._cfg["panel_visible"] = visible
            save_config(self._cfg)

    def _sync_view_menu(self):
        """Refleja en el menú Vista lo que muestra el panel."""
        o = self.panel.options()
        pairs = [(self._act_extra, o["extra_info"]), (self._act_fill, o["fill"]),
                 (self._act_grid, o["grid"])]
        for act, val in pairs:
            act.blockSignals(True)
            act.setChecked(bool(val))
            act.blockSignals(False)
        act = self._style_actions.get(o["wind_style"])
        if act is not None:
            act.setChecked(True)
        act = self._grid_actions.get(o["grid_step"])
        if act is not None:
            act.setChecked(True)
        act = self._proj_actions.get(self.panel.projection())
        if act is not None:
            act.setChecked(True)
        if hasattr(self, "_act_fir"):
            on = bool(self._cfg.get("fir_enabled", False))
            nb = bool(self._cfg.get("fir_neighbors", False))
            for act, val in ((self._act_fir, on), (self._act_fir_nb, nb)):
                act.blockSignals(True)
                act.setChecked(val)
                act.blockSignals(False)
            self._act_fir_nb.setEnabled(on)
            self.panel.set_fir_options(on, nb)
        if hasattr(self, "_act_area"):
            self._act_area.blockSignals(True)
            self._act_area.setChecked(bool(self._cfg.get("download_area_draw", False)))
            self._act_area.blockSignals(False)

    def _menu_set_option(self, key, value):
        """Opción de VIENTO / MAPA elegida desde el menú: se refleja en el
        panel, se guarda y se redibuja."""
        self.panel.set_options({key: value})
        self._on_panel_options_changed()

    def _menu_set_projection(self, key):
        self.panel.set_projection(key)
        self.set_projection(key)

    def _setup_help_menu(self):
        ayuda = self._menubar.addMenu("Ayuda")
        self._add_action(ayuda, "Atajos de teclado…", self._show_shortcuts, "Ctrl+/")
        ayuda.addSeparator()
        act_about = self._add_action(ayuda, "Acerca de Visor GRIB", self._show_about)
        act_about.setMenuRole(QAction.MenuRole.AboutRole)

    def _add_action(self, menu, text, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        menu.addAction(act)
        return act

    def _show_shortcuts(self):
        from .dialogs.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _show_about(self):
        from .dialogs.about_dialog import AboutDialog
        AboutDialog(self).exec()

    # ── Recientes ─────────────────────────────────────────────────────────────

    def _refresh_recent_menu(self):
        """Reconstruye el submenú Recientes desde la configuración."""
        if not hasattr(self, "_recent_menu"):
            return
        self._recent_menu.clear()
        recents = (self._cfg.get("recent_files") or [])[:RECENT_FILES_MAX]
        if not recents:
            empty_act = self._recent_menu.addAction("(vacío)")
            empty_act.setEnabled(False)
            return
        for path in recents:
            name = os.path.basename(path) or path
            act = self._recent_menu.addAction(name)
            act.setToolTip(path)
            if not os.path.exists(path):
                act.setEnabled(False)
            act.triggered.connect(lambda checked, p=path: self._open_recent(p))
        self._recent_menu.addSeparator()
        clear_act = self._recent_menu.addAction("Vaciar lista")
        clear_act.triggered.connect(self._clear_recent_files)

    def _clear_recent_files(self):
        self._cfg["recent_files"] = []
        save_config(self._cfg)
        self._refresh_recent_menu()
        if self._reader is None:
            self._welcome.set_recent_files([])

    def _open_recent(self, path: str):
        """Abre un archivo de la lista de recientes; si falta, avisa y lo saca."""
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "Archivo no encontrado",
                f"No se pudo abrir:\n{path}\n\nSe eliminará de la lista de recientes.")
            remove_recent_file(self._cfg, path)
            save_config(self._cfg)
            self._refresh_recent_menu()
            if self._reader is None:
                self._welcome.set_recent_files(self._cfg.get("recent_files") or [])
            return
        self.open_file(path)

    # ── Estado vacío / título ────────────────────────────────────────────────

    def _set_empty_state(self, empty: bool):
        """Alterna bienvenida ↔ área principal y habilita lo que depende de
        un archivo abierto."""
        self._welcome.setVisible(empty)
        self._main_area.setVisible(not empty)
        self._bar_file_area.setVisible(not empty)
        for act in (self._act_export_png, self._act_export_csv, self._act_export_wafs,
                    self._act_close, self._act_full, self._act_update, self._act_layer):
            act.setEnabled(not empty)
        if empty:
            self._welcome.set_recent_files(self._cfg.get("recent_files") or [])

    def _update_title(self):
        if self._path:
            self.setWindowTitle(f"{os.path.basename(self._path)}  —  {APP_TITLE}")
        else:
            self.setWindowTitle(APP_TITLE)
        self.setWindowFilePath(self._path or "")

    def set_status(self, text: str):
        self._statusbar.showMessage(text)

    # ── Archivo ──────────────────────────────────────────────────────────────

    def _file_open(self):
        start_dir = working_dir(self._cfg)
        path, _ = QFileDialog.getOpenFileName(self, "Abrir archivo GRIB2", start_dir,
                                              GRIB_FILTER)
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        """Abre un GRIB2 (también desde el Finder o la línea de comandos). Si
        no está en formato WAFS se convierte antes de mostrarlo."""
        from .grib_reader import GribReader, EngineUnavailable, ec
        engine = self._cfg.get("engine", "eccodes")
        self.set_status(f"Leyendo {os.path.basename(path)} ({engine}) …")
        QApplication.processEvents()
        try:
            try:
                reader = GribReader(path, engine=engine,
                                    wgrib2_path=self._cfg.get("wgrib2_path", ""))
            except EngineUnavailable as exc:
                if engine == "wgrib2" and ec is not None:
                    # El motor elegido no está: se avisa y se sigue con ecCodes
                    QMessageBox.warning(self, "wgrib2 no disponible",
                                        f"{exc}\nSe abre el archivo con ecCodes.")
                    reader = GribReader(path, engine="eccodes")
                else:
                    QMessageBox.critical(self, "Motor de lectura no disponible", str(exc))
                    self.set_status("Motor de lectura no disponible.")
                    return
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error al abrir el archivo",
                                 f"No se pudo leer el archivo:\n{path}\n\n{exc}")
            self.set_status("Error al abrir el archivo.")
            return
        if not self._accept_reader(reader):
            return
        reader, path, converted = self._ensure_wafs(reader, path)
        self.load_reader(reader, path, read_provenance(path))
        if converted:
            self.set_status(f"Convertido a WAFS: {path}")
        push_recent_file(self._cfg, path)
        save_config(self._cfg)
        self._refresh_recent_menu()
        self.set_status(f"Archivo cargado: {path}")

    def _ensure_wafs(self, reader, path: str):
        """El visor lee sólo WAFS: un archivo local en niveles de presión se
        convierte (junto al original, o en la caché si la carpeta no se
        puede escribir) y se abre el convertido. Devuelve (reader, path,
        convertido)."""
        from . import wafs_format as wf
        from .grib_reader import GribReader, ec
        if (not self._cfg.get("wafs_convert_local", True) or ec is None
                or getattr(reader, "kind", "altura") != "altura" or getattr(reader, "is_wafs", False)):
            return reader, path, False
        self.set_status(f"Convirtiendo {os.path.basename(path)} al formato WAFS…")
        QApplication.processEvents()
        dst = wf.converted_path_for(path)
        try:
            try:
                _dst, info = wf.convert_file(path, dst, provenance=read_provenance(path) or {},
                                             **(wf.options_from_config(self._cfg) or {}))
            except PermissionError:
                from .sources.cache import default_cache_dir
                folder = os.path.join(default_cache_dir(), "..", "wafs")
                os.makedirs(folder, exist_ok=True)
                dst = os.path.join(folder, os.path.basename(dst))
                _dst, info = wf.convert_file(path, dst, provenance=read_provenance(path) or {},
                                             **(wf.options_from_config(self._cfg) or {}))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "Conversión a WAFS",
                                f"No se pudo convertir el archivo al formato WAFS; se abre tal "
                                f"cual.\n{exc}")
            return reader, path, False
        if not info.get("convertido"):
            return reader, path, False
        try:
            new_reader = GribReader(dst, engine=reader.engine,
                                    wgrib2_path=self._cfg.get("wgrib2_path", ""))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "Conversión a WAFS",
                                f"El archivo convertido no se pudo releer; se abre el original.\n{exc}")
            return reader, path, False
        return new_reader, dst, True

    def get_data(self):
        """Diálogo «Obtener datos…» para la fuente elegida. Si el usuario lo
        pide, el archivo bajado se abre directamente en el visor."""
        from .dialogs.download_dialog import DownloadDialog
        region = None
        if self._reader is not None:
            r = self._reader
            region = (float(r.lats.max()), float(r.lats.min()),
                      float(r.lons.min()), float(r.lons.max()))
        dlg = DownloadDialog(self, cfg=self._cfg, dest_dir=working_dir(self._cfg), region=None,
                             source_key=self.cb_source.currentData(),
                             regions_fn=lambda: self._fir_regions)
        if region is not None:
            dlg.enable_domain_button(region)
        ok = dlg.exec()
        # El diálogo deja en la configuración el último modo y las casillas
        # del bloque Área (también si se cerró sin bajar)
        save_config(self._cfg)
        self._apply_area_layer()
        if ok and dlg.downloaded_paths:
            first = dlg.downloaded_paths[0]
            self._cfg["last_directory"] = os.path.dirname(first)
            if dlg.source is not None:
                self._cfg["source"] = dlg.source.key
                self._refresh_sources_combo()
            save_config(self._cfg)
            if dlg.open_after:
                self.open_file(first)
            else:
                self.set_status("Descargado: " + ", ".join(dlg.downloaded_paths))

    download_gfs = get_data     # nombre anterior

    def _accept_reader(self, reader) -> bool:
        """Valida el contenido: sin U/V se puede seguir sólo con temperatura;
        sin nada útil no se abre."""
        if "u" in reader.variables and "v" in reader.variables:
            if getattr(reader, "kind", "altura") == "superficie":
                self.set_status("Archivo de superficie: viento a 10 m y temperatura a 2 m.")
            return True
        if "t" in reader.variables:
            QMessageBox.warning(
                self, "Sin viento",
                "El archivo no contiene componentes U/V del viento en niveles de "
                "presión. Sólo se podrá mostrar temperatura.")
            self.panel.set_mode("temperatura")
            return True
        QMessageBox.critical(
            self, "Sin datos de viento",
            "El archivo no contiene componentes U/V (UGRD/VGRD) ni temperatura "
            "en niveles de presión.")
        self.set_status("Archivo sin U/V.")
        return False

    def load_reader(self, reader, path: str, provenance: dict = None):
        """Instala un lector ya construido (también lo usan los tests con un
        lector sintético) y dibuja el primer paso. `provenance` es el JSON
        que escribe la descarga junto al archivo (fuente, modelo, corrida)."""
        self._reader = reader
        self._path = path
        self._provenance = provenance
        self._current = None
        self._update_title()
        self._set_empty_state(False)
        self.inventory.set_text(reader.inventory_text())
        self.panel.populate(reader)
        self.plot.set_projection(self.panel.projection(), reader.lons, reader.lats)
        self.redraw(keep_extent=False)

    def _file_close(self):
        self._reader = None
        self._path = None
        self._provenance = None
        self._current = None
        self.inventory.set_text("Sin archivo abierto.")
        self.plot.draw_empty()
        self._update_title()
        self._set_empty_state(True)
        self.set_status("Archivo cerrado.")

    # ── Dibujo ───────────────────────────────────────────────────────────────

    def redraw(self, keep_extent: bool = True):
        """Recalcula los campos del paso/nivel seleccionados y redibuja."""
        r = self._reader
        if r is None:
            self.plot.draw_empty()
            return
        if not r.steps:
            return
        step_idx = max(0, min(self.panel.step_index(), len(r.steps) - 1))
        step = r.steps[step_idx]
        panel = self.panel

        try:
            if panel.level_mode == "sfc":
                u, v, t, info = r.get_surface_fields(step_idx)
            elif panel.level_mode == "p" and panel.sel_p is not None:
                u, v, t, info = r.get_level_fields(step_idx, panel.sel_p)
            elif hasattr(r, "fields_for_fl"):
                u, v, t, info = r.fields_for_fl(step_idx, panel.sel_fl)
            else:
                u, v, t, info = r.interp_to_pressure(step_idx, fl_to_hpa(panel.sel_fl))
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error de lectura",
                                 f"No se pudieron leer los campos:\n{exc}")
            return

        spd = direc = None
        if u is not None and v is not None:
            spd, direc = speed_dir_from_uv(u, v)
        self._current = {"u": u, "v": v, "t": t, "spd": spd, "dir": direc,
                         "info": info, "step": step, "step_idx": step_idx}

        self._update_status_panel(step, step_idx, info, u, v, t)

        # Título del mapa
        run = r.run_time()
        if panel.level_mode == "sfc":
            lvl_txt = "Superficie (viento 10 m, T 2 m)"
        elif panel.level_mode == "p":
            lvl_txt = (f"{panel._fl_text(info['p'])} (nivel WAFS)" if panel.wafs
                       else f"{info['p']:g} hPa")
        elif info.get("mode") == "wafs":
            lvl_txt = f"F{panel.sel_fl:03d} ({info['p']:g} hPa, nivel WAFS)"
        else:
            lvl_txt = f"F{panel.sel_fl:03d} ({info['p']:.0f} hPa)"
            if info["extrapolated"]:
                lvl_txt += f" → nivel más cercano {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl_txt += f" interp. {info['bracket'][0]:g}/{info['bracket'][1]:g} hPa"
        mode = panel.mode()
        mode_txt = {"viento": "Viento", "temperatura": "Temperatura",
                    "ambos": "Viento + Temperatura"}[mode]
        title = f"Corrida {fmt_dt(run)}Z  {step.label()}  |  {lvl_txt}  |  {mode_txt}"

        keep_view = bool(keep_extent and self.plot.has_data)
        opts = dict(panel.options())
        opts.update({"mode": mode, "show_wind": self._layer_enabled,
                     "keep_view": keep_view, "extent": None, "title": title,
                     "label_size": self._cfg.get("map_label_size", 7),
                     "label_units": self._cfg.get("map_label_units", True)})
        try:
            self.plot.draw(r.lats, r.lons, u, v, t, opts)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error al dibujar",
                                 f"No se pudo dibujar el mapa:\n{exc}")
            return
        if not keep_view:
            # Vista nueva: reinicia el historial de zoom/pan de la toolbar
            self._toolbar.update()

    def _update_status_panel(self, step, step_idx, info, u, v, t):
        run = self._reader.run_time()
        run_txt = f"RUN:   {fmt_dt(run)} UTC" if run else "RUN: --"
        h = step.hours
        hs = f"+{h:g} h" if h is not None else step.step_range
        step_txt = f"STEP:  [{step_idx}] {hs}  (stepRange {step.step_range})"
        ws, we = step.window_start, step.window_end
        utc_txt = (f"VALIDITY [{fmt_dt(ws, False)}–{fmt_dt(we, False)}] UTC  "
                   f"{ws.strftime('%d/%m/%Y') if ws else ''}")
        if ws is not None and we is not None:
            ls = ws.astimezone()
            le = we.astimezone()
            tzname = ls.tzname() or "local"
            loc_txt = (f"LOCAL    [{fmt_dt(ls, False)}–{fmt_dt(le, False)}] {tzname}  "
                       f"{ls.strftime('%d/%m/%Y')}")
        else:
            loc_txt = "LOCAL    [--:-- – --:--]"

        panel = self.panel
        if panel.level_mode == "sfc":
            lvl = "LEVEL: superficie (viento 10 m / T 2 m)"
        elif panel.level_mode == "p":
            lvl = (f"LEVEL: {panel._fl_text(info['p'])} (WAFS, nivel exacto)" if panel.wafs
                   else f"LEVEL: {info['p']:g} hPa (nivel del archivo)")
        elif info.get("mode") == "wafs":
            lvl = f"LEVEL: F{panel.sel_fl:03d} = {info['p'] * 100:.0f} Pa (WAFS, nivel exacto)"
        else:
            lvl = f"LEVEL: F{panel.sel_fl:03d} = {info['p']:.1f} hPa (ISA)"
            if info["extrapolated"]:
                lvl += f"\n  extrapolado / nivel más cercano: {info['nearest']:g} hPa"
            elif info["bracket"]:
                lvl += (f"\n  interpolado en ln(p) entre {info['bracket'][0]:g} y "
                        f"{info['bracket'][1]:g} hPa")
        missing = [n for n, f in (("U", u), ("V", v), ("T", t)) if f is None]
        if missing:
            lvl += f"\n  sin datos de: {', '.join(missing)}"
        if not self._layer_enabled:
            lvl += "\n  capa de datos DESHABILITADA"
        panel.set_status_texts(run_txt, step_txt, utc_txt, loc_txt, lvl,
                               source=self.source_text(step))

    def source_text(self, step=None) -> str:
        """Línea FUENTE del panel (dos renglones): fuente y modelo; corrida,
        plazo y resolución según la procedencia guardada por la descarga. Sin
        procedencia, archivo local."""
        prov = self._provenance
        fmt_line = self._format_line()
        if not prov:
            return "FUENTE: archivo local (sin procedencia)" + (f"\n{fmt_line}" if fmt_line else "")
        src = get_source(prov.get("fuente", ""))
        name = prov.get("nombre") or (src.name if src else prov.get("fuente", "?"))
        if src is not None and src.flight_levels:
            name += " ✓FL"
        model = (prov.get("modelo") or "").split(" vía ")[0].split(" (")[0]
        line1 = f"FUENTE: {name}" + (f"  ({model})" if model and model != name else "")
        run = prov.get("corrida") or ""
        if not run and self._reader is not None and self._reader.run_time() is not None:
            run = self._reader.run_time().strftime("%Y-%m-%dT%H:%MZ")
        try:
            run = f"{run[8:10]}/{run[5:7]} {run[11:13]}Z" if run else "?"   # 2026-10-14T06:00Z → 14/10 06Z
        except Exception:
            pass
        line2 = f"  corrida {run}"
        h = step.hours if step is not None else None
        if h is not None:
            line2 += f"  +{h:g} h"
        res = prov.get("resolucion_final")
        lines = [line1, line2]

        def deg(r):
            return f"{r.replace('p', ',')}°" if "p" in r and r[0].isdigit() else r
        if res:
            line2 += f"  ·  {deg(res)}"
        area = prov.get("area") or {}
        if area.get("etiqueta"):
            line2 += f"  ·  área {area['etiqueta']}"
            if area.get("cubre") is False:
                line2 += " (incompleta)"
        lines[1] = line2
        if prov.get("regrillado"):
            # Tercer renglón corto: el panel tiene ancho fijo y no ajusta texto
            src_res = prov.get("resolucion_descargada")
            if src_res:
                lines.append(f"  desde {deg(src_res)} ({prov['regrillado']})")
            else:
                lines.append(f"  regrillado: {prov['regrillado']}")
        elif prov.get("niveles"):
            lines.append(f"  niveles {prov['niveles']}")
        if fmt_line:
            lines.append(fmt_line)
        return "\n".join(lines)

    def _format_line(self) -> str:
        """Cuarto renglón de FUENTE: formato WAFS y rango de FL (y si se
        convirtió de niveles de presión)."""
        r = self._reader
        if r is None or not getattr(r, "is_wafs", False):
            return ""
        fls = sorted(r.fl_levels)
        txt = f"  WAFS FL{fls[0]:03d}–FL{fls[-1]:03d}"
        w = (self._provenance or {}).get("wafs") or {}
        if w.get("convertido"):
            txt += " (convertido)"
        return txt

    def set_projection(self, key: str):
        """Cambia la proyección del mapa (centrada en el dominio del archivo)
        y redibuja con la vista completa."""
        r = self._reader
        lons = r.lons if r is not None else None
        lats = r.lats if r is not None else None
        self.plot.set_projection(key, lons, lats)
        self._cfg["projection"] = key
        save_config(self._cfg)
        self._sync_view_menu()
        if r is not None:
            self.redraw(keep_extent=False)
        else:
            self.plot.draw_empty()

    def toggle_layer(self):
        """Disable / Enable: oculta la capa de datos y deja el mapa base."""
        self._layer_enabled = not self._layer_enabled
        self.panel.set_layer_enabled(self._layer_enabled)
        self._act_layer.setChecked(self._layer_enabled)
        self._act_layer.setText("Capa de datos activada" if self._layer_enabled
                                else "Capa de datos desactivada")
        self.redraw()

    def apply_extent(self, lon0: float, lon1: float, lat0: float, lat1: float):
        if self.plot.has_data:
            self.plot.set_extent([lon0, lon1, lat0, lat1])

    def full_extent(self):
        if self._reader is None:
            return
        r = self._reader
        self.plot.set_extent([float(r.lons.min()), float(r.lons.max()),
                              float(r.lats.min()), float(r.lats.max())])
        self._toolbar.update()

    def _on_draw(self, _event):
        """Tras cada dibujo (zoom/pan incluidos) refleja la extensión en los
        campos del recuadro."""
        if self.plot.has_data:
            ext = self.plot.get_extent()
            if ext:
                self.panel.set_extent_entries(ext)

    def _on_scroll(self, event):
        """Rueda del mouse: zoom alrededor del cursor (arriba acerca)."""
        if event.inaxes is not self.plot.ax or not self.plot.has_data:
            return
        factor = 0.8 if event.button == "up" else 1.25
        try:
            self._toolbar.push_current()      # para que Inicio/atrás funcionen
        except Exception:
            pass
        self.plot.zoom_at(event.xdata, event.ydata, factor)

    def _on_motion(self, event):
        """Lat/lon, valores y FIR bajo el cursor en la barra de estado."""
        if event.inaxes is not self.plot.ax or event.xdata is None or event.ydata is None:
            return
        lon, lat = self.plot.to_lonlat(float(event.xdata), float(event.ydata))
        if lon is None:
            return
        self.set_status(self.cursor_text(lon, lat) + self.fir_hover_text(event))

    # ── Límites de FIR ───────────────────────────────────────────────────────

    def _load_fir_layer(self, redraw=True):
        """(Re)carga los polígonos según la configuración (copia incluida,
        descargas y archivo propio) y los aplica al mapa."""
        self._fir_regions, self._fir_notes = firmod.load_layer(self._cfg)
        self._apply_fir_layer(redraw=redraw)

    def _fir_selection(self):
        """(códigos de Argentina, códigos vecinos) a dibujar según la configuración."""
        c = self._cfg
        active = set(c.get("fir_active") or [])
        if not c.get("fir_enabled", False):
            return [], []
        ar = [k for k in firmod.ARGENTINA_CODES if k in active]
        nb = [k for k in firmod.NEIGHBOR_CODES if k in active] if c.get("fir_neighbors", False) else []
        return ar, nb

    def _fir_style(self):
        c = self._cfg
        return {"color": c.get("fir_color"), "neighbor_color": c.get("fir_neighbor_color"),
                "line_width": c.get("fir_line_width"), "fill_alpha": c.get("fir_fill_alpha"),
                "label_size": c.get("fir_label_size")}

    def _apply_fir_layer(self, redraw=True):
        ar, nb = self._fir_selection()
        self.plot.set_fir(self._fir_regions, ar, nb, self._fir_style())
        self._sync_view_menu()
        if not redraw:
            return
        if self._reader is not None:
            self.redraw()
        else:
            self.plot.draw_empty()

    def set_fir_enabled(self, on: bool):
        """Vista ▸ FIR ▸ Límites de FIR (Ctrl+Shift+F) o la casilla del panel."""
        on = bool(on)
        if self._cfg.get("fir_enabled", False) != on:
            self._cfg["fir_enabled"] = on
            save_config(self._cfg)
        self._apply_fir_layer()

    def set_fir_neighbors(self, on: bool):
        on = bool(on)
        if self._cfg.get("fir_neighbors", False) != on:
            self._cfg["fir_neighbors"] = on
            save_config(self._cfg)
        self._apply_fir_layer()

    def _grid_bbox(self):
        """(lonmin, lonmax, latmin, latmax) de la grilla abierta o None."""
        r = self._reader
        if r is None:
            return None
        return (float(r.lons.min()), float(r.lons.max()), float(r.lats.min()), float(r.lats.max()))

    def open_fir_dialog(self, tab: int = 0):
        """Diálogo «Límites de FIR»: regiones y estilo, extremos y
        cobertura, fuentes de los límites. Al cerrarlo se recargan los
        archivos (pudo descargar o cargar uno propio)."""
        from .dialogs.fir_dialog import FirDialog
        dlg = FirDialog(self, cfg=self._cfg, regions=self._fir_regions, notes=self._fir_notes,
                        grid_bbox=self._grid_bbox())
        try:
            dlg.tabs.setCurrentIndex(int(tab))
        except Exception:
            pass
        if dlg.exec():
            self._cfg.update(dlg.values())
            save_config(self._cfg)
        self._load_fir_layer()

    def fir_hover_text(self, event) -> str:
        """Texto para la barra de estado: FIR que contiene el cursor y, si el
        cursor está sobre un contorno, las FIR que lo comparten."""
        try:
            inside, edges = self.plot.fir_hit(event)
        except Exception:
            return ""
        txt = ""
        if inside:
            txt += "   | FIR " + " / ".join(f"{r.name} ({r.code})" for r in inside)
        if edges:
            txt += "   | límite " + " · ".join(r.code for r in edges)
        return txt

    def fir_click_text(self, regions) -> str:
        """Extremos y cobertura de las FIR dadas (clic sobre el mapa)."""
        lines = []
        bbox = self._grid_bbox()
        for r in regions:
            e = r.extremes()
            if e is None:
                continue
            cov = firmod.coverage(r, bbox)
            cov_txt = {"completa": "la grilla cubre la FIR completa",
                       "parcial": "la grilla cubre la FIR parcialmente",
                       "ninguna": "la grilla no cubre la FIR",
                       "sin grilla": "sin archivo abierto"}.get(cov, cov)
            lines.append(f"FIR {r.name} ({r.code}): N {e['norte']:.2f}°  S {e['sur']:.2f}°  "
                         f"E {e['este']:.2f}°  O {e['oeste']:.2f}°  ·  {cov_txt}  ·  {r.source}")
        return "\n".join(lines)

    def _on_map_click(self, event):
        """Clic sin arrastre: nombre, extremos y cobertura de la FIR bajo el
        cursor en la barra de estado y en un tooltip junto al mouse."""
        try:
            inside, edges = self.plot.fir_hit(event)
        except Exception:
            return
        regions = list(inside) + [r for r in edges if r not in inside]
        if not regions:
            return
        text = self.fir_click_text(regions)
        if not text:
            return
        self.set_status(text.splitlines()[0])
        QToolTip.showText(QCursor.pos(), text.replace("\n", "<br>"), self.plot.canvas)

    # ── Área de descarga (rectángulos) ───────────────────────────────────────

    def area_layer_geometry(self):
        """(envolvente, [(código, región)]) según la última selección del
        bloque Área de «Obtener datos…», o (None, []) si no se dibuja."""
        c = self._cfg
        if not c.get("download_area_draw", False):
            return None, []
        mode = c.get("download_area_mode", "fir")
        if mode == "fir":
            table = areasmod.areas_from_config(c)
            codes = [k for k in (c.get("download_area_codes") or []) if areasmod.find_area(table, k)]
            chosen = [areasmod.find_area(table, k) for k in codes]
            env = areasmod.envelope(chosen, float(c.get("areas_margin_deg", areasmod.DEFAULT_MARGIN_DEG)))
            return env, [(a.code, a.region) for a in chosen]
        mr = c.get("download_manual_region")
        if mr and len(mr) == 4:
            return tuple(float(v) for v in mr), []
        return None, []

    def _apply_area_layer(self, redraw=True):
        env, boxes = self.area_layer_geometry()
        self.plot.set_download_area(env, boxes)
        self._sync_view_menu()
        if not redraw:
            return
        if self._reader is not None:
            self.redraw()
        else:
            self.plot.draw_empty()

    def set_area_draw(self, on: bool):
        """Vista ▸ FIR ▸ Rectángulos del área de descarga."""
        on = bool(on)
        if self._cfg.get("download_area_draw", False) != on:
            self._cfg["download_area_draw"] = on
            save_config(self._cfg)
        self._apply_area_layer()

    def open_areas_dialog(self):
        """Tabla de áreas (la misma que Preferencias ▸ Áreas / FIR)."""
        from .dialogs.areas_dialog import AreasDialog
        dlg = AreasDialog(self, cfg=self._cfg, regions_fn=lambda: self._fir_regions)
        if dlg.exec():
            self._cfg.update(dlg.values())
            save_config(self._cfg)
            self._apply_area_layer()

    def cursor_text(self, lon: float, lat: float) -> str:
        txt = f"Lat {lat:7.2f}   Lon {lon:8.2f}"
        cur = self._current
        if cur is not None and self._reader is not None:
            lons, lats = self._reader.lons, self._reader.lats
            i = int(np.argmin(np.abs(lons - lon)))
            j = int(np.argmin(np.abs(lats - lat)))
            dlon = float(abs(lons[1] - lons[0])) if len(lons) > 1 else 1.0
            dlat = float(abs(lats[1] - lats[0])) if len(lats) > 1 else 1.0
            if abs(lons[i] - lon) <= dlon and abs(lats[j] - lat) <= dlat:
                txt += f"   | punto ({lats[j]:.2f}, {lons[i]:.2f})"
                if cur["spd"] is not None:
                    s = cur["spd"][j, i]
                    d = cur["dir"][j, i]
                    if not np.isnan(s):
                        txt += f"   | Viento {s:5.1f} kt / {d:5.1f}°"
                    else:
                        txt += "   | Viento: sin dato"
                if cur["t"] is not None:
                    tv = cur["t"][j, i]
                    if not np.isnan(tv):
                        txt += f"   | T {tv - KELVIN:6.1f} °C"
        return txt

    # ── Exportar ─────────────────────────────────────────────────────────────

    def _default_name(self, ext: str) -> str:
        base = (os.path.splitext(os.path.basename(self._reader.path))[0]
                if self._reader else "grib")
        panel = self.panel
        lvl = {"fl": f"F{panel.sel_fl:03d}", "sfc": "superficie"}.get(
            panel.level_mode, f"{panel.sel_p}hPa")
        step_idx = self._current["step_idx"] if self._current else panel.step_index()
        return f"{base}_paso{step_idx}_{lvl}.{ext}"

    def _ask_save_path(self, title: str, ext: str, filt: str) -> str:
        default = os.path.join(working_dir(self._cfg), self._default_name(ext))
        path, _ = QFileDialog.getSaveFileName(self, title, default, filt)
        if path and not path.lower().endswith("." + ext):
            path += "." + ext
        if path:
            parent = os.path.dirname(path)
            if parent:
                self._cfg["last_directory"] = parent
                save_config(self._cfg)
        return path

    def export_png(self):
        if not self.plot.has_data:
            QMessageBox.information(self, "Exportar PNG", "No hay mapa para exportar.")
            return
        path = self._ask_save_path("Guardar PNG", "png", "PNG (*.png)")
        if not path:
            return
        try:
            self.write_png(path)
            self.set_status(f"PNG guardado: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Exportar PNG", f"No se pudo guardar:\n{exc}")

    def write_png(self, path: str):
        self.plot.save_png(path)

    def export_csv(self):
        if self._current is None or self._reader is None:
            QMessageBox.information(self, "Exportar CSV", "No hay datos cargados.")
            return
        path = self._ask_save_path("Guardar CSV", "csv", "CSV (*.csv)")
        if not path:
            return
        try:
            self.write_csv(path)
            self.set_status(f"CSV guardado: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Exportar CSV", f"No se pudo guardar:\n{exc}")

    def export_wafs(self):
        """«Exportar a WAFS…»: lo cargado (todos los plazos y niveles, o una
        selección) como GRIB2 WAFS con .idx y verificación."""
        if self._reader is None:
            QMessageBox.information(self, "Exportar a WAFS", "No hay datos cargados.")
            return
        if getattr(self._reader, "kind", "altura") != "altura":
            QMessageBox.information(self, "Exportar a WAFS",
                                    "El WAFS es un producto de altura: un archivo de superficie "
                                    "no se puede exportar en ese formato.")
            return
        from .dialogs.export_wafs_dialog import ExportWafsDialog
        region = None
        try:
            if self.plot.has_data:
                region = tuple(float(x) for x in self.plot.get_extent())
        except Exception:
            region = None
        dlg = ExportWafsDialog(self, reader=self._reader, cfg=self._cfg,
                               dest_dir=working_dir(self._cfg), region=region,
                               provenance=self._provenance)
        dlg.exec()
        if dlg.result:
            paths = dlg.result["archivos"]
            if paths:
                self._cfg["last_directory"] = os.path.dirname(paths[0])
                save_config(self._cfg)
            self.set_status("WAFS exportado: " + ", ".join(os.path.basename(p) for p in paths))

    def write_csv(self, path: str):
        """lat, lon, u, v, velocidad kt, dirección, T °C del nivel y paso actuales."""
        cur = self._current
        lats, lons = self._reader.lats, self._reader.lons

        def cell(arr, j, i):
            if arr is None:
                return ""
            val = arr[j, i]
            return "" if np.isnan(val) else f"{val:.3f}"

        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["# archivo", os.path.basename(self._reader.path)])
            w.writerow(["# paso", cur["step"].step_range, "validez_utc",
                        cur["step"].valid.isoformat() if cur["step"].valid else ""])
            w.writerow(["# nivel_hPa", f"{cur['info']['p']:.2f}", "modo",
                        {"fl": "FL interpolado", "sfc": "superficie"}.get(
                            self.panel.level_mode, "nivel exacto")])
            w.writerow(["lat", "lon", "u_ms", "v_ms", "velocidad_kt", "direccion_deg", "t_c"])
            tc = (cur["t"] - KELVIN) if cur["t"] is not None else None
            for j in range(len(lats)):
                for i in range(len(lons)):
                    w.writerow([f"{lats[j]:.3f}", f"{lons[i]:.3f}",
                                cell(cur["u"], j, i), cell(cur["v"], j, i),
                                cell(cur["spd"], j, i), cell(cur["dir"], j, i),
                                cell(tc, j, i)])

    # ── Preferencias ─────────────────────────────────────────────────────────

    def _open_settings(self):
        saved_color = self._cfg["accent_color"]
        saved_opacity = self._cfg.get("opacity", 180)
        dlg = SettingsDialog(self, cfg=self._cfg)
        dlg.theme_changed.connect(self._apply_theme)
        dlg.opacity_changed.connect(lambda v: self._apply_theme(opacity=v))
        if dlg.exec():
            self.apply_settings(dlg.values())
        else:
            self._apply_theme(saved_color, opacity=saved_opacity)

    def apply_settings(self, values: dict):
        """Aplica y guarda lo elegido en Preferencias: tema, proyección,
        valores de VIENTO y MAPA del panel, descarga y motor."""
        old_proj = self._cfg.get("projection", "platecarree")
        old_engine = (self._cfg.get("engine", "eccodes"), self._cfg.get("wgrib2_path", ""))
        self._cfg.update(values)
        self._apply_theme(values.get("accent_color"), opacity=values.get("opacity"))
        self.panel.set_options(self._map_options_from_cfg())
        self._sync_view_menu()
        self._refresh_sources_combo()
        self._apply_area_layer(redraw=False)
        if values.get("projection", old_proj) != old_proj:
            self.panel.set_projection(values["projection"])
            self.set_projection(values["projection"])     # redibuja y guarda
        elif self._reader is not None:
            self.redraw()
        save_config(self._cfg)
        new_engine = (self._cfg.get("engine", "eccodes"), self._cfg.get("wgrib2_path", ""))
        if new_engine != old_engine and self._path and os.path.exists(self._path):
            # El motor se usa al abrir: se reabre el archivo actual con el nuevo
            self.open_file(self._path)

    # ── Geometría ─────────────────────────────────────────────────────────────

    def _restore_geometry(self):
        """Geometría guardada, acotada a la pantalla disponible: si la
        ventana no entra se achica, y si queda fuera se centra."""
        x, y = self._cfg.get("window_x", 100), self._cfg.get("window_y", 100)
        w, h = self._cfg.get("window_w", 1600), self._cfg.get("window_h", 1000)
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(w, avail.width())
            h = min(h, avail.height())
            if (x + w > avail.right() + 1 or y + h > avail.bottom() + 1
                    or x < avail.left() or y < avail.top()):
                x = avail.left() + (avail.width() - w) // 2
                y = avail.top() + (avail.height() - h) // 2
        self.setGeometry(x, y, w, h)

    def closeEvent(self, event):
        g = self.geometry()
        self._cfg.update({"window_x": g.x(), "window_y": g.y(),
                          "window_w": g.width(), "window_h": g.height()})
        save_config(self._cfg)
        super().closeEvent(event)
