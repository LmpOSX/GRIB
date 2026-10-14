"""Hoja de atajos de teclado (menú Ayuda)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from .glass_dialog import GlassDialog, add_shadow as _add_shadow


# (grupo, acción, atajo).  Cmd = tecla ⌘ en macOS (Ctrl en Windows/Linux).
SHORTCUTS = [
    ("Archivo", "Nuevo presupuesto", "Cmd N"),
    ("Archivo", "Abrir…", "Cmd O"),
    ("Archivo", "Guardar", "Cmd S"),
    ("Archivo", "Cerrar", "Cmd W"),
    ("Archivo", "Exportar a Excel…", "Cmd E"),
    ("Edición", "Deshacer", "Cmd Z"),
    ("Edición", "Rehacer", "Cmd Shift Z"),
    ("Presupuesto", "Nueva sección", "Cmd Shift N"),
    ("Presupuesto", "Nuevo ítem", "Cmd I"),
    ("Presupuesto", "Nueva hoja (ítem presupuestario)", "Cmd P"),
    ("Presupuesto", "Buscar", "Cmd F"),
    ("Presupuesto", "Limpiar búsqueda", "Esc"),
    ("Presupuesto", "Menú de columnas visibles", "Cmd Shift C"),
    ("Presupuesto", "Gestionar versiones", "Cmd Shift V"),
    ("Presupuesto", "Monedas", "Cmd M"),
    ("Vista", "Agrandar fuente", "Cmd + (o Alt +)"),
    ("Vista", "Achicar fuente", "Cmd − (o Alt −)"),
    ("Vista", "Tamaño de fuente normal", "Cmd 0 (o Alt 0)"),
    ("Celdas", "Seleccionar la fila", "Clic"),
    ("Celdas", "Editar un valor manual", "Clic largo en la celda (mantener apretado)"),
    ("Celdas", "Renombrar el presupuesto (fila 0) o una sección", "Clic largo en su nombre"),
    ("Celdas", "Guardar / cancelar la edición", "Enter / Esc"),
    ("Celdas", "Abrir el diálogo completo del ítem o sección", "Doble clic"),
    ("Celdas", "Fijar un % individual (tasa, margen, prorrateo)", "Clic en la subcolumna %"),
    ("Columnas extra", "Seleccionar / extender la selección", "Shift + clic en el encabezado"),
    ("Columnas extra", "Deseleccionar", "Clic simple o Esc"),
    ("Columnas extra", "Mover la selección", "Cmd Shift ← / →"),
    ("Columnas extra", "Mover una columna", "Arrastrar el encabezado"),
    ("Columnas extra", "Editar la columna", "Doble clic en el encabezado"),
    ("Columnas extra", "Ocultar, limpiar tasas, eliminar…", "Clic derecho en el encabezado"),
    ("Columnas extra", "Agrupar las columnas seleccionadas", "Alt Shift → (o clic derecho)"),
    ("Columnas extra", "Desagrupar", "Alt Shift ← (o clic derecho)"),
    ("Columnas extra", "Contraer / expandir un grupo", "Clic en el − / + sobre el encabezado"),
    ("Hojas", "Renombrar una hoja", "Doble clic en la pestaña"),
    ("Hojas", "Reordenar hojas", "Arrastrar la pestaña"),
    ("Hojas", "Convertir una sección en hoja nueva (ítem presupuestario)", "Arrastrar la sección a la pestaña +"),
    ("Hojas", "Mover una sección a una hoja", "Arrastrar la sección a la pestaña de esa hoja"),
    ("Ítems", "Mover un ítem o sección", "Arrastrar la fila"),
    ("Panel fijo", "Ajustar el panel al contenido", "Doble clic en el separador"),
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
                keys = keys.replace("Cmd", MOD_KEY).replace("Alt Shift", "Alt Shift")
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
