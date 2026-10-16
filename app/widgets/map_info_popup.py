# -*- coding: utf-8 -*-
"""Ficha que aparece con un clic (sin arrastrar) sobre el mapa: el punto, el
archivo y la FIR bajo el cursor, ordenados por sección, con un botón que
lleva a la consulta de punto (la misma del clic derecho).

Es un widget hijo del mapa (no una ventana aparte): se dibuja encima del
canvas con los colores y tamaños del tema (QFrame#MapInfoPopup) y se
cierra sola con un clic fuera de ella o con Escape.
"""
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QApplication)


class MapInfoPopup(QFrame):
    consult_requested = pyqtSignal(float, float)      # lat, lon

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("MapInfoPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._lat = self._lon = None
        self._sections = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        lay.addLayout(self._body)
        row = QHBoxLayout()
        self.lbl_hint = QLabel("Clic derecho sobre el mapa, o este botón: consulta por nivel y hora")
        self.lbl_hint.setObjectName("PopupHint")
        row.addWidget(self.lbl_hint, 1)
        self.btn_consult = QPushButton("Consultar punto…")
        self.btn_consult.setObjectName("AccentBtn")
        self.btn_consult.clicked.connect(self._consult)
        row.addWidget(self.btn_consult)
        lay.addLayout(row)
        self.hide()
        # Un clic fuera de la ficha (en el mapa, el panel o donde sea) la cierra
        QApplication.instance().installEventFilter(self)

    # ── Contenido ────────────────────────────────────────────────────────────

    def set_sections(self, sections):
        """`sections`: [(título, texto)] en orden; las vacías se omiten."""
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
        """Todo el contenido en texto plano (tests y portapapeles)."""
        return "\n".join(f"{t}\n{x}" for t, x in self._sections)

    def show_at(self, pos: QPoint, lat=None, lon=None):
        """Muestra la ficha junto a `pos` (coordenadas del padre), dentro de
        los límites del padre."""
        self._lat, self._lon = lat, lon
        self.btn_consult.setEnabled(lat is not None and lon is not None)
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

    def _consult(self):
        lat, lon = self._lat, self._lon
        self.hide()
        if lat is not None and lon is not None:
            self.consult_requested.emit(float(lat), float(lon))

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
