# -*- coding: utf-8 -*-
"""Ficha del punto: aparece con un clic (sin arrastrar) sobre el mapa, o con
Vista ▸ Consultar punto… (⌘I), con PUNTO (la consulta editable: geodésico,
hora, FL y el perfil vertical de la celda) y FIR (la que está bajo el
cursor). Es la única consulta de punto de la aplicación.

Es un widget hijo del canvas del mapa (no una ventana aparte): se dibuja
encima con los colores y tamaños del tema (QFrame#MapInfoPopup). Se queda
con sus propios clics y su rueda (no llegan al mapa) y se cierra sola con
Escape o con un clic fuera de ella; ese clic sólo la cierra, no abre otra.
"""
from PyQt6.QtCore import Qt, QPoint, QEvent, QTimer
from PyQt6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QApplication, QWidget)

from .point_query_widget import PointQueryWidget


class MapInfoPopup(QFrame):
    def __init__(self, parent, variation_fn=None):
        super().__init__(parent)
        self.setObjectName("MapInfoPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._sections = []
        self._swallow_click = False
        self._anchor = None                 # última posición pedida a show_at (coord. del padre)
        self._refit_pending = False
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
        self.lbl_hint = QLabel("Cambiá geodésico, hora o FL y se recalcula  ·  perfil de la celda, "
                               "barbas con el norte arriba  ·  Escape o clic afuera cierra  ·  ⌘I la "
                               "vuelve a abrir")
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

    def _set_compact(self, on):
        """Márgenes y espacios normales (14/10 y 4) o compactos (10/4 y 2)."""
        lay = self.layout()
        if on:
            lay.setContentsMargins(10, 4, 10, 4)
            lay.setSpacing(2)
            self._body.setSpacing(2)
            self.query.layout().setSpacing(2)
        else:
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(4)
            self._body.setSpacing(4)
            self.query.layout().setSpacing(4)

    def show_at(self, pos: QPoint):
        """Muestra la ficha junto a `pos` (coordenadas del padre), dentro de
        los límites del padre."""
        parent = self.parentWidget()
        pw, ph = parent.width(), parent.height()
        prof = self.query.profile
        self._anchor = QPoint(pos)

        def refresh_layouts():
            # Los layouts cachean el sizeHint (updateGeometry lo renueva recién
            # en el próximo LayoutRequest): sin esto la ficha no se achica
            # cuando el perfil tiene menos filas que la vez anterior, y al
            # pasar de un punto sin datos (perfil oculto) a uno con datos el
            # alto «del resto» sale sin el perfil, el perfil recibe de más y
            # sus filas se estiran hasta salirse del mapa
            for lay in (self.query.layout(), self.layout()):
                lay.invalidate()
                lay.activate()

        # El perfil se achica para que la ficha entera entre en el mapa: el
        # alto que ocupa todo lo demás se mide con el sizeHint al día
        self._set_compact(False)
        refresh_layouts()
        other = self.sizeHint().height() - (prof.sizeHint().height() if prof.isVisibleTo(self) else 0)
        prof.set_max_height(ph - other - 16)
        refresh_layouts()
        self.adjustSize()
        # Por si el resto cambió de alto al reacomodarse (un rótulo que se
        # parte en dos líneas al cambiar el ancho): más pasadas, cada una
        # descontando lo que todavía sobresale, hasta que entra
        for _ in range(4):
            if self.height() <= ph or not prof.isVisibleTo(self):
                break
            other = self.sizeHint().height() - prof.sizeHint().height()
            prof.set_max_height(ph - other - 16 - (self.height() - ph))
            refresh_layouts()
            self.adjustSize()
        if self.height() > ph and prof.isVisibleTo(self):
            # Ni con el perfil en su piso entra (mapa muy bajo, fuentes altas):
            # márgenes y espacios compactos, y otra vuelta de ajuste
            self._set_compact(True)
            refresh_layouts()
            other = self.sizeHint().height() - prof.sizeHint().height()
            prof.set_max_height(ph - other - 8)
            refresh_layouts()
            self.adjustSize()
        if self.height() > ph:
            self.resize(self.width(), ph)
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
        self.setFocus()

    def take_click(self):
        """True si el último clic sobre el mapa fue el que cerró la ficha (ese
        clic no debe abrir otra)."""
        was, self._swallow_click = self._swallow_click, False
        return was

    # ── Los eventos del mouse sobre la ficha no pasan al mapa ────────────────

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()

    def _is_own(self, obj):
        w = obj if hasattr(obj, "parentWidget") else None
        while w is not None:
            if w is self:
                return True
            w = w.parentWidget()
        return False

    def eventFilter(self, obj, event):
        if self.isVisible():
            t = event.type()
            if t == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget) and not self._is_own(obj):
                # Clic afuera: cierra; si fue sobre el mapa, ese clic no abre otra.
                # Sólo el evento dirigido al widget: el mismo clic llega antes
                # dirigido a la ventana nativa (QWindow), que no es «propia» ni
                # ajena, y con él la ficha se cerraba aunque el clic fuera sobre
                # un campo suyo
                self._swallow_click = obj is self.parentWidget()
                self.hide()
            elif t == QEvent.Type.MouseButtonRelease and self._swallow_click:
                # Si el clic no llega a informarse (soltó fuera de los ejes), la
                # marca se limpia igual después de este evento
                QTimer.singleShot(0, lambda: setattr(self, "_swallow_click", False))
            elif (t in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                  and event.key() == Qt.Key.Key_Escape):
                self.hide()
                return True
            elif t == QEvent.Type.Resize and obj is self.parentWidget() and not self._refit_pending:
                # El mapa cambió de tamaño con la ficha abierta (la ventana se
                # achicó, o el mapa termina de acomodarse justo después del
                # clic): se vuelve a ajustar al alto nuevo en el mismo lugar,
                # en el acto (show_at sólo toca la ficha, no al mapa)
                self._refit_pending = True
                try:
                    if self._anchor is not None:
                        self.show_at(self._anchor)
                finally:
                    self._refit_pending = False
        return super().eventFilter(obj, event)
