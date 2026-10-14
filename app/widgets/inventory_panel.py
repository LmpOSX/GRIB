# -*- coding: utf-8 -*-
"""Panel de inventario del archivo GRIB: texto de sólo lectura en fuente
monoespaciada (corrida, pasos, variables, niveles, grilla)."""
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QPlainTextEdit


class InventoryPanel(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setMinimumHeight(60)      # toma el alto que sobra; scroll interno
        self.set_text("Sin archivo abierto.")

    def set_text(self, text: str):
        self.setPlainText(text or "")
        self.moveCursor(self.textCursor().MoveOperation.Start)
