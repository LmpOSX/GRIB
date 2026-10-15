"""Hoja de atajos de teclado (menú Ayuda)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from .glass_dialog import GlassDialog, add_shadow as _add_shadow


# (grupo, acción, atajo).  Cmd = tecla ⌘ en macOS (Ctrl en Windows/Linux).
SHORTCUTS = [
    ("Archivo", "Abrir GRIB…", "Cmd O"),
    ("Archivo", "Obtener datos…", "Cmd Shift D"),
    ("Archivo", "Exportar PNG…", "Cmd E"),
    ("Archivo", "Exportar CSV…", "Cmd Shift E"),
    ("Archivo", "Exportar a WAFS…", "Cmd Shift W"),
    ("Archivo", "Cerrar archivo", "Cmd W"),
    ("Archivo", "Salir", "Cmd Q"),
    ("Vista", "Todo el dominio", "Cmd Shift 0"),
    ("Vista", "Actualizar (redibujar)", "F5"),
    ("Vista", "Capa de datos activada / desactivada", "Cmd D"),
    ("Vista", "Panel lateral (mostrar / ocultar)", "Cmd Shift P"),
    ("Vista", "Pantalla completa (entrar / salir)", "Ctrl Cmd F (botón verde) · F11"),
    ("Vista", "Límites de FIR de Argentina (mostrar / ocultar)", "Cmd Shift F"),
    ("Vista", "FIR vecinas, extremos y cobertura, configurar FIR", "Menú Vista ▸ FIR"),
    ("Vista", "Preferencias…", "Cmd ,"),
    ("Vista", "Agrandar fuente", "Cmd + (o Alt +)"),
    ("Vista", "Achicar fuente", "Cmd − (o Alt −)"),
    ("Vista", "Tamaño de fuente normal", "Cmd 0 (o Alt 0)"),
    ("Vista", "Acercar / alejar un paso fino", "Cmd Shift + / Cmd Shift −  (botones + y − de la barra)"),
    ("Mapa", "Desplazar el mapa (pan)", "Arrastrar con el botón izquierdo"),
    ("Mapa", "Desplazar fino (÷ N, Preferencias ▸ Mapa)", "Cmd (o Shift) + arrastrar"),
    ("Mapa", "Acercar / alejar alrededor del cursor", "Rueda del mouse"),
    ("Mapa", "Acercar / alejar fino alrededor del cursor", "Cmd (o Shift) + rueda"),
    ("Mapa", "Paso normal con los botones + y −", "Alt + clic en el botón"),
    ("Mapa", "Volver a la vista inicial", "Botón Inicio"),
    ("Mapa", "Valores bajo el cursor", "Mover el mouse sobre el mapa"),
    ("Mapa", "FIR bajo el cursor (nombre y código)", "Mover el mouse con la capa de FIR activa"),
    ("Mapa", "Extremos y cobertura de la FIR", "Clic (sin arrastrar) dentro de la FIR"),
    ("Panel", "Cambiar paso, nivel, variable u opción", "Redibuja automáticamente"),
    ("Panel", "Aplicar el recuadro lat/lon", "Enter en un campo"),
    ("Ayuda", "Atajos de teclado", "Cmd /"),
]


class ShortcutsDialog(GlassDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Atajos de teclado")
        self.setMinimumWidth(640)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel("Atajos de teclado y gestos")
        title.setObjectName("Heading")
        lay.addWidget(title)

        table = QTableWidget(len(SHORTCUTS), 3)
        table.setHorizontalHeaderLabels(["Grupo", "Acción", "Atajo"])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setMinimumHeight(300)
        table.setMaximumHeight(480)     # el resto se recorre con el scroll de la tabla
        from ..utils import MOD_KEY, IS_MAC
        for r, (grp, action, keys) in enumerate(SHORTCUTS):
            if not IS_MAC:
                keys = keys.replace("Cmd", MOD_KEY)
            table.setItem(r, 0, QTableWidgetItem(grp))
            table.setItem(r, 1, QTableWidgetItem(action))
            table.setItem(r, 2, QTableWidgetItem(keys))
        lay.addWidget(table)
        self._table = table

        # La rueda sobre cualquier parte del diálogo recorre la tabla
        table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        table.setFocus()

        row = QHBoxLayout()
        row.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

    def wheelEvent(self, event):
        # Rueda fuera de la tabla (título, márgenes, encabezado): desplazar la
        # tabla igual.  Los eventos sintetizados no se propagan, no hay bucle.
        from PyQt6.QtWidgets import QApplication
        QApplication.sendEvent(self._table.verticalScrollBar(), event)
        event.accept()
