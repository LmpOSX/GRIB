# -*- coding: utf-8 -*-
"""Tests offscreen de la ventana principal y los diálogos (Fase 2).

Se corren con QT_QPA_PLATFORM=offscreen. El desenfoque nativo de los
diálogos se anula (hace segfault en offscreen) y la configuración se aísla
en un directorio temporal.
"""
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app import config  # noqa: E402
from app.dialogs import glass_dialog  # noqa: E402

glass_dialog._apply_dialog_blur = lambda w: None

_app = QApplication.instance() or QApplication([])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_cfg_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(self._tmp.name, "config.json")
        self.w = None

    def tearDown(self):
        if self.w is not None:
            self.w.close()
            self.w.deleteLater()
            _app.processEvents()
        config.CONFIG_PATH = self._old_cfg_path
        self._tmp.cleanup()


class TestMainWindow(_Base):
    def _window(self):
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()
        return self.w

    def test_abre_y_cierra(self):
        w = self._window()
        self.assertTrue(w.isVisible())
        self.assertEqual(w.windowTitle(), "Visor GRIB")
        self.assertTrue(w._welcome.isVisible())
        self.assertFalse(w._main_area.isVisible())
        w.close()
        self.assertTrue(os.path.exists(config.CONFIG_PATH))

    def test_menus(self):
        w = self._window()
        titles = [a.text() for a in w._menubar.actions()]
        self.assertEqual(titles, ["Archivo", "Vista", "Ayuda"])
        self.assertFalse(w._act_export_png.isEnabled())
        self.assertFalse(w._act_close.isEnabled())
        self.assertEqual(w._act_open.shortcut().toString(), "Ctrl+O")
        self.assertEqual(w._act_full.shortcut().toString(), "Ctrl+Shift+0")
        self.assertEqual(w._act_layer.shortcut().toString(), "Ctrl+D")

    def test_zoom_de_fuente_persistido(self):
        import json
        w = self._window()
        base = w._cfg["font_size"]
        w._font_size_up()
        self.assertEqual(w._cfg["font_size"], base + 1)
        with open(config.CONFIG_PATH) as fh:
            self.assertEqual(json.load(fh)["font_size"], base + 1)
        w._font_size_reset()
        self.assertEqual(w._cfg["font_size"], 13)
        w._font_size_down()
        self.assertEqual(w._cfg["font_size"], 12)

    def test_un_solo_escape(self):
        from PyQt6.QtGui import QShortcut
        w = self._window()
        escapes = [s for s in w.findChildren(QShortcut)
                   if s.key().toString() == "Esc"]
        self.assertEqual(len(escapes), 1)

    def test_recientes_faltante_se_elimina(self):
        w = self._window()
        w._cfg["recent_files"] = ["/ruta/que/no/existe.grib2"]
        w._refresh_recent_menu()
        from PyQt6.QtWidgets import QMessageBox
        old = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: None)
        try:
            w._open_recent("/ruta/que/no/existe.grib2")
        finally:
            QMessageBox.warning = old
        self.assertEqual(w._cfg["recent_files"], [])

    def test_objetos_del_stylesheet(self):
        w = self._window()
        names = {c.objectName() for c in w.findChildren(object)
                 if hasattr(c, "objectName")}
        for n in ("MainContainer", "AppMenuBar", "ContentPanel", "ActionBar",
                  "ActionSep", "WelcomeWidget"):
            self.assertIn(n, names)

    def test_tema_cambia_stylesheet(self):
        w = self._window()
        before = _app.styleSheet()
        w._apply_theme("#C0674D")
        self.assertNotEqual(before, _app.styleSheet())
        self.assertEqual(w._cfg["accent_color"], "#C0674D")


class TestDialogos(_Base):
    def test_settings(self):
        from app.dialogs.settings_dialog import SettingsDialog
        self.w = SettingsDialog(None, "#4A90D9", 180)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.w._select_color("#5B8C5A")
        self.assertEqual(self.w.selected_color(), "#5B8C5A")
        self.w.accept()
        self.assertFalse(self.w.isVisible())

    def test_shortcuts(self):
        from app.dialogs.shortcuts_dialog import ShortcutsDialog, SHORTCUTS
        self.w = ShortcutsDialog(None)
        self.w.show()
        _app.processEvents()
        self.assertEqual(self.w._table.rowCount(), len(SHORTCUTS))
        self.w.accept()

    def test_about(self):
        from app.dialogs.about_dialog import AboutDialog
        from app.dialogs.glass_dialog import GlassDialog
        self.w = AboutDialog(None)
        self.assertIsInstance(self.w, GlassDialog)
        self.w.show()
        _app.processEvents()
        self.assertTrue(self.w.isVisible())
        self.w.accept()

    def test_todos_los_dialogos_son_glass(self):
        import inspect
        from PyQt6.QtWidgets import QDialog
        from app.dialogs import about_dialog, settings_dialog, shortcuts_dialog
        from app.dialogs.glass_dialog import GlassDialog
        for mod in (about_dialog, settings_dialog, shortcuts_dialog):
            for _, cls in inspect.getmembers(mod, inspect.isclass):
                if issubclass(cls, QDialog) and cls is not QDialog and cls.__module__ == mod.__name__:
                    self.assertTrue(issubclass(cls, GlassDialog), cls)


if __name__ == "__main__":
    unittest.main()


class TestPantallaCompleta(_Base):
    def test_disable_native_fullscreen_fuera_de_mac(self):
        from app import platform_blur
        import platform as _pl
        old = _pl.system
        _pl.system = lambda: "Linux"
        try:
            self.assertFalse(platform_blur.disable_native_fullscreen(None))
        finally:
            _pl.system = old
