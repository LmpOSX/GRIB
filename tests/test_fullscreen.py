# -*- coding: utf-8 -*-
"""Pantalla completa: la ventana es translúcida con desenfoque y fuera de
pantalla completa, y opaca (fondo del tema) en pantalla completa o sin
desenfoque; Vista ▸ Pantalla completa y sus atajos."""
import os
import shutil
import tempfile
import unittest

_app = None


def _qt():
    global _app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from app.dialogs import glass_dialog
    glass_dialog._apply_dialog_blur = lambda w: None
    return _app


class TestPantallaCompleta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qt()
        cls.tmp = tempfile.mkdtemp()
        from app import config
        cls._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(cls.tmp, "config.json")

    @classmethod
    def tearDownClass(cls):
        from app import config
        config.CONFIG_PATH = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()

    def tearDown(self):
        self.w.showNormal()
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()

    def _translucent(self):
        from PyQt6.QtCore import Qt
        return self.w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def test_opaca_en_pantalla_completa(self):
        w = self.w
        w.set_blur_active(True)
        self.assertTrue(self._translucent())
        self.assertEqual(w.styleSheet(), "")
        w.toggle_fullscreen()
        _app.processEvents()
        self.assertTrue(w.isFullScreen())
        self.assertFalse(self._translucent())
        self.assertIn("QMainWindow { background-color:", w.styleSheet())
        self.assertTrue(w._act_fullscreen.isChecked())
        w.toggle_fullscreen()
        _app.processEvents()
        self.assertFalse(w.isFullScreen())
        self.assertTrue(self._translucent())
        self.assertEqual(w.styleSheet(), "")
        self.assertFalse(w._act_fullscreen.isChecked())
        # el botón verde / el sistema también pasan por changeEvent
        w.showFullScreen()
        _app.processEvents()
        self.assertFalse(self._translucent())
        self.assertTrue(w._act_fullscreen.isChecked())
        w.showNormal()
        _app.processEvents()
        self.assertTrue(self._translucent())

    def test_sin_desenfoque_siempre_opaca(self):
        w = self.w
        w.set_blur_active(False)
        self.assertFalse(self._translucent())
        self.assertIn("background-color", w.styleSheet())
        w.toggle_fullscreen(True)
        _app.processEvents()
        self.assertFalse(self._translucent())
        w.toggle_fullscreen(False)
        _app.processEvents()
        self.assertFalse(self._translucent())
        self.assertIn("background-color", w.styleSheet())
        # el color opaco sigue al acento
        w._apply_theme(accent="#ff0000")
        self.assertIn("#400000", w.styleSheet())

    def test_accion_y_atajos(self):
        w = self.w
        act = w._act_fullscreen
        self.assertEqual(act.text(), "Pantalla completa")
        self.assertTrue(act.isCheckable())
        self.assertEqual([s.toString() for s in act.shortcuts()], ["Meta+Ctrl+F", "F11"])
        act.trigger()
        _app.processEvents()
        self.assertTrue(w.isFullScreen())
        act.trigger()
        _app.processEvents()
        self.assertFalse(w.isFullScreen())


if __name__ == "__main__":
    unittest.main()
