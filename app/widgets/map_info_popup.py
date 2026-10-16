# -*- coding: utf-8 -*-
"""Ficha que aparece con un clic (sin arrastrar) sobre el mapa: PUNTO (la
consulta editable: geodésico, hora, FL y las tres capas, el mismo bloque
que la ventana «Consulta de punto»), ARCHIVO (lo de STATUS) y FIR (la que
está bajo el cursor).

Es un widget hijo del canvas del mapa (no una ventana aparte): se dibuja
encima con los colores y tamaños del tema (QFrame#MapInfoPopup) y se
cierra sola con un clic fuera de ella o con Escape.
"""
from PyQt6.QtCore import Qt, QPoint, QEvent
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QApplication)

from .point_query_widget import PointQueryWidget


class MapInfoPopup(QFrame):
    def __init__(self, parent, variation_fn=None):
        super().__init__(parent)
        self.setObjectName("MapInfoPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._sections = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        head = QLabel("PUNTO")
        head.setObjectName("PopupHead")
        lay.addWidget(head)
        self.query = PointQueryWidget(self, variation_fn=variation_fn)
        lay.addWidget(self.query)
        self.lbl_point = QLabel("")          # PUNTO sin consulta (superficie / nivel de presión)
        self.lbl_point.setObjectName("PopupMono")
        self.lbl_point.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_point.hide()
        lay.addWidget(self.lbl_point)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        lay.addLayout(self._body)
        row = QHBoxLayout()
        self.lbl_hint = QLabel("Cambiá geodésico, hora o FL y se recalcula  ·  ⌘I abre la consulta "
                               "en ventana  ·  Escape o clic afuera cierra")
        self.lbl_hint.setObjectName("PopupHint")
        row.addWidget(self.lbl_hint, 1)
        self.btn_copy = QPushButton("Copiar")
        self.btn_copy.setToolTip("Copia la consulta y los valores como texto")
        self.btn_copy.clicked.connect(self.query.copy_text)
        row.addWidget(self.btn_copy)
        lay.addLayout(row)
        self.hide()
        # Un clic fuera de la ficha (en el mapa, el panel o donde sea) la cierra
        QApplication.instance().installEventFilter(self)

    # ── Contenido ────────────────────────────────────────────────────────────

    def set_point_static(self, text):
        """PUNTO como texto fijo (sin consulta por FL: archivos de superficie
        o en niveles de presión); None vuelve al bloque editable."""
        self.lbl_point.setText(text or "")
        self.lbl_point.setVisible(bool(text))
        self.query.setVisible(not text)
        self.btn_copy.setVisible(not text)

    def set_sections(self, sections):
        """Secciones fijas después de PUNTO: [(título, texto)]; las vacías se omiten."""
        while self._body.count():
            item = self._body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sections = [(t, x) for t, x in sections if x]
        for title, text in self._sections:
            head = QLabel(title)
            head.setObjectName("PopupHead")
            body = QLabel(text)
            body.setObjectName("PopupMono")
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._body.addWidget(head)
            self._body.addWidget(body)

    def text(self):
        """Las secciones fijas en texto plano (tests)."""
        parts = []
        if self.lbl_point.isVisible() or not self.query.isVisible():
            parts.append("PUNTO\n" + self.lbl_point.text())
        parts += [f"{t}\n{x}" for t, x in self._sections]
        return "\n".join(parts)

    def show_at(self, pos: QPoint):
        """Muestra la ficha junto a `pos` (coordenadas del padre), dentro de
        los límites del padre."""
        self.adjustSize()
        parent = self.parentWidget()
        pw, ph = parent.width(), parent.height()
        x, y = pos.x() + 14, pos.y() + 14
        if x + self.width() > pw:
            x = pos.x() - self.width() - 14
        if y + self.height() > ph:
            y = pos.y() - self.height() - 14
        x = max(0, min(x, pw - self.width()))
        y = max(0, min(y, ph - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()

    def eventFilter(self, obj, event):
        if self.isVisible():
            t = event.type()
            if t == QEvent.Type.MouseButtonPress:
                try:
                    gp = event.globalPosition().toPoint()
                except AttributeError:
                    gp = None
                if gp is None or not self.rect().contains(self.mapFromGlobal(gp)):
                    self.hide()
            elif t == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self.hide()
        return super().eventFilter(obj, event)
