# -*- coding: utf-8 -*-
"""Volcado hexadecimal estilo `hexdump -C` (posición · 16 bytes en hex ·
ASCII) con tramos pintados: cada mensaje con un tinte alternado, el nodo
elegido con el acento y sus hijos con colores propios. Pinta sólo las filas
visibles, así que sirve para archivos grandes."""
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPainter, QFont, QFontMetrics, QColor, QPen
from PyQt6.QtWidgets import QAbstractScrollArea

BYTES_PER_ROW = 16


class HexView(QAbstractScrollArea):
    byte_clicked = pyqtSignal(int)          # posición del byte sobre el que se hizo clic

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HexView")
        self._data = b""
        self._messages = []                 # [(offset, size)] para el tinte alternado
        self._selected = None               # (offset, size) con el acento
        self._children = []                 # [(offset, size, índice de color)]
        self._colors = None
        self._font = QFont("Menlo")
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setPointSize(12)
        self._metrics()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)

    # ── Configuración ────────────────────────────────────────────────────

    def set_colors(self, colors):
        self._colors = colors
        self.viewport().update()

    def set_font_size(self, pt):
        self._font.setPointSize(max(8, int(pt)))
        self._metrics()
        self._update_scrollbars()
        self.viewport().update()

    def set_data(self, data, messages=None):
        self._data = data
        self._messages = list(messages or [])
        self._selected = None
        self._children = []
        self._update_scrollbars()
        self.viewport().update()

    def set_selection(self, offset, size, children=None):
        """Tramo elegido y, si se dan, (offset, size) de sus hijos para
        pintarlos con colores distintos."""
        self._selected = (int(offset), int(size)) if size else None
        self._children = [(int(o), int(s), i % 8) for i, (o, s) in enumerate(children or []) if s]
        self.viewport().update()

    def clear_selection(self):
        self.set_selection(0, 0)

    def scroll_to(self, offset, margin_rows=2):
        """Deja la fila del byte a la vista (con unas filas de margen arriba)."""
        row = int(offset) // BYTES_PER_ROW
        first = self.verticalScrollBar().value()
        visible = max(1, self.viewport().height() // self._row_h)
        if row < first + margin_rows or row >= first + visible - margin_rows:
            self.verticalScrollBar().setValue(max(0, row - margin_rows))

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(self._width + 24, 480)

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(self._width + 24, 200)

    def row_count(self):
        return (len(self._data) + BYTES_PER_ROW - 1) // BYTES_PER_ROW

    def selection(self):
        return self._selected

    # ── Geometría ────────────────────────────────────────────────────────

    def _metrics(self):
        fm = QFontMetrics(self._font)
        self._char_w = fm.horizontalAdvance("0")
        self._row_h = fm.height() + 4
        self._ascent = fm.ascent() + 2
        self._x_off = 8
        self._x_hex = self._x_off + self._char_w * 9 + 8        # «00000000 »
        self._x_asc = self._x_hex + self._char_w * (BYTES_PER_ROW * 3 + 1) + 12
        self._width = self._x_asc + self._char_w * (BYTES_PER_ROW + 2) + 8

    def _update_scrollbars(self):
        vb = self.verticalScrollBar()
        visible = max(1, self.viewport().height() // self._row_h)
        vb.setRange(0, max(0, self.row_count() - visible))
        vb.setPageStep(visible)
        vb.setSingleStep(1)
        hb = self.horizontalScrollBar()
        hb.setRange(0, max(0, self._width - self.viewport().width()))
        hb.setPageStep(self.viewport().width())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrollbars()

    def _byte_rect(self, pos, x0):
        """Rectángulo del byte `pos` en la columna hexadecimal."""
        row = pos // BYTES_PER_ROW
        col = pos % BYTES_PER_ROW
        first = self.verticalScrollBar().value()
        x = self._x_hex + col * 3 * self._char_w + (self._char_w if col >= 8 else 0) - x0
        y = (row - first) * self._row_h
        return QRect(x - 1, y, self._char_w * 2 + 2, self._row_h)

    def _ascii_rect(self, pos, x0):
        row = pos // BYTES_PER_ROW
        col = pos % BYTES_PER_ROW
        first = self.verticalScrollBar().value()
        x = self._x_asc + (col + 1) * self._char_w - x0
        y = (row - first) * self._row_h
        return QRect(x, y, self._char_w, self._row_h)

    def byte_at(self, point):
        """Posición del byte bajo el punto (columna hex o ASCII), o None."""
        x = point.x() + self.horizontalScrollBar().value()
        row = self.verticalScrollBar().value() + point.y() // self._row_h
        if row < 0 or row >= self.row_count():
            return None
        col = None
        if self._x_hex <= x < self._x_asc:
            rel = x - self._x_hex
            if rel >= 8 * 3 * self._char_w + self._char_w:
                rel -= self._char_w
            col = int(rel // (3 * self._char_w))
        elif self._x_asc + self._char_w <= x < self._x_asc + (BYTES_PER_ROW + 1) * self._char_w:
            col = int((x - self._x_asc - self._char_w) // self._char_w)
        if col is None or col < 0 or col >= BYTES_PER_ROW:
            return None
        pos = row * BYTES_PER_ROW + col
        return pos if pos < len(self._data) else None

    def mousePressEvent(self, event):
        pos = self.byte_at(event.position().toPoint())
        if pos is not None:
            self.byte_clicked.emit(pos)
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        # Rueda: 3 filas por paso, como un editor de texto
        delta = event.angleDelta().y()
        if delta:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - (3 * delta // 120))
            event.accept()
        else:
            super().wheelEvent(event)

    # ── Pintado ──────────────────────────────────────────────────────────

    def _fill_range(self, painter, start, size, color, x0, rows):
        """Pinta el fondo de un tramo de bytes (hex y ASCII) por filas."""
        first_row, last_row = rows
        end = start + size
        lo = max(start, first_row * BYTES_PER_ROW)
        hi = min(end, (last_row + 1) * BYTES_PER_ROW)
        if lo >= hi:
            return
        pos = lo
        while pos < hi:
            row_end = min(hi, (pos // BYTES_PER_ROW + 1) * BYTES_PER_ROW)
            r1 = self._byte_rect(pos, x0)
            r2 = self._byte_rect(row_end - 1, x0)
            painter.fillRect(QRect(r1.left(), r1.top(), r2.right() - r1.left() + 1, r1.height()), color)
            a1 = self._ascii_rect(pos, x0)
            a2 = self._ascii_rect(row_end - 1, x0)
            painter.fillRect(QRect(a1.left(), a1.top(), a2.right() - a1.left() + 1, a1.height()), color)
            pos = row_end

    def paintEvent(self, event):
        c = self._colors
        painter = QPainter(self.viewport())
        painter.setFont(self._font)
        if c is None:
            painter.end()
            return
        painter.fillRect(self.viewport().rect(), c["bg"])
        first = self.verticalScrollBar().value()
        x0 = self.horizontalScrollBar().value()
        visible = self.viewport().height() // self._row_h + 1
        last = min(self.row_count() - 1, first + visible)
        rows = (first, last)
        n = len(self._data)
        if n == 0:
            painter.setPen(c["text_dim"])
            painter.drawText(self._x_off, self._ascent, "(archivo vacío)")
            painter.end()
            return
        # Tintes de los mensajes (alternados), sólo los que tocan las filas visibles
        lo_byte, hi_byte = first * BYTES_PER_ROW, (last + 1) * BYTES_PER_ROW
        for i, (off, size) in enumerate(self._messages):
            if off >= hi_byte or off + size <= lo_byte:
                continue
            self._fill_range(painter, off, size, c["msg_a"] if i % 2 == 0 else c["msg_b"], x0, rows)
        # Hijos del nodo elegido, cada uno con su color
        for off, size, k in self._children:
            self._fill_range(painter, off, size, c["fields"][k], x0, rows)
        # Tramo elegido: fondo del acento (debajo de los hijos si los hay) y marco
        if self._selected:
            off, size = self._selected
            if not self._children:
                self._fill_range(painter, off, size, c["selected"], x0, rows)
            painter.setPen(QPen(c["selected"], 2))
            end = off + size
            pos = max(off, lo_byte)
            while pos < min(end, hi_byte):
                row_end = min(end, (pos // BYTES_PER_ROW + 1) * BYTES_PER_ROW)
                r1 = self._byte_rect(pos, x0)
                r2 = self._byte_rect(row_end - 1, x0)
                painter.drawRect(QRect(r1.left(), r1.top() + 1, r2.right() - r1.left(), r1.height() - 2))
                pos = row_end
        # Texto
        for row in range(first, last + 1):
            y = (row - first) * self._row_h + self._ascent
            start = row * BYTES_PER_ROW
            chunk = bytes(self._data[start:start + BYTES_PER_ROW])
            painter.setPen(c["offset"])
            painter.drawText(self._x_off - x0, y, f"{start:08x}")
            painter.setPen(c["text"])
            hex_parts = []
            for i, b in enumerate(chunk):
                hex_parts.append(f"{b:02x}")
                if i == 7:
                    hex_parts.append("")
            painter.drawText(self._x_hex - x0, y, " ".join(hex_parts))
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            painter.setPen(c["text_dim"])
            painter.drawText(self._x_asc - x0, y, "|" + asc + "|")
        painter.end()
