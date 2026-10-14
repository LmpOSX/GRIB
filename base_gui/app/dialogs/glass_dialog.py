"""
Base class for all glassmorphism dialogs.
Uses a native macOS titlebar (transparent + full-size content view) so the
dialog is draggable and has native traffic-light window controls, while the
background still shows frosted-glass blur identical to the main window.
"""
from PyQt6.QtWidgets import QDialog, QGraphicsDropShadowEffect, QFrame
from PyQt6.QtCore import Qt, QTimer, QEvent
from PyQt6.QtGui import QColor


import sys

# Height reserved at the top of the dialog for the native titlebar / traffic lights
TITLEBAR_HEIGHT = 28
_IS_MAC = sys.platform == "darwin"


def add_shadow(widget):
    """Legacy helper — kept for API compatibility but the shadow is
    removed at show-time by GlassDialog so dialogs look flush."""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(50)
    shadow.setOffset(0, 12)
    shadow.setColor(QColor(0, 0, 0, 160))
    widget.setGraphicsEffect(shadow)


class GlassDialog(QDialog):
    """QDialog with a native titlebar, glass background and native blur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # Native titlebar: standard Dialog flag (no FramelessWindowHint)
        self.setWindowFlags(Qt.WindowType.Dialog)
        # El fondo translúcido solo tiene sentido con el desenfoque nativo de
        # macOS; en Windows/Linux el diálogo es opaco (fondo del tema).
        if _IS_MAC:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def showEvent(self, event):
        super().showEvent(event)
        # Leave room at the top for the native titlebar / traffic lights
        # (solo macOS: con FullSizeContentView el contenido sube bajo la barra)
        layout = self.layout()
        if layout and _IS_MAC:
            m = layout.contentsMargins()
            layout.setContentsMargins(m.left(), TITLEBAR_HEIGHT, m.right(), m.bottom())
        # Remove drop-shadow effects from GlassPanel children
        for child in self.findChildren(QFrame):
            if child.objectName() == "GlassPanel":
                child.setGraphicsEffect(None)
        if not hasattr(self, "_blur_applied"):
            self._blur_applied = True
            _apply_dialog_blur(self)
            # Al convertir la ventana nativa (barra transparente + contenido a
            # pantalla completa) macOS la deja más baja que su contenido y los
            # widgets se aplastan o se superponen.  Se reajusta en el próximo
            # ciclo de eventos y se fija una altura mínima igual a la necesaria.
            QTimer.singleShot(0, self._fit_to_contents)

    def _fit_to_contents(self):
        layout = self.layout()
        if layout:
            layout.activate()
        hint = self.sizeHint()
        min_h = max(self.minimumHeight(), hint.height())
        min_w = max(self.minimumWidth(), hint.width())
        # Nunca más alto/ancho que la pantalla disponible (las tablas internas
        # tienen scroll propio)
        scr = self.screen()
        if scr is not None:
            avail = scr.availableGeometry()
            min_h = min(min_h, avail.height() - 40)
            min_w = min(min_w, avail.width() - 40)
        self.setMinimumSize(min_w, min_h)
        if self.height() < min_h or self.width() < min_w:
            self.resize(max(self.width(), min_w), max(self.height(), min_h))
        self._relayout_full_rect()

    def _relayout_full_rect(self):
        """Con NSWindowStyleMaskFullSizeContentView el contenido crece hacia
        arriba (bajo la barra de título) pero los eventos de resize que llegan
        al layout traen el alto SIN esa franja: el layout quedaba 28 px más
        bajo que el widget y aplastaba los campos.  Se reaplica el rect real."""
        layout = self.layout()
        if layout and layout.geometry() != self.rect():
            layout.setGeometry(self.rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_full_rect()

    def event(self, event):
        handled = super().event(event)
        # Un LayoutRequest posterior (polish de estilos, cambio de sizeHint)
        # vuelve a aplicar el rect reducido; se corrige de nuevo.
        if event.type() == QEvent.Type.LayoutRequest:
            self._relayout_full_rect()
        return handled


def _apply_dialog_blur(widget):
    """Apply native blur + transparent titlebar to a dialog's NSWindow."""
    import platform
    if platform.system() != "Darwin":
        return
    try:
        import objc
        from AppKit import NSVisualEffectView, NSColor
        from ctypes import c_void_p

        wid = int(widget.winId())
        ns_view = objc.objc_object(c_void_p=wid)
        ns_window = ns_view.window()
        if ns_window is None:
            return

        # ── Native titlebar: transparent + full-size content view ──
        # NSWindowStyleMaskFullSizeContentView = 1 << 15
        ns_window.setStyleMask_(ns_window.styleMask() | (1 << 15))
        ns_window.setTitlebarAppearsTransparent_(True)
        # NSWindowTitleHidden = 1
        ns_window.setTitleVisibility_(1)
        # NO usar setMovableByWindowBackground_: con fondo translúcido AppKit
        # se queda con el arrastre sobre sliders y otros controles.  La barra
        # de título (transparente pero presente) sigue permitiendo mover.

        content_view = ns_window.contentView()
        superview = content_view.superview()
        if superview is None:
            return

        effect_view = NSVisualEffectView.alloc().initWithFrame_(superview.bounds())
        effect_view.setMaterial_(13)      # HUDWindow
        effect_view.setBlendingMode_(0)   # BehindWindow
        effect_view.setState_(1)          # Active
        effect_view.setAutoresizingMask_(18)

        superview.addSubview_positioned_relativeTo_(
            effect_view, -1, content_view)

        ns_window.setBackgroundColor_(NSColor.clearColor())
        ns_window.setOpaque_(False)

    except Exception:
        pass
