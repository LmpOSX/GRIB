# -*- coding: utf-8 -*-
"""Ventana principal del Visor GRIB (PyQt6).

Esqueleto tomado de la base gráfica: tema generado desde el color de acento,
zoom de fuente, menús, preferencias, bienvenida con recientes, geometría
persistida y un único atajo Escape.
"""
import os

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QApplication, QMessageBox, QMenuBar, QFileDialog, QStatusBar,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut, QAction

from .config import (
    load_config, save_config, FONT_SIZE_MIN, FONT_SIZE_MAX,
    push_recent_file, remove_recent_file, working_dir, RECENT_FILES_MAX,
)
from .theme import build_stylesheet
from .dialogs.settings_dialog import SettingsDialog
from .widgets.welcome_widget import WelcomeWidget

APP_TITLE = "Visor GRIB"
GRIB_FILTER = "GRIB (*.grib2 *.grb2 *.grib *.grb);;Todos los archivos (*)"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg = load_config()
        self._reader = None            # GribReader del archivo abierto
        self._path: str | None = None  # ruta del archivo abierto

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._apply_theme(self._cfg["accent_color"])
        self._build_ui()
        self._restore_geometry()
        self._register_shortcuts()
        self._set_empty_state(True)
        self._update_title()

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
        """Gancho para los widgets que no se estilizan por QSS (el mapa)."""

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
        """Único atajo Escape: lo redefine la ventana con mapa."""

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

        # Área principal (mapa + panel de controles); la llena la subclase
        # o la fase siguiente. Acá sólo se reserva el contenedor.
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
        """Contenido del área principal (mapa y panel). Se completa en la
        ventana con mapa; la base deja el contenedor vacío."""

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

        # Acciones que dependen de un archivo abierto (las agrega la fase del mapa)
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
        """Botones de la barra que requieren archivo abierto (fase del mapa)."""

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
            QMessageBox.critical(self, "Error al abrir el archivo",
                                 f"No se pudo leer el archivo:\n{path}\n\n{exc}")
            self.set_status("Error al abrir el archivo.")
            return
        if not self._accept_reader(reader):
            return
        self._reader = reader
        self._path = path
        push_recent_file(self._cfg, path)
        save_config(self._cfg)
        self._refresh_recent_menu()
        self._update_title()
        self._set_empty_state(False)
        self._on_file_opened()
        self.set_status(f"Archivo cargado: {path}")

    def _accept_reader(self, reader) -> bool:
        """Validaciones de contenido (sin U/V, etc.). Devuelve False si no se
        debe abrir. La ventana con mapa las implementa."""
        return True

    def _on_file_opened(self):
        """Gancho tras abrir un archivo (la ventana con mapa llena controles)."""

    def _file_close(self):
        self._reader = None
        self._path = None
        self._on_file_closed()
        self._update_title()
        self._set_empty_state(True)
        self.set_status("Archivo cerrado.")

    def _on_file_closed(self):
        """Gancho tras cerrar el archivo."""

    # ── Acciones del mapa (las implementa la ventana con mapa) ───────────────

    def export_png(self):
        """Exportar PNG: se implementa junto con el mapa."""

    def export_csv(self):
        """Exportar CSV: se implementa junto con el mapa."""

    def full_extent(self):
        """Todo el dominio: se implementa junto con el mapa."""

    def redraw(self):
        """Actualizar: se implementa junto con el mapa."""

    def toggle_layer(self):
        """Capa de datos activada/desactivada: se implementa junto con el mapa."""

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
