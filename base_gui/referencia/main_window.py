import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QListWidget, QListWidgetItem,
    QFrame, QApplication, QMessageBox, QMenu, QMenuBar, QFileDialog,
    QComboBox, QLineEdit, QTreeWidgetItem, QToolButton
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut, QAction
from PyQt6.QtGui import QFont

from .config import (
    load_config, save_config, FONT_SIZE_MIN, FONT_SIZE_MAX,
    push_recent_file, remove_recent_file, working_dir,
)
from .theme import build_stylesheet
from .models import Project
from . import database as db
from .dialogs.project_dialog import ProjectDialog
from .dialogs.currency_dialog import CurrencyManagerDialog
from .dialogs.settings_dialog import SettingsDialog
from .dialogs.version_dialog import VersionManagerDialog
from .dialogs.sheet_dialog import SheetDialog
from .dialogs.export_dialog import ExportDialog
from .widgets.budget_widget import BudgetTreeWidget, _PAIR_KEY_ROLE
from .widgets.sheet_tab_bar import SheetTabBar
from .widgets.welcome_widget import WelcomeWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._cfg = load_config()
        self._current_project: Project | None = None
        self._projects: list[Project] = []
        self._sheets: list[Project] = []
        self._active_project_id: int | None = None   # principal o sheet activo
        self._sheet_totals_cache: dict[int, float] = {}
        self._sheet_names_cache:  dict[int, str]   = {}
        self._xml_path: str | None = None  # last saved/opened XML path
        self._dirty: bool = False  # hay cambios sin guardar en XML
        # Deshacer / rehacer: fotos del estado vivo, una por cambio
        self._undo_stack: list = []
        self._redo_stack: list = []
        self._undo_baseline: str | None = None
        self._applying_snapshot = False
        self._UNDO_MAX = 50

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._apply_theme(self._cfg["accent_color"])
        self._build_ui()
        self._restore_geometry()
        self._register_shortcuts()

        db.init_db()
        self._load_projects()
        self._setup_shortcuts()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _apply_theme(self, accent: str = None, font_size: int = None,
                     opacity: int = None):
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
        # Reajustar anchos de columna al nuevo tamaño de fuente
        if hasattr(self, '_budget_widget'):
            self._budget_widget.update_column_widths()
            self._budget_widget.set_accent_color(self._cfg["accent_color"])
        if hasattr(self, '_sheet_tab_bar'):
            self._sheet_tab_bar.set_accent_color(self._cfg["accent_color"])

    def _register_shortcuts(self):
        for seq in ("Ctrl++", "Ctrl+=", "Alt++", "Alt+="):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_up)
        for seq in ("Ctrl+-", "Alt+-"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_down)
        for seq in ("Ctrl+0", "Alt+0"):
            QShortcut(QKeySequence(seq), self).activated.connect(self._font_size_reset)

    def _setup_shortcuts(self):
        """Configure keyboard shortcuts."""
        def sc(key, slot):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(slot)
            return s

        sc("Ctrl+Shift+N", self._budget_widget._add_section)
        sc("Ctrl+I", self._budget_widget._add_item)
        sc("Ctrl+P", self._on_add_sheet)
        sc("Ctrl+F", lambda: (self._search_edit.setFocus(),
                               self._search_edit.selectAll()))
        sc("Ctrl+Shift+C", self._budget_widget._col_vis_btn.showMenu)
        sc("Ctrl+Shift+V", self._manage_versions)
        sc("Ctrl+M", self._manage_currencies)
        sc("Escape", self._on_escape)

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

    # ── UI ────────────────────────────────────────────────────────────────────

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
        self._setup_help_menu()

        # ── Action bar (replaces sidebar) ────────────────────────────────────
        root_lay.addWidget(self._build_action_bar())

        # ── Content area ─────────────────────────────────────────────────────
        self._content = QWidget()
        self._content.setObjectName("ContentPanel")
        content_lay = QVBoxLayout(self._content)
        content_lay.setContentsMargins(8, 6, 8, 6)
        content_lay.setSpacing(0)

        # ── Main area (sheet tabs + budget tree) ──
        self._main_area = QWidget()
        main_lay = QVBoxLayout(self._main_area)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # Sheet tabs + total (same row, above tree)
        self._sheet_tab_bar = SheetTabBar()
        self._sheet_tab_bar.tab_changed.connect(self._on_sheet_tab_changed)
        self._sheet_tab_bar.add_clicked.connect(self._on_add_sheet)
        self._sheet_tab_bar.sheet_edit_requested.connect(self._on_edit_sheet)
        self._sheet_tab_bar.sheet_renamed.connect(self._on_sheet_renamed)
        self._sheet_tab_bar.sheets_reordered.connect(self._on_sheets_reordered)
        self._sheet_tab_bar.section_dropped_on_plus.connect(self._on_section_to_new_sheet)
        self._sheet_tab_bar.section_dropped_on_sheet.connect(self._on_section_to_sheet)
        self._sheet_tab_bar.sheet_delete_requested.connect(self._on_delete_sheet)
        self._sheet_tab_bar.sheet_duplicate_requested.connect(self._on_duplicate_sheet)

        self._budget_widget = BudgetTreeWidget()
        self._budget_widget.project_changed.connect(self._on_project_changed)
        self._budget_widget.refreshed.connect(self._track_undo)
        self._budget_widget.project_renamed.connect(self._on_project_renamed)

        # Embed total label inside the tab bar row
        self._sheet_tab_bar.layout().addWidget(self._budget_widget._total_label)

        main_lay.addWidget(self._sheet_tab_bar)
        main_lay.addWidget(self._budget_widget, 1)

        # ── Welcome / empty state ──
        self._welcome = WelcomeWidget()
        self._welcome.new_clicked.connect(self._file_new)
        self._welcome.open_clicked.connect(self._file_open)
        self._welcome.recent_clicked.connect(self._open_recent)

        content_lay.addWidget(self._main_area, 1)
        content_lay.addWidget(self._welcome, 1)

        root_lay.addWidget(self._content, 1)

    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("ActionBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        def _sep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setObjectName("ActionSep")
            s.setFixedHeight(22)
            return s

        # ── Project-related widgets (hidden in empty state) ──
        self._bar_project_area = QWidget()
        proj_lay = QHBoxLayout(self._bar_project_area)
        proj_lay.setContentsMargins(0, 0, 0, 0)
        proj_lay.setSpacing(4)

        # ── Propiedades ──
        proj_btn = QPushButton("Propiedades")
        proj_btn.setToolTip("Editar propiedades del proyecto")
        proj_btn.clicked.connect(self._edit_project)
        proj_lay.addWidget(proj_btn)

        # ── Version dropdown ──
        self._ver_menu_btn = QToolButton()
        self._ver_menu_btn.setObjectName("DropdownBtn")
        self._ver_menu_btn.setText("Versiones")
        self._ver_menu_btn.setToolTip("Guardar o cargar versiones (Ctrl+Shift+V)")
        self._ver_menu_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._ver_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._ver_menu_btn.setMinimumWidth(150)
        self._ver_menu = QMenu(self._ver_menu_btn)
        self._ver_menu_btn.setMenu(self._ver_menu)
        proj_lay.addWidget(self._ver_menu_btn)

        # ── Currency dropdown ──
        self._cur_menu_btn = QToolButton()
        self._cur_menu_btn.setObjectName("DropdownBtn")
        self._cur_menu_btn.setText("Agregar Moneda")
        self._cur_menu_btn.setToolTip("Moneda de cotización (Ctrl+M)")
        self._cur_menu_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._cur_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._cur_menu_btn.setMinimumWidth(140)
        self._cur_menu = QMenu(self._cur_menu_btn)
        self._cur_menu_btn.setMenu(self._cur_menu)
        proj_lay.addWidget(self._cur_menu_btn)

        proj_lay.addWidget(_sep())

        # ── Budget actions (from budget_widget toolbar) ──
        self._budget_action_placeholder = QWidget()
        self._budget_action_layout = QHBoxLayout(self._budget_action_placeholder)
        self._budget_action_layout.setContentsMargins(0, 0, 0, 0)
        self._budget_action_layout.setSpacing(4)
        proj_lay.addWidget(self._budget_action_placeholder)

        lay.addWidget(self._bar_project_area)

        lay.addStretch()

        # ── Search (also project-related) ──
        self._bar_search_area = QWidget()
        search_lay = QHBoxLayout(self._bar_search_area)
        search_lay.setContentsMargins(0, 0, 0, 0)
        search_lay.setSpacing(4)

        self._search_edit = QLineEdit()
        self._search_edit.setObjectName("SearchField")
        self._search_edit.setPlaceholderText("Buscar… (Ctrl+F)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setFixedWidth(220)
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_lay.addWidget(self._search_edit)
        search_lay.addWidget(_sep())

        lay.addWidget(self._bar_search_area)

        # ── Settings (always visible) ──
        settings_btn = QPushButton("⚙")
        settings_btn.setToolTip("Configuración")
        settings_btn.setFixedWidth(32)
        settings_btn.clicked.connect(self._open_settings)
        lay.addWidget(settings_btn)

        return bar

    def _setup_file_menu(self):
        def _add(menu, text, slot, shortcut=None):
            act = QAction(text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            menu.addAction(act)
            return act

        archivo = self._menubar.addMenu("Archivo")
        _add(archivo, "Nuevo", self._file_new, "Ctrl+N")
        _add(archivo, "Abrir...", self._file_open, "Ctrl+O")

        # Recent files submenu
        self._recent_menu = archivo.addMenu("Abrir reciente")
        self._refresh_recent_menu()

        archivo.addSeparator()
        self._act_save    = _add(archivo, "Guardar", self._file_save, "Ctrl+S")
        self._act_save_as = _add(archivo, "Guardar como...", self._file_save_as)
        archivo.addSeparator()
        self._act_close   = _add(archivo, "Cerrar", self._file_close, "Ctrl+W")
        archivo.addSeparator()
        self._act_export  = _add(archivo, "Exportar a Excel...", self._export_excel, "Ctrl+E")

        edicion = self._menubar.addMenu("Edición")
        self._act_undo = _add(edicion, "Deshacer", self._undo, "Ctrl+Z")
        self._act_redo = _add(edicion, "Rehacer", self._redo, "Ctrl+Shift+Z")
        self._update_undo_actions()

    def _setup_help_menu(self):
        ayuda = self._menubar.addMenu("Ayuda")
        keys_act = QAction("Atajos de teclado…", self)
        keys_act.setShortcut(QKeySequence("Ctrl+/"))
        keys_act.triggered.connect(self._show_shortcuts)
        ayuda.addAction(keys_act)
        ayuda.addSeparator()
        about_act = QAction("Acerca de Presupuestador Pro", self)
        about_act.triggered.connect(self._show_about)
        ayuda.addAction(about_act)

    def _show_shortcuts(self):
        from .dialogs.shortcuts_dialog import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def _show_about(self):
        from . import __version__
        from PyQt6.QtCore import QT_VERSION_STR
        import platform
        QMessageBox.about(
            self,
            "Acerca de Presupuestador Pro",
            f"<h3>Presupuestador Pro</h3>"
            f"<p><b>Versión {__version__}</b></p>"
            f"<p>Aplicación de presupuestación profesional con soporte"
            f" multi-moneda, versionado, columnas extra (tasas, márgenes,"
            f" sumatorias) y exportación a Excel.</p>"
            f"<p style='color:gray;font-size:11px'>"
            f"Qt {QT_VERSION_STR} · Python {platform.python_version()}<br>"
            f"© 2026 Presupuestador Pro</p>"
        )

    def _refresh_recent_menu(self):
        """Rebuild the 'Abrir reciente' submenu from cfg.recent_files."""
        if not hasattr(self, "_recent_menu"):
            return
        self._recent_menu.clear()
        import os
        from .config import RECENT_FILES_MAX
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
        if self._current_project is None:
            self._welcome.set_recent_files([])

    def _open_recent(self, path: str):
        """Open a file from the recent list. If it's missing, warn and drop."""
        import os
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "Archivo no encontrado",
                f"No se pudo abrir:\n{path}\n\nSe eliminará de la lista de recientes.")
            remove_recent_file(self._cfg, path)
            save_config(self._cfg)
            self._refresh_recent_menu()
            if self._current_project is None:
                self._welcome.set_recent_files(self._cfg.get("recent_files") or [])
            return
        if not self._check_unsaved_changes():
            return
        self.open_file(path)

    def _set_empty_state(self, empty: bool):
        """Toggle welcome widget vs main budget area, and enable/disable
        project-dependent chrome."""
        self._welcome.setVisible(empty)
        self._main_area.setVisible(not empty)
        self._bar_project_area.setVisible(not empty)
        self._bar_search_area.setVisible(not empty)
        # File menu: Save / Save as / Close / Export require an open project
        for act in (self._act_save, self._act_save_as,
                    self._act_close, self._act_export):
            act.setEnabled(not empty)
        if empty:
            self._welcome.set_recent_files(self._cfg.get("recent_files") or [])

    def _reparent_budget_buttons(self):
        """Move budget widget toolbar buttons into the action bar."""
        bw = self._budget_widget
        lay = self._budget_action_layout
        for w in (bw._add_section_btn, bw._add_item_btn,
                  bw._edit_btn, bw._del_btn):
            lay.addWidget(w)

        s = QFrame()
        s.setFrameShape(QFrame.Shape.VLine)
        s.setObjectName("ActionSep")
        s.setFixedHeight(22)
        lay.addWidget(s)

        for w in (bw._expand_rows_btn, bw._wrap_btn,
                  bw._col_extra_btn, bw._col_vis_btn):
            lay.addWidget(w)

    def _update_title(self):
        """Título de ventana: «proyecto — archivo.ppto», con la marca nativa
        de modificado ([*] → punto en el botón de cerrar en macOS) y el archivo
        asociado (ícono de documento y ruta con Cmd-clic en el título)."""
        import os
        if self._xml_path:
            file_name = os.path.basename(self._xml_path)
        else:
            file_name = "Sin título" if self._current_project else ""
        if self._current_project:
            self.setWindowTitle(f"{self._current_project.name}  —  {file_name}[*]")
        else:
            self.setWindowTitle("Presupuestador Pro")
        self.setWindowFilePath(self._xml_path or "")
        self.setWindowModified(bool(self._dirty and self._current_project))

    def _check_unsaved_changes(self) -> bool:
        """Si hay cambios sin guardar, pregunta al usuario. Retorna True si se puede continuar."""
        if not self._dirty:
            return True
        reply = QMessageBox.question(
            self, "Cambios sin guardar",
            "Hay cambios sin guardar. ¿Desea guardar antes de continuar?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Save:
            self._file_save()
            return not self._dirty  # True si se salvó exitosamente
        if reply == QMessageBox.StandardButton.Discard:
            return True
        return False  # Cancel

    # ── Projects ──────────────────────────────────────────────────────────────

    def _load_projects(self):
        self._projects = db.get_projects()
        # Auto-select the only project (or the last used one)
        last_id = self._cfg.get("last_project_id")
        found = None
        if last_id:
            found = next((p for p in self._projects if p.id == last_id), None)
        if not found and self._projects:
            found = self._projects[0]
        if found:
            self._on_project_selected(found)
        else:
            self._on_project_selected(None)

    def _on_project_selected(self, project):
        if project is None:
            self._current_project = None
            self._active_project_id = None
            self._sheets = []
            self._sheet_tab_bar.set_sheets([])
            self.setWindowTitle("Presupuestador Pro")
            self._reset_undo()
            if hasattr(self, '_budget_widget'):
                self._budget_widget.load_project(None)
            self._set_empty_state(True)
            return
        self._set_empty_state(False)
        self._current_project = project
        self._cfg["last_project_id"] = project.id
        save_config(self._cfg)
        self._update_title()
        self._refresh_base_currency_combo()
        self._refresh_version_menu()
        self._active_project_id = project.id
        self._load_sheets()
        self._rebuild_sheet_totals_cache()
        self._sheet_tab_bar.select_principal()
        self._budget_widget.set_root_project_id(project.id)
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        self._budget_widget.load_project(project)
        # Reparent budget buttons into action bar (first load only)
        if not self._budget_action_layout.count():
            self._reparent_budget_buttons()

    def _refresh_base_currency_combo(self):
        self._cur_menu.clear()
        if not self._current_project:
            self._cur_menu_btn.setText("Agregar Moneda")
            return
        currencies = db.get_currencies(self._current_project.id)
        if not currencies:
            self._cur_menu_btn.setText("Agregar Moneda")
            add_act = self._cur_menu.addAction("Agregar Moneda…")
            add_act.triggered.connect(self._manage_currencies)
            return
        # Show current base currency on button
        base = next((c for c in currencies
                     if c.id == self._current_project.base_currency_id), None)
        if base:
            self._cur_menu_btn.setText(f"{base.name} — {base.code}")
        else:
            self._cur_menu_btn.setText(f"{currencies[0].name} — {currencies[0].code}")
        # Populate menu with currencies
        for c in currencies:
            act = self._cur_menu.addAction(f"{c.name} — {c.code}")
            act.setData(c.id)
            act.triggered.connect(lambda checked, cid=c.id: self._on_base_currency_action(cid))
        self._cur_menu.addSeparator()
        add_act = self._cur_menu.addAction("Agregar Moneda…")
        add_act.triggered.connect(self._manage_currencies)

    def _on_base_currency_action(self, currency_id: int):
        if not self._current_project:
            return
        if currency_id == self._current_project.base_currency_id:
            return

        currencies = db.get_currencies(self._current_project.id)
        new_base = next((c for c in currencies if c.id == currency_id), None)
        if new_base is None:
            return

        pivot = new_base.exchange_rate
        if pivot == 0:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Tasa inválida",
                                "La tasa de la moneda seleccionada es 0.")
            return

        # Anclar ítems sin moneda explícita a la moneda base actual
        # para que se conviertan correctamente con las nuevas tasas
        old_base_id = self._current_project.base_currency_id
        if old_base_id is not None:
            db.assign_null_currency_items(self._current_project.id, old_base_id)

        # Recalcular todas las tasas relativas a la nueva base
        for cur in currencies:
            cur.exchange_rate = cur.exchange_rate / pivot
            db.save_currency(cur)

        self._current_project.base_currency_id = new_base.id
        self._current_project.base_currency_code = new_base.code
        self._cur_menu_btn.setText(f"{new_base.name} — {new_base.code}")
        db.save_project(self._current_project)
        db.sync_sheet_currencies(self._current_project.id)
        self._dirty = True
        self._update_title()
        self._load_sheets()
        self._rebuild_sheet_totals_cache()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        self._load_active_into_widget()

    # ── Proyecto vivo (D11) ──────────────────────────────────────────────────

    def _reload_current_project(self, quiet: bool = False):
        """Relee el presupuesto principal desde la base de sesión y lo devuelve.

        Si su id ya no existe, NO se reutiliza el objeto viejo (con él, la
        primera escritura de vista abortaba la app por clave foránea): se pasa
        al principal vigente de la base o, si no hay ninguno, al estado vacío,
        avisando al usuario.  Devuelve el Project vivo o None."""
        cur = self._current_project
        if cur is None:
            return None
        fresh = db.get_project(cur.id)
        if fresh is not None:
            self._current_project = fresh
            return fresh
        stale_id = cur.id
        self._projects = db.get_projects()
        if self._projects:
            self._reset_undo()
            self._on_project_selected(self._projects[0])
            msg = "Se muestra el presupuesto que sí está disponible."
        else:
            self._xml_path = None
            self._dirty = False
            self._on_project_selected(None)
            msg = "Se vació la ventana; abrí el archivo de nuevo."
        if not quiet:
            QMessageBox.warning(
                self, "Presupuesto no disponible",
                f"El presupuesto abierto (id {stale_id}) ya no está en la sesión.\n{msg}")
        return self._current_project

    def _ensure_current_alive(self) -> bool:
        """True si el presupuesto actual sigue existiendo (y quedó releído).
        False si hubo que recuperar otro estado: la acción que llama debe
        abortarse, porque ya no aplica a lo que el usuario veía."""
        before = self._current_project.id if self._current_project else None
        after = self._reload_current_project()
        return after is not None and after.id == before

    def _load_active_into_widget(self):
        """Carga en el árbol el proyecto/hoja activo, siempre releído de la base."""
        active = self._get_active_project()
        fresh = db.get_project(active.id) if active else None
        if active is not None and fresh is None:
            fresh = self._reload_current_project()
        self._budget_widget.load_project(fresh)

    def _refresh_version_menu(self):
        """Menú del botón Versiones: "Nueva…" (guardar foto), la lista de
        fotos (clic = cargar) y "Gestionar…"."""
        self._ver_menu.clear()
        if not self._current_project:
            return
        self._ver_menu.addAction("Nueva…", self._save_version)
        versions = db.get_versions(self._current_project.id)
        if versions:
            self._ver_menu.addSeparator()
        for v in versions:
            vlabel = v.name
            if v.version_number:
                vlabel += f" {v.version_number}"
            act = self._ver_menu.addAction(vlabel)
            act.setData(v.id)
            act.setToolTip(f"Cargar «{vlabel}» sobre el presupuesto actual")
            act.triggered.connect(lambda checked, ver=v: self._load_version(ver))
        self._ver_menu.addSeparator()
        self._ver_menu.addAction("Gestionar…", self._manage_versions)

    def _save_version(self):
        """Foto del estado actual con nombre y número (reemplaza si el número existe)."""
        if not self._current_project or not self._ensure_current_alive():
            return None
        from .dialogs.version_dialog import save_version_interactive
        v = save_version_interactive(self, self._current_project.id)
        if v:
            self._dirty = True
            self._update_title()
            self._refresh_version_menu()
        return v

    def _load_version(self, version) -> bool:
        """Copia la foto sobre el estado actual.  Antes pregunta si guardar el
        estado actual como versión; el estado previo queda en Deshacer."""
        if not self._current_project or not self._ensure_current_alive():
            return False
        label = f"{version.name} {version.version_number}".strip()
        box = QMessageBox(self)
        box.setWindowTitle("Cargar versión")
        box.setText(f"Cargar «{label}» reemplaza el presupuesto actual.")
        box.setInformativeText("¿Querés guardar el estado actual como una versión antes?")
        save_btn = box.addButton("Guardar y cargar", QMessageBox.ButtonRole.AcceptRole)
        load_btn = box.addButton("Cargar sin guardar", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            if not self._save_version():
                return False
        elif clicked is not load_btn:
            return False
        self._push_undo_point()
        self._apply_snapshot(version.snapshot_json)
        self._dirty = True
        self._update_title()
        return True

    def _apply_snapshot(self, snapshot_json: str):
        """Restaura una foto sobre el estado vivo y reconstruye la interfaz."""
        if not self._ensure_current_alive():
            return          # la foto era de un presupuesto que ya no existe
        self._applying_snapshot = True
        try:
            db.restore_snapshot(self._current_project.id, snapshot_json)
            refreshed = self._reload_current_project()
            if refreshed is None:
                return
            self._projects = db.get_projects()
            self._refresh_base_currency_combo()
            self._refresh_version_menu()
            self._load_sheets()
            self._rebuild_sheet_totals_cache()
            self._budget_widget.set_root_project_id(self._current_project.id)
            self._budget_widget.set_sheet_totals(
                self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
            self._active_project_id = self._current_project.id
            self._sheet_tab_bar.select_principal()
            self._budget_widget.load_project(refreshed)
        finally:
            self._applying_snapshot = False
        self._update_title()          # la foto trae el nombre del presupuesto
        self._undo_baseline = db.snapshot_project(self._current_project.id)
        self._update_undo_actions()

    # ── Deshacer / rehacer ────────────────────────────────────────────────────

    def _reset_undo(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._undo_baseline = None
        self._update_undo_actions()

    def _track_undo(self):
        """Tras cada reconstrucción del árbol: si el presupuesto cambió respecto
        de la última foto, la foto anterior pasa a la pila de deshacer."""
        if self._applying_snapshot or not self._current_project:
            return
        if not db.project_exists(self._current_project.id):
            return      # proyecto muerto: la foto saldría vacía (D11)
        snap = db.snapshot_project(self._current_project.id)
        if self._undo_baseline is None:
            self._undo_baseline = snap
            return
        if snap != self._undo_baseline:
            self._undo_stack.append(self._undo_baseline)
            del self._undo_stack[:-self._UNDO_MAX]
            self._redo_stack.clear()
            self._undo_baseline = snap
        self._update_undo_actions()

    def _push_undo_point(self):
        """Guarda el estado actual en Deshacer (antes de cargar una versión)."""
        if not self._current_project:
            return
        snap = db.snapshot_project(self._current_project.id)
        self._undo_stack.append(snap)
        del self._undo_stack[:-self._UNDO_MAX]
        self._redo_stack.clear()
        self._undo_baseline = snap

    def _undo(self):
        if not self._current_project or not self._ensure_current_alive():
            return
        if not self._undo_stack:
            return
        current = self._undo_baseline or db.snapshot_project(self._current_project.id)
        target = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._apply_snapshot(target)
        self._dirty = True
        self._update_title()

    def _redo(self):
        if not self._current_project or not self._ensure_current_alive():
            return
        if not self._redo_stack:
            return
        current = self._undo_baseline or db.snapshot_project(self._current_project.id)
        target = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._apply_snapshot(target)
        self._dirty = True
        self._update_title()

    def _update_undo_actions(self):
        if hasattr(self, "_act_undo"):
            self._act_undo.setEnabled(bool(self._undo_stack))
            self._act_redo.setEnabled(bool(self._redo_stack))

    def _new_project(self):
        if not self._check_unsaved_changes():
            return
        dlg = ProjectDialog(self)
        if dlg.exec():
            # Limpiar proyecto anterior
            if self._current_project:
                db.delete_project(self._current_project.id)
            p = db.save_project(dlg.project)
            self._xml_path = None
            self._dirty = True
            self._projects = db.get_projects()
            found = next((pr for pr in self._projects if pr.id == p.id), None)
            if found:
                self._on_project_selected(found)

    def _edit_project(self):
        if not self._current_project:
            return
        dlg = ProjectDialog(self, project=self._current_project)
        if dlg.exec():
            db.save_project(self._current_project)
            self._dirty = True
            self._update_title()
            self._projects = db.get_projects()
            self._budget_widget.refresh()

    def _delete_project(self):
        if not self._current_project:
            return
        reply = QMessageBox.question(
            self, "Eliminar proyecto",
            f"¿Eliminar '{self._current_project.name}' y todos sus datos?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            db.delete_project(self._current_project.id)
            self._current_project = None
            self._active_project_id = None
            self._sheets = []
            self._sheet_totals_cache = {}
            self._sheet_names_cache  = {}
            self._dirty = True
            self._update_title()
            self._projects = db.get_projects()
            self._load_projects()

    # ── Currencies ────────────────────────────────────────────────────────────

    def _manage_currencies(self):
        if not self._current_project or not self._ensure_current_alive():
            return
        dlg = CurrencyManagerDialog(self, project=self._current_project)
        if dlg.exec():
            self._dirty = True
            self._update_title()
        if self._reload_current_project() is None:
            return
        db.sync_sheet_currencies(self._current_project.id)
        self._projects = db.get_projects()
        self._load_sheets()
        self._rebuild_sheet_totals_cache()
        self._refresh_base_currency_combo()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        self._load_active_into_widget()

    # ── Versions ──────────────────────────────────────────────────────────────

    def _manage_versions(self, export_mode: bool = False):
        if not self._current_project or not self._ensure_current_alive():
            return
        dlg = VersionManagerDialog(self, project_id=self._current_project.id,
                                   export_mode=export_mode)
        result = dlg.exec()
        if dlg.versions_changed:
            self._dirty = True
            self._update_title()
        self._refresh_version_menu()
        if result and dlg.export_version:
            self._export_snapshot(dlg.export_version)
        elif result and dlg.selected_version:
            self._load_version(dlg.selected_version)

    def _get_active_project(self):
        """Devuelve el proyecto o sheet actualmente visible en el widget."""
        if not self._active_project_id:
            return self._current_project
        if self._current_project and self._active_project_id == self._current_project.id:
            return self._current_project
        sheet = next((s for s in self._sheets if s.id == self._active_project_id), None)
        if sheet is None or not db.project_exists(sheet.id):
            # La hoja activa ya no existe (p. ej. se recrearon al restaurar una
            # foto): volver al principal en vez de seguir con un id muerto
            self._active_project_id = self._current_project.id if self._current_project else None
            self._sheet_tab_bar.select_principal()
            return self._current_project
        return sheet

    # ── Sheets ────────────────────────────────────────────────────────────────

    def _load_sheets(self):
        if not self._current_project:
            self._sheets = []
        else:
            self._sheets = db.get_sheets(self._current_project.id)
        self._sheet_tab_bar.set_sheets(self._sheets)

    def _rebuild_sheet_totals_cache(self):
        self._sheet_totals_cache = {}
        self._sheet_names_cache  = {}
        for sh in self._sheets:
            self._sheet_totals_cache[sh.id] = db.get_sheet_total(sh.id)
            self._sheet_names_cache[sh.id]  = sh.name

    def _on_project_changed(self):
        """Called when columns or project data change — rebuild sheet totals."""
        self._dirty = True
        self._update_title()
        self._rebuild_sheet_totals_cache()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)

    def _on_sheet_tab_changed(self, sheet_id: int):
        self._clear_search()
        if sheet_id == -1:
            self._active_project_id = self._current_project.id if self._current_project else None
            self._rebuild_sheet_totals_cache()
            self._budget_widget.set_sheet_totals(
                self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
            self._budget_widget.load_project(self._reload_current_project())
        else:
            self._active_project_id = sheet_id
            sheet = next((s for s in self._sheets if s.id == sheet_id), None)
            if sheet:
                self._rebuild_sheet_totals_cache()
                self._budget_widget.set_sheet_totals(
                    self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
                self._budget_widget.load_project(sheet)

    def _on_add_sheet(self):
        if not self._current_project:
            return
        dlg = SheetDialog(self, parent_project_id=self._current_project.id)
        if dlg.exec():
            saved = db.save_sheet(dlg.sheet)
            self._dirty = True
            self._update_title()
            self._load_sheets()
            self._rebuild_sheet_totals_cache()
            self._budget_widget.set_sheet_totals(
                self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
            self._sheet_tab_bar.select_sheet(saved.id)
            self._active_project_id = saved.id
            refreshed = db.get_project(saved.id)
            self._budget_widget.load_project(refreshed or saved)

    def _on_section_to_new_sheet(self, section_id: int):
        """Sección soltada sobre "+": pasa a ser un Ítem Presupuestario (hoja
        nueva) y en su lugar queda un ítem vinculado a esa hoja."""
        if not self._current_project or not self._ensure_current_alive():
            return
        sec = db.get_section(section_id)
        if not sec:
            return
        reply = QMessageBox.question(
            self, "Convertir en Ítem Presupuestario",
            f"¿Convertir la sección «{sec.name}» en una hoja nueva?\n\n"
            "La sección y su contenido pasan a la hoja, y en su lugar queda un "
            "ítem vinculado al total de esa hoja (el total del presupuesto no cambia).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            self._budget_widget.refresh()
            return
        new_id = db.convert_section_to_sheet(section_id, self._current_project.id)
        if new_id is None:
            QMessageBox.warning(self, "Convertir", "No se pudo convertir la sección.")
            self._budget_widget.refresh()
            return
        self._after_section_moved(select_sheet_id=new_id)

    def _on_section_to_sheet(self, section_id: int, sheet_id: int):
        """Sección soltada sobre la pestaña de una hoja existente: se mueve
        allí (como sección raíz), sin dejar nada en el origen."""
        if not self._current_project or not self._ensure_current_alive():
            return
        sec = db.get_section(section_id)
        sheet = next((s for s in self._sheets if s.id == sheet_id), None)
        if not sec or not sheet:
            return
        if sec.project_id == sheet_id:
            self._budget_widget.refresh()
            return
        reply = QMessageBox.question(
            self, "Mover sección",
            f"¿Mover la sección «{sec.name}» y todo su contenido a la hoja «{sheet.name}»?\n\n"
            "Desaparece del presupuesto de origen (el total de origen baja).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if reply != QMessageBox.StandardButton.Yes:
            self._budget_widget.refresh()
            return
        if not db.move_section_to_project(section_id, sheet_id):
            QMessageBox.warning(self, "Mover sección", "No se pudo mover la sección.")
            self._budget_widget.refresh()
            return
        self._after_section_moved(select_sheet_id=sheet_id)

    def _after_section_moved(self, select_sheet_id: int):
        self._dirty = True
        self._update_title()
        self._load_sheets()
        self._rebuild_sheet_totals_cache()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        self._sheet_tab_bar.select_sheet(select_sheet_id)
        self._active_project_id = select_sheet_id
        self._load_active_into_widget()

    def _on_project_renamed(self, project_id: int, name: str):
        """Fila EDT 0 editada en el árbol: título, propiedades y pestaña."""
        if self._current_project and project_id == self._current_project.id:
            self._current_project.name = name
            self._dirty = True
            self._update_title()
        else:
            sheet = next((s for s in self._sheets if s.id == project_id), None)
            if sheet:
                sheet.name = name
                self._sheet_names_cache[project_id] = name
                self._sheet_tab_bar.rename_sheet_tab(project_id, name)
                self._budget_widget.set_sheet_totals(
                    self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
                self._dirty = True
                self._update_title()

    def _on_sheet_renamed(self, sheet_id: int, name: str):
        """Doble clic en la pestaña → nombre nuevo."""
        sheet = next((s for s in self._sheets if s.id == sheet_id), None)
        if not sheet or not name or name == sheet.name:
            return
        sheet.name = name
        db.save_sheet(sheet)
        self._dirty = True
        self._update_title()
        self._sheet_names_cache[sheet_id] = name
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        if self._active_project_id == sheet_id:
            self._budget_widget.load_project(db.get_project(sheet_id) or sheet)
        elif self._active_project_id == self._current_project.id:
            self._budget_widget.refresh()     # ítems vinculados muestran el nombre

    def _on_sheets_reordered(self, ids: list):
        """Arrastre de pestañas → posiciones nuevas."""
        if not self._current_project:
            return
        db.reorder_sheets(self._current_project.id, ids)
        order = {sid: i for i, sid in enumerate(ids)}
        self._sheets.sort(key=lambda s: order.get(s.id, 999))
        for s in self._sheets:
            s.position = order.get(s.id, s.position)
        self._dirty = True
        self._update_title()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)

    def _on_edit_sheet(self, sheet_id: int):
        sheet = next((s for s in self._sheets if s.id == sheet_id), None)
        if not sheet:
            return
        dlg = SheetDialog(self, sheet=sheet, parent_project_id=self._current_project.id)
        if dlg.exec():
            db.save_sheet(sheet)
            self._dirty = True
            self._update_title()
            self._load_sheets()
            self._rebuild_sheet_totals_cache()
            self._sheet_tab_bar.rename_sheet_tab(sheet_id, sheet.name)
            self._budget_widget.set_sheet_totals(
                self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
            if self._active_project_id == sheet_id:
                self._budget_widget.load_project(sheet)

    def _on_delete_sheet(self, sheet_id: int):
        sheet = next((s for s in self._sheets if s.id == sheet_id), None)
        if not sheet:
            return

        referencing = db.get_items_referencing_sheet(sheet_id)
        if referencing:
            n = len(referencing)
            msg = QMessageBox(self)
            msg.setWindowTitle("Eliminar Ítem Presupuestario")
            msg.setText(
                f"Existen {n} ítem{'s' if n != 1 else ''} cotizable{'s' if n != 1 else ''} "
                f"en otras hojas que utilizan «{sheet.name}»."
            )
            msg.setInformativeText("¿Qué desea hacer con esos ítems?")
            del_btn     = msg.addButton("Eliminar ítems", QMessageBox.ButtonRole.DestructiveRole)
            convert_btn = msg.addButton("Mantener como ítems normales",
                                        QMessageBox.ButtonRole.ActionRole)
            cancel_btn  = msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            msg.setDefaultButton(cancel_btn)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == cancel_btn or clicked is None:
                return
            if clicked == del_btn:
                db.delete_items_referencing_sheet(sheet_id)
            elif clicked == convert_btn:
                sheet_total   = db.get_sheet_total(sheet_id)
                base_cur_id   = (self._current_project.base_currency_id
                                 if self._current_project else None)
                db.detach_items_from_sheet(sheet_id, sheet_total, base_cur_id)
        else:
            reply = QMessageBox.question(
                self, "Eliminar Ítem Presupuestario",
                f"¿Eliminar «{sheet.name}» y todos sus datos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        db.delete_project(sheet_id)
        self._dirty = True
        self._update_title()
        if self._active_project_id == sheet_id:
            self._active_project_id = self._current_project.id
            self._sheet_tab_bar.select_principal()
        self._load_sheets()
        self._rebuild_sheet_totals_cache()
        self._budget_widget.set_sheet_totals(
            self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
        active = self._get_active_project()
        self._budget_widget.load_project(active)

    def _on_duplicate_sheet(self, sheet_id: int):
        new_id = db.duplicate_sheet(sheet_id)
        if new_id:
            self._dirty = True
            self._update_title()
            self._load_sheets()
            self._rebuild_sheet_totals_cache()
            self._budget_widget.set_sheet_totals(
                self._sheet_totals_cache, self._sheet_names_cache, self._sheets)
            self._sheet_tab_bar.select_sheet(new_id)
            self._active_project_id = new_id
            refreshed = db.get_project(new_id)
            self._budget_widget.load_project(refreshed)

    # ── Search ────────────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        """Filter tree items by search text in section/item names."""
        text = text.strip().lower()
        tree = self._budget_widget._tree
        extra_tree = self._budget_widget._extra_tree

        if not text:
            # Show all items
            self._set_all_visible(tree.invisibleRootItem(), True)
            self._sync_extra_tree_visibility(tree, extra_tree)
            return

        keywords = text.split()
        # First pass: mark matching items, then show ancestors
        self._set_all_visible(tree.invisibleRootItem(), False)
        self._show_matching(tree.invisibleRootItem(), keywords)
        self._sync_extra_tree_visibility(tree, extra_tree)

    def _search_highlight_brush(self):
        from PyQt6.QtGui import QColor, QBrush
        c = QColor(self._cfg.get("accent_color", "#4A90D9"))
        c.setAlpha(90)
        return QBrush(c)

    def _extra_row_of(self, child: QTreeWidgetItem):
        key = child.data(0, _PAIR_KEY_ROLE)
        pair = self._budget_widget._item_pairs.get(key) if key else None
        return pair[1] if pair else None

    def _show_matching(self, parent: QTreeWidgetItem, keywords: list) -> bool:
        """Recursively show items matching keywords (EDT, descripción y las
        columnas extra) and highlight the matching cells. Returns True if any
        child matches."""
        from PyQt6.QtGui import QBrush
        hl = self._search_highlight_brush()
        any_match = False
        for i in range(parent.childCount()):
            child = parent.child(i)
            cells = {(0, 0): (child.text(0) or "").lower(),
                     (0, 1): (child.text(1) or "").lower()}
            extra = self._extra_row_of(child)
            if extra is not None:
                for c in range(extra.columnCount()):
                    t = (extra.text(c) or "").lower()
                    if t:
                        cells[(1, c)] = t
            all_text = " ".join(cells.values())
            matches = all(kw in all_text for kw in keywords)

            child_has_match = self._show_matching(child, keywords)

            # Resaltar las celdas donde aparece alguna palabra
            child.setBackground(1, QBrush())
            if extra is not None:
                for c in range(extra.columnCount()):
                    extra.setBackground(c, QBrush())
            if matches:
                for (tree, c), t in cells.items():
                    if any(kw in t for kw in keywords):
                        (child if tree == 0 else extra).setBackground(c if tree else 1, hl)

            if matches or child_has_match:
                child.setHidden(False)
                child.setExpanded(True)
                any_match = True
        return any_match

    def _set_all_visible(self, parent: QTreeWidgetItem, visible: bool):
        from PyQt6.QtGui import QBrush
        for i in range(parent.childCount()):
            child = parent.child(i)
            child.setHidden(not visible)
            if visible:
                child.setExpanded(True)
                child.setBackground(1, QBrush())
                extra = self._extra_row_of(child)
                if extra is not None:
                    for c in range(extra.columnCount()):
                        extra.setBackground(c, QBrush())
            self._set_all_visible(child, visible)

    def _sync_extra_tree_visibility(self, tree, extra_tree):
        """Sync visibility of extra tree items with the main tree."""
        def sync_children(main_parent, extra_parent):
            for i in range(main_parent.childCount()):
                main_child = main_parent.child(i)
                if i < extra_parent.childCount():
                    extra_child = extra_parent.child(i)
                    extra_child.setHidden(main_child.isHidden())
                    extra_child.setExpanded(main_child.isExpanded())
                    sync_children(main_child, extra_child)

        sync_children(tree.invisibleRootItem(), extra_tree.invisibleRootItem())

    def _clear_search(self):
        if self._search_edit.text():
            self._search_edit.clear()

    def _on_escape(self):
        """Único atajo Escape: primero deselecciona columnas, si no, limpia la búsqueda."""
        bw = getattr(self, "_budget_widget", None)
        if bw is not None and bw.selected_columns():
            bw.clear_column_selection()
            return
        self._clear_search()

    # ── Export Excel ──────────────────────────────────────────────────────────

    def _export_excel(self):
        if not self._current_project:
            QMessageBox.information(self, "Exportar", "Seleccione un proyecto primero.")
            return
        from .dialogs.export_dialog import EXPORT_OPTIONS
        dlg = ExportDialog(self, project_name=self._current_project.name,
                           options={k: self._cfg.get(k, True) for k, _ in EXPORT_OPTIONS})
        if not dlg.exec() or not dlg.choice:
            return
        # Recordar las opciones de la planilla y usarlas en esta exportación
        if hasattr(dlg, "config_values"):
            self._cfg.update(dlg.config_values())
            save_config(self._cfg)
        self._export_options = dlg.options() if hasattr(dlg, "options") else {}
        if dlg.choice == 'choose':
            self._manage_versions(export_mode=True)     # "Exportar a Excel…" allí
            return
        self._export_snapshot(None)

    def _ask_excel_path(self, suffix: str) -> str:
        import os
        safe_name = "".join(c if c.isalnum() or c in " _-" else "_"
                            for c in self._current_project.name)
        default_filename = f"{safe_name}_{suffix}.xlsx".strip("_")
        default_path = os.path.join(working_dir(self._cfg), default_filename)
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", default_path, "Excel (*.xlsx);;Todos los archivos (*)")
        if path and not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        return path

    def _export_snapshot(self, version):
        """Exporta el estado actual (version=None) o una versión guardada."""
        output_path = self._ask_excel_path(
            "actual" if version is None else (version.version_number or version.name))
        if not output_path:
            return
        try:
            from .excel_exporter import export_snapshot, view_settings_for_export
            pids = [self._current_project.id] + [s.id for s in self._sheets]
            values = None
            if version is None:
                snap_json = db.snapshot_project(self._current_project.id)
                version_name = "Estado actual"
                # valores calculados para ajustar anchos (solo el estado actual)
                values = {pid: db.compute_project_values(pid, need_extra=True)[0] for pid in pids}
            else:
                snap_json = version.snapshot_json
                version_name = f"{version.name} {version.version_number}".strip()
            options = getattr(self, "_export_options", None)
            if options is None:
                from .dialogs.export_dialog import EXPORT_OPTIONS
                options = {k[len("export_"):]: self._cfg.get(k, True) for k, _ in EXPORT_OPTIONS}
            export_snapshot(
                snap_json,
                output_path,
                project_name=self._current_project.name,
                version_name=version_name,
                options=options,
                views=view_settings_for_export(pids),
                values=values,
            )
            QMessageBox.information(
                self, "Exportar",
                f"Archivo exportado correctamente:\n{output_path}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error al exportar", str(exc))

    # ── Archivo (XML) ────────────────────────────────────────────────────────

    def _file_new(self):
        """Nuevo presupuesto: cierra actual, crea vacío y abre diálogo de proyecto."""
        if not self._check_unsaved_changes():
            return
        if self._current_project:
            db.delete_project(self._current_project.id)
            self._current_project = None
            self._active_project_id = None
            self._sheets = []
            self._sheet_totals_cache = {}
            self._sheet_names_cache = {}
        self._xml_path = None
        self._dirty = False
        self._reset_undo()
        self._projects = db.get_projects()
        self._on_project_selected(None)
        self._sheet_tab_bar.set_sheets([])
        self._budget_widget.set_sheet_totals({}, {}, [])
        self._budget_widget.load_project(None)
        self._update_title()
        # Abrir diálogo de nuevo proyecto directamente
        dlg = ProjectDialog(self)
        if dlg.exec():
            p = db.save_project(dlg.project)
            self._dirty = True
            self._projects = db.get_projects()
            found = next((pr for pr in self._projects if pr.id == p.id), None)
            if found:
                self._on_project_selected(found)

    def _file_close(self):
        """Cierra el proyecto actual y vacía el programa."""
        if not self._check_unsaved_changes():
            return
        if self._current_project:
            db.delete_project(self._current_project.id)
        self._current_project = None
        self._active_project_id = None
        self._sheets = []
        self._sheet_totals_cache = {}
        self._sheet_names_cache = {}
        self._xml_path = None
        self._dirty = False
        self._projects = db.get_projects()
        self._update_title()
        self._sheet_tab_bar.set_sheets([])
        self._budget_widget.set_sheet_totals({}, {}, [])
        self._budget_widget.load_project(None)
        self._refresh_base_currency_combo()
        self._refresh_version_menu()
        self._reset_undo()
        self._clear_search()
        # Volver a la pantalla de bienvenida (igual que al iniciar la app sin
        # proyecto abierto).
        self._set_empty_state(True)

    def _file_open(self):
        if not self._check_unsaved_changes():
            return
        start_dir = working_dir(self._cfg)
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir proyecto", start_dir,
            "Presupuesto (*.ppto);;Archivos XML (*.xml);;Todos (*)")
        if not path:
            return
        self.open_file(path)

    def open_file(self, path: str):
        """Open a .ppto/.xml file — also used for Finder double-click."""
        try:
            from .xml_io import import_project_xml
            # Importar PRIMERO: si el archivo falla, el presupuesto actual
            # sigue vivo (antes se borraba antes de importar y quedaba un
            # objeto muerto en la ventana → D11)
            new_id = import_project_xml(path)
            old = self._current_project
            if old is not None and old.id != new_id:
                db.delete_project(old.id)
            self._projects = db.get_projects()
            found = next((p for p in self._projects if p.id == new_id), None)
            if found:
                self._reset_undo()
                self._on_project_selected(found)
            self._xml_path = path
            self._dirty = False
            self._update_title()
            # Register in recent files + working directory
            push_recent_file(self._cfg, path)
            save_config(self._cfg)
            self._refresh_recent_menu()
        except Exception as exc:
            from .xml_io import IncompatibleFileError
            title = ("Archivo de una versión más nueva"
                     if isinstance(exc, IncompatibleFileError) else "Error al abrir")
            QMessageBox.critical(self, title, str(exc))

    def _file_save(self):
        if not self._current_project:
            QMessageBox.information(self, "Guardar", "Seleccione un proyecto primero.")
            return
        if self._xml_path:
            self._save_xml(self._xml_path)
        else:
            self._file_save_as()

    def _file_save_as(self):
        if not self._current_project:
            QMessageBox.information(self, "Guardar", "Seleccione un proyecto primero.")
            return
        import os
        if self._xml_path:
            default_path = self._xml_path
        else:
            base = f"{self._current_project.name}.ppto"
            default_path = os.path.join(working_dir(self._cfg), base)
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar proyecto",
            default_path,
            "Presupuesto (*.ppto);;Archivos XML (*.xml)")
        if not path:
            return
        self._save_xml(path)

    def _save_xml(self, path: str):
        try:
            from .xml_io import export_project_xml
            export_project_xml(self._current_project.id, path)
            self._xml_path = path
            self._dirty = False
            self._update_title()
            # Register in recent files + working directory
            push_recent_file(self._cfg, path)
            save_config(self._cfg)
            self._refresh_recent_menu()
        except Exception as exc:
            QMessageBox.critical(self, "Error al guardar", str(exc))

    # ── Settings ──────────────────────────────────────────────────────────────

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

    # ── Geometry & resize grip ────────────────────────────────────────────────

    def _restore_geometry(self):
        self.setGeometry(
            self._cfg.get("window_x", 100),
            self._cfg.get("window_y", 100),
            self._cfg.get("window_w", 1400),
            self._cfg.get("window_h", 860),
        )

    def closeEvent(self, event):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Cambios sin guardar",
                "Hay cambios sin guardar. ¿Desea guardar antes de salir?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if reply == QMessageBox.StandardButton.Save:
                self._file_save()
                if self._dirty:
                    event.ignore()
                    return
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        g = self.geometry()
        self._cfg.update({"window_x": g.x(), "window_y": g.y(),
                           "window_w": g.width(), "window_h": g.height()})
        save_config(self._cfg)
        super().closeEvent(event)

