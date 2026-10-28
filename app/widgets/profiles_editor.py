# -*- coding: utf-8 -*-
"""Editor de perfiles del bloque «Archivo a guardar» (ver app/profiles.py):
lista a la izquierda y, a la derecha, el nombre, el propio bloque
`SaveOptionsBox` como formulario (sin el combo de perfil), la grilla con
nombre y el modo de FL que el perfil arrastra, y si se muestra en los
diálogos. Agregar, duplicar, borrar (los de fábrica se ocultan), restaurar
de fábrica uno o todos. Lo usa la pestaña Perfiles de Preferencias."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QLineEdit, QListWidget,
    QListWidgetItem, QComboBox, QCheckBox,
)

from .. import areas as A
from .. import fl_table as flt
from .. import profiles as PR
from .save_options import SaveOptionsBox


class ProfilesEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, cfg=None, parent=None, grids=None):
        super().__init__(parent)
        self._cfg = cfg or {}
        self._profiles = PR.profiles_from_config(self._cfg)
        self._grids = list(grids) if grids is not None else A.grids_from_config(self._cfg)
        self._loading = False
        self._build()
        self._fill_list()
        if self.lst.count():
            self.lst.setCurrentRow(0)

    # ── Construcción ─────────────────────────────────────────────────────────

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.lst = QListWidget()
        self.lst.setMinimumWidth(190)
        self.lst.currentRowChanged.connect(self._on_row)
        left.addWidget(self.lst, 1)
        row = QGridLayout()
        row.setHorizontalSpacing(4)
        row.setVerticalSpacing(4)
        self.btn_add = QPushButton("Agregar")
        self.btn_add.clicked.connect(self.add_profile)
        self.btn_dup = QPushButton("Duplicar")
        self.btn_dup.clicked.connect(self.duplicate_profile)
        self.btn_del = QPushButton("Borrar")
        self.btn_del.setToolTip("Un perfil de fábrica no se borra: se oculta con «Visible»")
        self.btn_del.clicked.connect(self.delete_profile)
        self.btn_restore = QPushButton("Restaurar de fábrica")
        self.btn_restore.setToolTip("Vuelve a los valores iniciales de este perfil de fábrica")
        self.btn_restore.clicked.connect(self.restore_profile)
        self.btn_restore_all = QPushButton("Restaurar todos")
        self.btn_restore_all.setToolTip("Los de fábrica vuelven a sus valores; los propios se conservan")
        self.btn_restore_all.clicked.connect(self.restore_all)
        row.addWidget(self.btn_add, 0, 0)
        row.addWidget(self.btn_dup, 0, 1)
        row.addWidget(self.btn_del, 1, 0)
        row.addWidget(self.btn_restore, 1, 1)
        row.addWidget(self.btn_restore_all, 2, 0, 1, 2)
        left.addLayout(row)
        lay.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Nombre"), 0, 0)
        self.ed_name = QLineEdit()
        self.ed_name.textEdited.connect(self._on_form_changed)
        g.addWidget(self.ed_name, 0, 1)
        self.lbl_info = QLabel("")
        self.lbl_info.setObjectName("Hint")
        g.addWidget(self.lbl_info, 0, 2)
        self.chk_enabled = QCheckBox("Visible en los diálogos")
        self.chk_enabled.toggled.connect(self._on_form_changed)
        g.addWidget(self.chk_enabled, 0, 3)
        g.setColumnStretch(1, 1)
        right.addLayout(g)
        self.form = SaveOptionsBox(cfg=self._cfg, show_profile=False, profiles=self._profiles,
                                   grids=self._grids)
        self.form.changed.connect(self._on_form_changed)
        right.addWidget(self.form)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.addWidget(QLabel("Grilla con nombre"), 0, 0)
        self.cb_grid = QComboBox()
        self.cb_grid.setToolTip("Al elegir el perfil, Obtener datos, Generar y Exportar a WAFS pasan "
                                "a esta grilla (zona y resolución). Se editan en Áreas / FIR.")
        self.cb_grid.currentIndexChanged.connect(self._on_form_changed)
        g.addWidget(self.cb_grid, 0, 1)
        g.addWidget(QLabel("Modo de FL"), 0, 2)
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("Sin cambiar", None)
        for m in flt.MODES:
            self.cb_mode.addItem(flt.MODE_LABELS[m], m)
        self.cb_mode.setToolTip("Al elegir el perfil, los diálogos pasan a este modo de etiquetado "
                                "de los niveles (el FDP de INDRA lee los 14 FL del modo INDRA).")
        self.cb_mode.currentIndexChanged.connect(self._on_form_changed)
        g.addWidget(self.cb_mode, 0, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        right.addLayout(g)
        self.lbl_error = QLabel("")
        self.lbl_error.setObjectName("StatusWarn")
        self.lbl_error.setWordWrap(True)
        self.lbl_error.setVisible(False)
        right.addWidget(self.lbl_error)
        hint = QLabel("Al elegir el perfil en un diálogo se cargan estos valores, la grilla y el modo "
                      "de FL; cambiar cualquier valor después deja «Personalizado». «Como el origen» "
                      "no se edita: es el perfil sin cambios.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        right.addWidget(hint)
        right.addStretch()
        lay.addLayout(right, 1)
        self._fill_grid_combo()

    # ── Lista ────────────────────────────────────────────────────────────────

    def _item_text(self, p):
        txt = p.name or p.id
        if not p.enabled:
            txt += "  (oculto)"
        elif PR.is_modified(p):
            txt += "  *"
        return txt

    def _fill_list(self):
        cur = self.current_id()
        self.lst.blockSignals(True)
        try:
            self.lst.clear()
            for p in self._profiles:
                it = QListWidgetItem(self._item_text(p))
                it.setData(Qt.ItemDataRole.UserRole, p.id)
                it.setToolTip(("De fábrica" if p.builtin else "Propio") + (" · modificado" if PR.is_modified(p) else ""))
                self.lst.addItem(it)
            if cur is not None:
                for i in range(self.lst.count()):
                    if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == cur:
                        self.lst.setCurrentRow(i)
        finally:
            self.lst.blockSignals(False)

    def _fill_grid_combo(self):
        cur = self.cb_grid.currentData()
        self.cb_grid.blockSignals(True)
        try:
            self.cb_grid.clear()
            self.cb_grid.addItem("Sin grilla", None)
            for g in self._grids:
                n = g.size()
                txt = g.name + (f" ({g.res:g}°, {n[0]} × {n[1]})" if n else "") + ("" if g.enabled else " (oculta)")
                self.cb_grid.addItem(txt, g.id)
            self.cb_grid.setCurrentIndex(max(0, self.cb_grid.findData(cur)) if cur else 0)
        finally:
            self.cb_grid.blockSignals(False)

    def set_grids(self, grids):
        """Otra tabla de grillas (la pestaña Áreas / FIR cambió)."""
        self._grids = list(grids)
        self._fill_grid_combo()
        self.form.set_profiles(self._profiles, self._grids)

    def current_id(self):
        it = self.lst.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None

    def current(self):
        return PR.find_profile(self._profiles, self.current_id())

    def select(self, pid):
        for i in range(self.lst.count()):
            if self.lst.item(i).data(Qt.ItemDataRole.UserRole) == pid:
                self.lst.setCurrentRow(i)
                return True
        return False

    def _on_row(self, _i):
        p = self.current()
        self._loading = True
        try:
            self.ed_name.setText(p.name if p else "")
            self.chk_enabled.setChecked(bool(p and p.enabled))
            self.form.set_values(p.values if p else {})
            self.cb_grid.setCurrentIndex(max(0, self.cb_grid.findData(p.grid)) if p and p.grid else 0)
            self.cb_mode.setCurrentIndex(max(0, self.cb_mode.findData(p.fl_mode)) if p and p.fl_mode else 0)
            editable = p is not None and not p.is_default
            for w in (self.ed_name, self.form, self.cb_grid, self.cb_mode, self.chk_enabled):
                w.setEnabled(editable)
            self.btn_dup.setEnabled(p is not None)
            self.btn_del.setEnabled(p is not None and not p.builtin)
            self.btn_restore.setEnabled(p is not None and p.builtin and not p.is_default)
            self._refresh_info()
        finally:
            self._loading = False

    def _refresh_info(self):
        p = self.current()
        if p is None:
            self.lbl_info.setText("")
            return
        txt = "de fábrica" if p.builtin else "propio"
        if PR.is_modified(p):
            txt += " · modificado"
        self.lbl_info.setText(txt)

    # ── Formulario → perfil ─────────────────────────────────────────────────

    def _on_form_changed(self, *_a):
        if self._loading:
            return
        p = self.current()
        if p is None or p.is_default:
            return
        p.name = self.ed_name.text().strip()
        p.enabled = self.chk_enabled.isChecked()
        p.values = {k: v for k, v in self.form.values().items() if k in p.values or k in PR.ge.KEYS}
        p.values = {k: p.values[k] for k in PR.ge.KEYS}
        p.grid = self.cb_grid.currentData()
        p.fl_mode = self.cb_mode.currentData()
        it = self.lst.currentItem()
        if it is not None:
            it.setText(self._item_text(p))
        self._refresh_info()
        self._validate()
        self.changed.emit()

    # ── Botones ──────────────────────────────────────────────────────────────

    def add_profile(self, profile=None):
        p = profile or PR.Profile(PR.new_id(), "Nuevo perfil", self.form.values() if self.current() else {})
        self._profiles.append(p)
        self._fill_list()
        self.select(p.id)
        self.ed_name.setFocus()
        self.ed_name.selectAll()
        self._validate()
        self.changed.emit()
        return p

    def duplicate_profile(self):
        p = self.current()
        if p is None:
            return
        c = p.copy()
        c.id, c.builtin, c.enabled = PR.new_id(), False, True
        c.name = f"{p.name} (copia)"
        self.add_profile(c)

    def delete_profile(self):
        p = self.current()
        if p is None or p.builtin:
            return
        self._profiles = [x for x in self._profiles if x.id != p.id]
        self._fill_list()
        if self.lst.count() and self.lst.currentRow() < 0:
            self.lst.setCurrentRow(0)
        self._on_row(self.lst.currentRow())
        self._validate()
        self.changed.emit()

    def restore_profile(self):
        p = self.current()
        f = PR.factory_profile(p.id) if p is not None and p.builtin else None
        if f is None:
            return
        f.enabled = p.enabled
        self._profiles = [f if x.id == p.id else x for x in self._profiles]
        self._fill_list()
        self._on_row(self.lst.currentRow())
        self._validate()
        self.changed.emit()

    def restore_all(self):
        out = []
        for p in self._profiles:
            f = PR.factory_profile(p.id) if p.builtin else None
            if f is not None:
                f.enabled = p.enabled
            out.append(f or p)
        self._profiles = out
        self._fill_list()
        self._on_row(self.lst.currentRow())
        self._validate()
        self.changed.emit()

    # ── Valores ──────────────────────────────────────────────────────────────

    def profiles(self):
        return [p.copy() for p in self._profiles]

    def errors(self):
        errs, seen = [], set()
        for p in self._profiles:
            if not p.name:
                errs.append("Un perfil no tiene nombre.")
            key = p.name.strip().lower()
            if key and key in seen:
                errs.append(f"Nombre de perfil repetido: {p.name}.")
            seen.add(key)
            if p.grid and A.find_grid(self._grids, p.grid) is None:
                errs.append(f"{p.name}: la grilla «{p.grid}» no existe.")
        return errs

    def values(self):
        return {"profiles": PR.profiles_to_config(self._profiles)}

    def _validate(self):
        errs = self.errors()
        self.lbl_error.setText("\n".join(errs[:4]))
        self.lbl_error.setVisible(bool(errs))
        return not errs
