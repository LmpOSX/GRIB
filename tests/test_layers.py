# -*- coding: utf-8 -*-
"""Menú Capas de la barra de acciones: cada capa del mapa se prende y apaga
por separado (GRIB, marco, fondo, Extra Info, costas, grilla de grados,
grilla del archivo, FIR, Working Areas) y queda sincronizado con el panel,
el menú Vista y la configuración."""
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


class TestCapas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qt()
        cls.tmp = tempfile.mkdtemp()
        from app import config
        cls._old = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(cls.tmp, "config.json")
        shutil.copy(os.path.join(os.path.dirname(__file__), "data", "WAFS_like_test.grib2"),
                    os.path.join(cls.tmp, "w.grib2"))

    @classmethod
    def tearDownClass(cls):
        from app import config
        config.CONFIG_PATH = cls._old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        try:
            os.remove(os.path.join(self.tmp, "config.json"))
        except OSError:
            pass
        from app.main_window import MainWindow
        self.w = MainWindow()
        self.w.show()
        _app.processEvents()

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()

    def _open(self):
        self.w.open_file(os.path.join(self.tmp, "w.grib2"))
        _app.processEvents()

    def test_menu_y_estado_inicial(self):
        w = self.w
        self.assertEqual(w._btn_layers.text(), "Capas")
        self.assertEqual(w._btn_layers.objectName(), "DropdownBtn")
        self.assertIsNotNone(w._btn_layers.menu())
        self.assertEqual([k for k, _t in w.LAYERS], list(w._layer_actions))
        w._sync_layers_menu()
        checked = {k: a.isChecked() for k, a in w._layer_actions.items()}
        self.assertEqual(checked, {"grib": True, "frame": False, "fill": False, "extra": False,
                                   "coast": True, "graticule": True, "filegrid": False,
                                   "fir": False, "wa": False})
        self.assertTrue(all(a.isCheckable() for a in w._layer_actions.values()))

    def test_costas_y_grilla_de_grados(self):
        w = self.w
        self._open()
        n_base = len(w.plot._base_artists)
        n_gl = len(w.plot._gridliners)
        self.assertGreater(n_base, 0)
        self.assertGreater(n_gl, 0)
        w.set_layer_visible("coast", False)
        self.assertFalse(w._cfg["map_coast"])
        self.assertFalse(w.plot.show_coast)
        self.assertEqual(len(w.plot._base_artists), 0)
        w.set_layer_visible("graticule", False)
        self.assertFalse(w._cfg["map_graticule"])
        self.assertEqual(len(w.plot._gridliners), 0)
        # la grilla del archivo sigue disponible sin la de grados
        w.set_layer_visible("filegrid", True)
        self.assertEqual(len(w.plot._gridliners), 1)
        self.assertTrue(w.panel.chk_grid.isChecked())
        w.set_layer_visible("coast", True)
        w.set_layer_visible("graticule", True)
        self.assertEqual(len(w.plot._base_artists), n_base)
        self.assertEqual(len(w.plot._gridliners), n_gl + 1)
        # también sin archivo abierto (mapa vacío)
        w._file_close()
        w.set_layer_visible("coast", False)
        self.assertEqual(len(w.plot._base_artists), 0)
        w.set_layer_visible("coast", True)
        self.assertGreater(len(w.plot._base_artists), 0)
        with open(os.path.join(self.tmp, "config.json"), encoding="utf-8") as fh:
            self.assertIn('"map_coast": true', fh.read())

    def test_capas_independientes(self):
        w = self.w
        self._open()
        w.set_layer_visible("grib", False)
        self.assertFalse(w._layer_enabled)
        self.assertFalse(w._act_layer.isChecked())
        self.assertEqual(w.panel.btn_disable.text(), "Mostrar capa")
        for key in ("frame", "fill", "extra", "filegrid", "fir", "wa"):
            w.set_layer_visible(key, True)
        self.assertTrue(w._cfg["download_area_draw"])
        self.assertTrue(w._cfg["map_fill"])
        self.assertTrue(w._cfg["map_extra_info"])
        self.assertTrue(w._cfg["map_grid"])
        self.assertTrue(w._cfg["fir_enabled"])
        self.assertTrue(w._cfg["wa_show"])
        self.assertTrue(w.panel.chk_fill.isChecked())
        self.assertTrue(w.panel.chk_extra.isChecked())
        self.assertTrue(w.panel.chk_fir.isChecked())
        self.assertTrue(w.panel.chk_wa.isChecked())
        self.assertTrue(w._act_fir.isChecked())
        self.assertTrue(w._act_area.isChecked())
        self.assertFalse(w._layer_enabled)                      # el GRIB sigue apagado
        w.set_layer_visible("fir", False)
        self.assertFalse(w._cfg["fir_enabled"])
        self.assertTrue(w._cfg["wa_show"])                      # las demás no se tocan
        # los cambios hechos por otra vía se reflejan en el menú
        w._act_layer.trigger()                                  # Ctrl+D
        self.assertTrue(w._layer_enabled)
        w.panel.chk_fill.setChecked(False)
        w._sync_layers_menu()
        self.assertTrue(w._layer_actions["grib"].isChecked())
        self.assertFalse(w._layer_actions["fill"].isChecked())
        self.assertFalse(w._layer_actions["fir"].isChecked())
        self.assertTrue(w._layer_actions["wa"].isChecked())

    def test_preferencias(self):
        from app.dialogs.settings_dialog import SettingsDialog
        w = self.w
        d = SettingsDialog(w, cfg=w._cfg)
        self.assertTrue(d.chk_coast.isChecked())
        self.assertTrue(d.chk_graticule.isChecked())
        d.chk_coast.setChecked(False)
        v = d.values()
        self.assertFalse(v["map_coast"])
        self.assertTrue(v["map_graticule"])
        w.apply_settings(v)
        self.assertFalse(w.plot.show_coast)
        w._sync_layers_menu()
        self.assertFalse(w._layer_actions["coast"].isChecked())


if __name__ == "__main__":
    unittest.main()
