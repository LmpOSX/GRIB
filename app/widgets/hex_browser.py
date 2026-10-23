# -*- coding: utf-8 -*-
"""Visor hexadecimal: el archivo abierto como un `hexdump -C` y su estructura
en árbol (mensaje → sección → campo → subcampo), el árbol a la izquierda y
el volcado a la derecha. Va como panel del mapa (botón `0x` de la barra de
acciones, Vista ▸ Panel hexadecimal, Ctrl+Shift+H): debajo del mapa si el
panel lateral está a la vista, a la izquierda del mapa si no.

Los valores de la sección 7 no forman un árbol pero se listan por demanda:
filas de la grilla y, dentro, una celda por valor con su tramo de bytes y
su valor decodificado (ver grib_hex.data_rows / row_cells). `goto_cell`
salta a la celda de un mensaje (el clic en el mapa lo usa).

Cada nivel del árbol tiene un color (el cuadrito junto al nombre); al elegir
un nodo se pinta en el volcado toda su ruta, cada tramo con el color de su
nivel y el elegido encima, con el marco del acento. Abrir o cerrar un nodo
con «+» / «−» no cambia lo pintado. Un clic sobre un byte del volcado abre
el árbol hasta el campo que lo contiene. Los mensajes se desarrollan al
abrirlos (los archivos grandes tienen miles). El archivo se mapea en memoria
y se suelta al cerrarlo o al cargar otro."""
import bisect
import mmap
import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QGuiApplication, QIcon, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QSplitter, QLineEdit, QHeaderView, QAbstractItemView,
)

from .hex_view import HexView
from .. import grib_hex as gh
from ..theme import hex_colors

_ROLE_NODE = Qt.ItemDataRole.UserRole
TREE_MIN_WIDTH = 440        # ancho del árbol cuando el panel va a la izquierda del mapa
TREE_FLOOR = 300            # mínimo del árbol: debajo del mapa cede antes que el volcado


class HexBrowser(QWidget):
    def __init__(self, parent=None, cfg=None):
        super().__init__(parent)
        self.setObjectName("HexBrowser")
        self._cfg = cfg if cfg is not None else {}
        self._path = ""
        self._fh = None
        self._mm = None
        self._data = b""
        self._messages = []
        self._starts = []
        self._nodes = {}            # id(item) → Node
        self._items = {}            # id(node) → item
        self._trees = {}            # índice de mensaje → Node raíz
        self._level_icons = []      # cuadrito del color de cada nivel, para el árbol
        self._values_provider = None    # offset de mensaje → vector de valores (ecCodes)
        self._build_ui()
        self.apply_theme()

    # ── Archivo ──────────────────────────────────────────────────────────

    def load(self, path="", data=None):
        """Carga `path` (mapeado en memoria) o `data` directamente; suelta lo
        anterior. Con ninguno de los dos, queda vacío."""
        self.clear()
        self._path = path or ""
        if data is not None:
            self._data = data
        elif path:
            self._data = self._open(path)
        self._messages = gh.scan_messages(self._data)
        self._starts = [o for o, _s in self._messages]
        self._by_offset = {o: i for i, (o, _s) in enumerate(self._messages)}
        self._fill_messages()

    def clear(self):
        """Vacía el visor y suelta el archivo."""
        self.hex.set_data(b"")
        self.tree.clear()
        self._nodes.clear()
        self._items.clear()
        self._trees.clear()
        self._messages = []
        self._starts = []
        self._by_offset = {}
        self._data = b""
        self._path = ""
        try:
            if self._mm is not None:
                self._mm.close()
            if self._fh is not None:
                self._fh.close()
        except Exception:
            pass
        self._mm = self._fh = None
        self.lbl_info.setText("")
        self.lbl_detail.setText("Sin archivo.")

    def path(self):
        return self._path

    def set_values_provider(self, fn):
        """`fn(offset_del_mensaje)` → vector de valores en el orden del
        archivo (o None): con él las celdas de un empaquetado en bloque
        (complejo, JPEG, PNG) muestran su valor."""
        self._values_provider = fn

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

    # ── Interfaz ─────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        title = QLabel("HEXADECIMAL")
        title.setObjectName("PanelTitle")
        head.addWidget(title)
        head.addStretch()
        self.lbl_info = QLabel("")
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
        self.tree.setIconSize(QSize(12, 12))
        self.tree.setMinimumWidth(TREE_FLOOR)
        self.tree.setMinimumHeight(60)
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.split.addWidget(self.tree)
        self.hex = HexView()
        self.hex.byte_clicked.connect(self.select_byte)
        self.split.addWidget(self.hex)
        self.split.setStretchFactor(0, 1)       # el árbol toma el ancho que sobra
        self.split.setStretchFactor(1, 0)
        self.split.setCollapsible(0, False)
        self.split.setCollapsible(1, False)
        lay.addWidget(self.split, 1)

        self.lbl_detail = QLabel("Sin archivo.")
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
        lay.addLayout(row)

    def apply_theme(self, cfg=None):
        """Colores del acento y tamaño de fuente del volcado; los cuadritos
        del árbol se rehacen con los colores nuevos."""
        if cfg is not None:
            self._cfg = cfg
        colors = hex_colors(self._cfg.get("accent_color", "#4a90d9"), self._cfg.get("opacity", 180))
        self.hex.set_colors(colors)
        self.hex.set_font_size(max(9, int(self._cfg.get("font_size", 13)) - 1))
        self._level_icons = [self._swatch(c) for c in colors["levels"]]
        for i in range(self.tree.topLevelItemCount()):
            self._recolor(self.tree.topLevelItem(i), 0)
        self.setMinimumWidth(TREE_FLOOR + self.hex.minimumSizeHint().width() + self.split.handleWidth())
        self.updateGeometry()
        self.fit_tree()

    def fit_tree(self):
        """El volcado con su ancho justo y el árbol con todo lo que sobra."""
        self.split.setSizes([10 ** 6, self.hex.sizeHint().width()])

    def preferred_width(self):
        """Ancho para que entren el árbol y el volcado (posición · 16 bytes ·
        ASCII) sin cortar."""
        return TREE_MIN_WIDTH + self.hex.sizeHint().width() + self.split.handleWidth()

    def sizeHint(self):
        return QSize(self.preferred_width(), 420)

    def _recolor(self, item, level):
        item.setIcon(0, self.level_icon(level))
        for k in range(item.childCount()):
            self._recolor(item.child(k), level + 1)

    @staticmethod
    def _swatch(color):
        """Cuadrito redondeado, opaco, con el color de un nivel."""
        pm = QPixmap(12, 12)
        pm.fill(Qt.GlobalColor.transparent)
        c = QColor(color)
        c.setAlpha(255)
        pt = QPainter(pm)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        pt.setPen(Qt.PenStyle.NoPen)
        pt.setBrush(c)
        pt.drawRoundedRect(1, 1, 10, 10, 2.5, 2.5)
        pt.end()
        return QIcon(pm)

    def level_icon(self, level):
        return self._level_icons[level % len(self._level_icons)] if self._level_icons else QIcon()

    def _fill_messages(self):
        total = len(self._messages)
        n = len(self._data)
        self.lbl_info.setText(f"{n:,} bytes · {total} mensajes".replace(",", "."))
        for i, (off, size) in enumerate(self._messages):
            it = QTreeWidgetItem([gh._msg_name(i, total), "", f"{off} +{size}"])
            it.setData(0, _ROLE_NODE, i)
            it.setIcon(0, self.level_icon(0))
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            self.tree.addTopLevelItem(it)
        self.hex.set_data(self._data, self._messages)
        if total:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        else:
            self.lbl_detail.setText("El archivo no tiene mensajes GRIB." if n else "Archivo vacío.")

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
            self._add_item(it, c, 1)
        return root

    def _add_item(self, parent_item, node, level):
        it = QTreeWidgetItem(parent_item, [node.name, node.text, f"{node.offset} +{node.size}"])
        it.setIcon(0, self.level_icon(level))
        self._nodes[id(it)] = node
        self._items[id(node)] = it
        if node.kind in ("data", "row") and not node.children:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        for c in node.children:
            self._add_item(it, c, level + 1)
        return it

    def _level_of(self, item):
        n = 0
        while item.parent() is not None:
            item = item.parent()
            n += 1
        return n

    def _ensure_rows(self, item):
        """Cuelga las filas de un nodo de datos (una sola vez)."""
        node = self._nodes.get(id(item))
        if node is None or node.kind != "data" or node.children:
            return node
        level = self._level_of(item) + 1
        for r in gh.data_rows(node):
            node.add(r)
            self._add_item(item, r, level)
        it = item
        it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        return node

    def _ensure_cells(self, item):
        """Cuelga las celdas de una fila (una sola vez)."""
        row = self._nodes.get(id(item))
        if row is None or row.kind != "row" or row.children:
            return row
        data_node = row.parent
        values = None
        if self._values_provider is not None and (data_node.meta or {}).get("template") not in (0, 4):
            msg = gh.path_of(data_node)[0]
            try:
                values = self._values_provider(msg.offset)
            except Exception:
                values = None
        level = self._level_of(item) + 1
        for c in gh.row_cells(self._data, data_node, row, values):
            row.add(c)
            self._add_item(item, c, level)
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicatorWhenChildless)
        return row

    def _on_expanded(self, item):
        if item.parent() is None:
            self._ensure_parsed(item.data(0, _ROLE_NODE))
            return
        node = self._nodes.get(id(item))
        if node is None:
            return
        if node.kind == "data":
            self._ensure_rows(item)
        elif node.kind == "row":
            self._ensure_cells(item)

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
        chain = gh.path_of(node)
        self.hex.set_path([(n.offset, n.size) for n in chain])
        self.hex.scroll_to(node.offset)
        path = " ▸ ".join(n.name for n in chain)
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
        if node.kind == "data":
            k = gh.cell_at(node.meta or {}, pos)
            if k is not None:
                self._select_cell(node, k)
                return
        it = self._items.get(id(node))
        if it is None:
            return
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)

    def _data_node(self, root):
        for sec in root.children:
            for c in sec.children:
                if c.kind == "data":
                    return c
        return None

    def _select_cell(self, data_node, k):
        """Abre filas y celdas hasta el valor `k` del nodo de datos y lo elige."""
        it = self._items.get(id(data_node))
        if it is None or k < 0 or k >= gh.cell_count(data_node.meta or {}):
            return False
        self._ensure_rows(it)
        r = gh.row_of(data_node, k)
        if r >= len(data_node.children):
            return False
        row = data_node.children[r]
        rit = self._items[id(row)]
        self._ensure_cells(rit)
        cell = row.children[k - row.meta["k0"]]
        cit = self._items[id(cell)]
        it.setExpanded(True)
        rit.setExpanded(True)
        self.tree.setCurrentItem(cit)
        self.tree.scrollToItem(cit)
        return True

    def goto_cell(self, msg_offset, k):
        """Elige el valor `k` (en el orden del archivo) del mensaje que
        empieza en `msg_offset`; si no hay celdas, la sección de datos.
        Devuelve True si pudo."""
        i = self._by_offset.get(int(msg_offset))
        if i is None:
            return False
        root = self._ensure_parsed(i)
        data_node = self._data_node(root)
        if data_node is None:
            self.tree.setCurrentItem(self.tree.topLevelItem(i))
            return False
        if self._select_cell(data_node, int(k)):
            return True
        it = self._items.get(id(data_node))
        self.tree.setCurrentItem(it)
        self.tree.scrollToItem(it)
        return False

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
