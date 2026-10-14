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
    QLabel,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QAction

from .config import (
    load_config, save_config, FONT_SIZE_MIN, FONT_SIZE_MAX,
    push_recent_file, remove_recent_file, working_dir, RECENT_FILES_MAX,
)
from .theme import build_stylesheet, generate_palette
from .grib_reader import KELVIN, fl_to_hpa, fmt_dt, speed_dir_from_uv
from .dialogs.settings_dialog import SettingsDialog
from .widgets.welcome_widget import WelcomeWidget
from .widgets.control_panel import ControlPanel
from .widgets.inventory_panel import InventoryPanel

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
        p = generate_palette(self._cfg["accent_color"])
        plot.set_palette(
            bg=p["bg_data"].name(), ax_bg=p["bg_data"].name(),
            text=p["text_bright"].name(), text_dim=p["text_dim"].name(),
            coast=p["text_bright"].name(), border=p["text_dim"].name(),
            grid=p["mid"].name(), grid_fine=p["bg2"].name(),
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
        """Único atajo Escape: sale del modo Zoom / Pan del mapa."""
        mode = self._toolbar_mode()
        if mode == "ZOOM":
            self._toolbar.zoom()
        elif mode == "PAN":
            self._toolbar.pan()
        self._sync_map_buttons()

    # ── Interfaz ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("MainContainer")
        self.setCentralWidget(central)

        root_lay = QVBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

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
        self.plot = WindPlot(map_frame)
        self.plot.canvas.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        map_lay.addWidget(self.plot.canvas, 1)
        # La toolbar de matplotlib implementa zoom/pan pero sus íconos negros
        # no se ven sobre fondo oscuro: queda oculta y se maneja con botones
        # propios en la barra de acciones.
        self._toolbar = NavigationToolbar2QT(self.plot.canvas, map_frame)
        self._toolbar.hide()
        self._main_lay.addWidget(map_frame, 1)

        # ── Panel derecho con scroll ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(PANEL_WIDTH)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side = QWidget()
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 4, 0)
        side_lay.setSpacing(8)
        self.panel = ControlPanel()
        side_lay.addWidget(self.panel)
        inv_frame = QFrame()
        inv_frame.setObjectName("GlassPanel")
        inv_lay = QVBoxLayout(inv_frame)
        inv_lay.setContentsMargins(12, 8, 12, 10)
        inv_title = QLabel("INVENTARIO")
        inv_title.setObjectName("PanelTitle")
        inv_lay.addWidget(inv_title)
        self.inventory = InventoryPanel()
        inv_lay.addWidget(self.inventory)
        side_lay.addWidget(inv_frame)
        scroll.setWidget(side)
        self._main_lay.addWidget(scroll)

        # ── Señales del panel: cualquier cambio redibuja solo ──
        self.panel.step_changed.connect(lambda _i: self.redraw())
        self.panel.level_changed.connect(self.redraw)
        self.panel.variable_changed.connect(lambda _m: self.redraw())
        self.panel.options_changed.connect(self.redraw)
        self.panel.update_clicked.connect(self.redraw)
        self.panel.layer_toggled.connect(self.toggle_layer)
        self.panel.extent_applied.connect(self.apply_extent)
        self.panel.full_extent_clicked.connect(self.full_extent)
        self.panel.extent_invalid.connect(
            lambda msg: QMessageBox.warning(self, "Recuadro", msg))

        # ── Eventos del canvas ──
        self.plot.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.plot.canvas.mpl_connect("draw_event", self._on_draw)

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ActionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        open_btn = QPushButton("Abrir GRIB…")
        open_btn.setToolTip("Abrir un archivo GRIB2 (Ctrl+O)")
        open_btn.clicked.connect(self._file_open)
        lay.addWidget(open_btn)

        # Acciones que dependen de un archivo abierto
        self._bar_file_area = QWidget()
        self._bar_file_lay = QHBoxLayout(self._bar_file_area)
        self._bar_file_lay.setContentsMargins(0, 0, 0, 0)
        self._bar_file_lay.setSpacing(4)
        self._bar_file_lay.addWidget(self._action_sep())
        self._build_file_actions(self._bar_file_lay)
        lay.addWidget(self._bar_file_area)

        lay.addStretch()

        settings_btn = QPushButton("⚙")
        settings_btn.setToolTip("Preferencias (Ctrl+,)")
        settings_btn.setFixedWidth(32)
        settings_btn.clicked.connect(self._open_settings)
        lay.addWidget(settings_btn)
        return bar

    @staticmethod
    def _action_sep() -> QFrame:
        s = QFrame()
        s.setFrameShape(QFrame.Shape.VLine)
        s.setObjectName("ActionSep")
        s.setFixedHeight(22)
        return s

    def _build_file_actions(self, lay: QHBoxLayout):
        """Botones del mapa en la barra de acciones (reemplazan la toolbar de
        matplotlib, que queda oculta)."""
        self._btn_home = QPushButton("Inicio")
        self._btn_home.setToolTip("Volver a la vista inicial del mapa")
        self._btn_home.clicked.connect(self._map_home)
        self._btn_zoom = QPushButton("Zoom")
        self._btn_zoom.setObjectName("MapBtn")
        self._btn_zoom.setCheckable(True)
        self._btn_zoom.setToolTip("Zoom: arrastrar un rectángulo sobre el mapa (Esc para salir)")
        self._btn_zoom.clicked.connect(self._map_zoom)
        self._btn_pan = QPushButton("Pan")
        self._btn_pan.setObjectName("MapBtn")
        self._btn_pan.setCheckable(True)
        self._btn_pan.setToolTip("Pan: arrastrar el mapa (Esc para salir)")
        self._btn_pan.clicked.connect(self._map_pan)
        self._btn_png = QPushButton("Guardar PNG")
        self._btn_png.setToolTip("Exportar la vista actual a PNG (Ctrl+E)")
        self._btn_png.clicked.connect(self.export_png)
        for b in (self._btn_home, self._btn_zoom, self._btn_pan):
            lay.addWidget(b)
        lay.addWidget(self._action_sep())
        lay.addWidget(self._btn_png)

    # ── Toolbar de matplotlib (oculta) ───────────────────────────────────────

    def _toolbar_mode(self) -> str:
        mode = getattr(self._toolbar, "mode", None)
        name = getattr(mode, "name", None)
        if name:
            return name
        text = str(mode or "")
        if "zoom" in text and "rect" in text:
            return "ZOOM"
        if "pan" in text:
            return "PAN"
        return "NONE"

    def _sync_map_buttons(self):
        mode = self._toolbar_mode()
        self._btn_zoom.setChecked(mode == "ZOOM")
        self._btn_pan.setChecked(mode == "PAN")

    def _map_home(self):
        self._toolbar.home()
        self._sync_map_buttons()

    def _map_zoom(self):
        self._toolbar.zoom()
        self._sync_map_buttons()

    def _map_pan(self):
        self._toolbar.pan()
        self._sync_map_buttons()

    # ── Menús ────────────────────────────────────────────────────────────────

    def _setup_file_menu(self):
        archivo = self._menubar.addMenu("Archivo")
        self._act_open = self._add_action(archivo, "Abrir GRIB…", self._file_open, "Ctrl+O")
        self._recent_menu = archivo.addMenu("Recientes")
        self._refresh_recent_menu()
        archivo.addSeparator()
        self._act_export_png = self._add_action(
            archivo, "Exportar PNG…", self.export_png, "Ctrl+E")
        self._act_export_csv = self._add_action(
            archivo, "Exportar CSV…", self.export_csv, "Ctrl+Shift+E")
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
        vista.addSeparator()
        act_prefs = self._add_action(vista, "Preferencias…", self._open_settings, "Ctrl+,")
        act_prefs.setMenuRole(QAction.MenuRole.PreferencesRole)

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
        for act in (self._act_export_png, self._act_export_csv, self._act_close,
                    self._act_full, self._act_update, self._act_layer):
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
        """Abre un GRIB2 (también desde el Finder o la línea de comandos)."""
        from .grib_reader import GribReader, ec, ECCODES_HELP
        if ec is None:
            QMessageBox.critical(self, "eccodes no disponible", ECCODES_HELP)
            return
        self.set_status(f"Leyendo {os.path.basename(path)} …")
        QApplication.processEvents()
        try:
            reader = GribReader(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error al abrir el archivo",
                                 f"No se pudo leer el archivo:\n{path}\n\n{exc}")
            self.set_status("Error al abrir el archivo.")
            return
        if not self._accept_reader(reader):
            return
        self.load_reader(reader, path)
        push_recent_file(self._cfg, path)
        save_config(self._cfg)
        self._refresh_recent_menu()
        self.set_status(f"Archivo cargado: {path}")

    def _accept_reader(self, reader) -> bool:
        """Valida el contenido: sin U/V se puede seguir sólo con temperatura;
        sin nada útil no se abre."""
        if "u" in reader.variables and "v" in reader.variables:
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

    def load_reader(self, reader, path: str):
        """Instala un lector ya construido (también lo usan los tests con un
        lector sintético) y dibuja el primer paso."""
        self._reader = reader
        self._path = path
        self._current = None
        self._update_title()
        self._set_empty_state(False)
        self.inventory.set_text(reader.inventory_text())
        self.panel.populate(reader)
        self.redraw(keep_extent=False)

    def _file_close(self):
        self._reader = None
        self._path = None
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
            if panel.level_mode == "p" and panel.sel_p is not None:
                u, v, t, info = r.get_level_fields(step_idx, panel.sel_p)
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
        if panel.level_mode == "p":
            lvl_txt = f"{info['p']:g} hPa"
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

        extent = self.plot.get_extent() if (keep_extent and self.plot.has_data) else None
        opts = dict(panel.options())
        opts.update({"mode": mode, "show_wind": self._layer_enabled,
                     "extent": extent, "title": title})
        try:
            self.plot.draw(r.lats, r.lons, u, v, t, opts)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Error al dibujar",
                                 f"No se pudo dibujar el mapa:\n{exc}")
            return
        if extent is None:
            # Vista nueva: reinicia el historial de zoom/pan de la toolbar
            self._toolbar.update()
            self._sync_map_buttons()

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
        if panel.level_mode == "p":
            lvl = f"LEVEL: {info['p']:g} hPa (nivel del archivo)"
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
        panel.set_status_texts(run_txt, step_txt, utc_txt, loc_txt, lvl)

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
        self._sync_map_buttons()

    def _on_draw(self, _event):
        """Tras cada dibujo (zoom/pan incluidos) refleja la extensión en los
        campos del recuadro."""
        if self.plot.has_data:
            ext = self.plot.get_extent()
            if ext:
                self.panel.set_extent_entries(ext)

    def _on_motion(self, event):
        """Lat/lon y valores bajo el cursor en la barra de estado."""
        if event.inaxes is not self.plot.ax or event.xdata is None or event.ydata is None:
            return
        self.set_status(self.cursor_text(float(event.xdata), float(event.ydata)))

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
        lvl = f"F{panel.sel_fl:03d}" if panel.level_mode == "fl" else f"{panel.sel_p:g}hPa"
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
                        "FL interpolado" if self.panel.level_mode == "fl" else "nivel exacto"])
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
        dlg = SettingsDialog(self, current_color=saved_color,
                             current_opacity=saved_opacity)
        dlg.theme_changed.connect(self._apply_theme)
        dlg.opacity_changed.connect(lambda v: self._apply_theme(opacity=v))
        if dlg.exec():
            self._apply_theme(dlg.selected_color(), opacity=dlg.selected_opacity())
            save_config(self._cfg)
        else:
            self._apply_theme(saved_color, opacity=saved_opacity)

    # ── Geometría ─────────────────────────────────────────────────────────────

    def _restore_geometry(self):
        self.setGeometry(
            self._cfg.get("window_x", 100),
            self._cfg.get("window_y", 100),
            self._cfg.get("window_w", 1400),
            self._cfg.get("window_h", 860),
        )

    def closeEvent(self, event):
        g = self.geometry()
        self._cfg.update({"window_x": g.x(), "window_y": g.y(),
                          "window_w": g.width(), "window_h": g.height()})
        save_config(self._cfg)
        super().closeEvent(event)
