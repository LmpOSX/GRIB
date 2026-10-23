# -*- coding: utf-8 -*-
"""«Ver hexadecimal…»: el archivo abierto como un `hexdump -C` a la derecha y
su estructura en árbol a la izquierda (mensaje → sección → campo → subcampo).
Al elegir un nodo se pinta su tramo con el acento y cada hijo con un color
propio; un clic sobre un byte del volcado abre el árbol hasta el campo que
lo contiene. Los mensajes se desarrollan al abrirlos (los archivos grandes
tienen miles)."""
import bisect
import mmap
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLineEdit, QHeaderView, QAbstractItemView,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.hex_view import HexView
from .. import grib_hex as gh
from ..theme import hex_colors

_ROLE_NODE = Qt.ItemDataRole.UserRole


class HexViewerDialog(GlassDialog):
    def __init__(self, parent=None, path="", cfg=None, data=None):
        super().__init__(parent)
        self._cfg = cfg or {}
        self._path = path
        self._fh = None
        self._mm = None
        if data is not None:
            self._data = data
        else:
            self._data = self._open(path)
        self._messages = gh.scan_messages(self._data)
        self._starts = [o for o, _s in self._messages]
        self._nodes = {}            # id(item) → Node
        self._items = {}            # id(node) → item
        self._trees = {}            # índice de mensaje → Node raíz
        self.setWindowTitle(f"Hexadecimal — {os.path.basename(path) or 'datos'}")
        self.setMinimumSize(1400, 680)
        self._build_ui()
        self._apply_colors()
        self._fill_messages()

    def _open(self, path):
        self._fh = open(path, "rb")
        try:
            if os.path.getsize(path) == 0:
                return b""
            self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
            return self._mm
        except Exception:
            self._fh.seek(0)
            return self._fh.read()

    def closeEvent(self, event):
        super().closeEvent(event)
        self._release()

    def _release(self):
        self.hex.set_data(b"")
        self._data = b""
        try:
            if self._mm is not None:
                self._mm.close()
            if self._fh is not None:
                self._fh.close()
        except Exception:
            pass
        self._mm = self._fh = None

    # ── Interfaz ─────────────────────────────────────────────────────────

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
        head = QHBoxLayout()
        title = QLabel("Volcado hexadecimal")
        title.setObjectName("Heading")
        head.addWidget(title)
        head.addStretch()
        n = len(self._data)
        self.lbl_info = QLabel(f"{n:,} bytes · {len(self._messages)} mensajes".replace(",", "."))
        self.lbl_info.setObjectName("Hint")
        head.addWidget(self.lbl_info)
        lay.addLayout(head)

        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName("HexTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Campo", "Valor", "Posición"])
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setMinimumWidth(520)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.split.addWidget(self.tree)
        self.hex = HexView()
        self.hex.set_font_size(max(9, int(self._cfg.get("font_size", 13)) - 1))
        self.hex.byte_clicked.connect(self.select_byte)
        self.split.addWidget(self.hex)
        self.split.setStretchFactor(1, 0)
        self.split.setStretchFactor(0, 1)       # el volcado tiene ancho fijo; el árbol toma el resto
        lay.addWidget(self.split, 1)

        self.lbl_detail = QLabel("Elegí un mensaje, una sección o un campo; o hacé clic en un byte.")
        self.lbl_detail.setObjectName("HexDetail")
        self.lbl_detail.setWordWrap(True)
        self.lbl_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.lbl_detail)

        row = QHBoxLayout()
        row.addWidget(QLabel("Ir al byte"))
        self.ed_goto = QLineEdit()
        self.ed_goto.setPlaceholderText("decimal o 0x…")
        self.ed_goto.setMaximumWidth(140)
        self.ed_goto.returnPressed.connect(self._goto)
        row.addWidget(self.ed_goto)
        row.addStretch()
        self.btn_copy = QPushButton("Copiar bytes")
        self.btn_copy.setToolTip("Copia al portapapeles los bytes del tramo elegido, en hexadecimal")
        self.btn_copy.clicked.connect(self._copy)
        row.addWidget(self.btn_copy)
        b = QPushButton("Cerrar")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    def _apply_colors(self):
        self.hex.set_colors(hex_colors(self._cfg.get("accent_color", "#4a90d9")))

    def _fill_messages(self):
        self.tree.clear()
        self._nodes.clear()
        self._items.clear()
        self._trees.clear()
        total = len(self._messages)
        for i, (off, size) in enumerate(self._messages):
            it = QTreeWidgetItem([gh._msg_name(i, total), "", f"{off} +{size}"])
            it.setData(0, _ROLE_NODE, i)
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.tree.addTopLevelItem(it)
        self.hex.set_data(self._data, self._messages)
        if total:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    # ── Árbol ────────────────────────────────────────────────────────────

    def _ensure_parsed(self, i):
        """Desarrolla el mensaje `i` (una sola vez) y cuelga sus secciones."""
        if i in self._trees:
            return self._trees[i]
        off, _size = self._messages[i]
        try:
            root = gh.parse_message(self._data, off, i, len(self._messages))
        except Exception as exc:
            root = gh.Node(gh._msg_name(i, len(self._messages)), off, _size, None,
                           f"no se pudo desarrollar: {exc}", kind="message")
        self._trees[i] = root
        it = self.tree.topLevelItem(i)
        self._nodes[id(it)] = root
        self._items[id(root)] = it
        it.setText(1, root.text)
        it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        for c in root.children:
            self._add_item(it, c)
        return root

    def _add_item(self, parent_item, node):
        it = QTreeWidgetItem(parent_item, [node.name, node.text, f"{node.offset} +{node.size}"])
        self._nodes[id(it)] = node
        self._items[id(node)] = it
        for c in node.children:
            self._add_item(it, c)
        return it

    def _on_expanded(self, item):
        if item.parent() is None:
            self._ensure_parsed(item.data(0, _ROLE_NODE))

    def node_of(self, item):
        if item is None:
            return None
        if item.parent() is None:
            return self._ensure_parsed(item.data(0, _ROLE_NODE))
        return self._nodes.get(id(item))

    def _on_current_changed(self, item, _prev):
        node = self.node_of(item)
        if node is None:
            self.hex.clear_selection()
            return
        self.hex.set_selection(node.offset, node.size, [(c.offset, c.size) for c in node.children])
        self.hex.scroll_to(node.offset)
        path = " ▸ ".join(n.name for n in gh.path_of(node))
        raw = gh.hex_bytes(self._data, node.offset, node.size)
        txt = f"{path}   [{node.offset}, {node.size} byte{'s' if node.size != 1 else ''}]"
        if raw:
            txt += f"\n{raw}"
        if node.text and node.kind != "message":
            txt += f"   → {node.text}"
        self.lbl_detail.setText(txt)

    def current_node(self):
        return self.node_of(self.tree.currentItem())

    # ── Navegación ───────────────────────────────────────────────────────

    def select_byte(self, pos):
        """Abre el árbol hasta el nodo más profundo que contiene `pos`."""
        pos = int(pos)
        if not self._messages or pos < 0 or pos >= len(self._data):
            return
        i = bisect.bisect_right(self._starts, pos) - 1
        if i < 0:
            return
        off, size = self._messages[i]
        if pos >= off + size:
            return
        root = self._ensure_parsed(i)
        node = gh.find_at(root, pos) or root
        it = self._items.get(id(node))
        if it is None:
            return
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)

    def _goto(self):
        txt = self.ed_goto.text().strip().lower()
        try:
            pos = int(txt, 16) if txt.startswith("0x") else int(txt)
        except ValueError:
            return
        self.select_byte(pos)

    def _copy(self):
        sel = self.hex.selection()
        if not sel:
            return
        off, size = sel
        QGuiApplication.clipboard().setText(gh.hex_bytes(self._data, off, size, limit=size))
