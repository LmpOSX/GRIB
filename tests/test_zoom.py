# -*- coding: utf-8 -*-
"""Zoom y desplazamiento del mapa: paso de la rueda (mouse y trackpad),
modo fino con tecla modificadora, botones ± y atajos, arrastre fino y las
dos preferencias de Mapa."""
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


class _Ev:
    pass


class _Gui:
    def __init__(self, pixels):
        self._pixels = pixels

    def pixelDelta(self):
        class _D:
            def __init__(s, null):
                s._null = null

            def isNull(s):
                return s._null
        return _D(not self._pixels)


class TestZoom(unittest.TestCase):
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
        self.w.open_file(os.path.join(self.tmp, "w.grib2"))
        _app.processEvents()
        self.ax = self.w.plot.ax

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        _app.processEvents()

    def _width(self):
        x0, x1 = self.ax.get_xlim()
        return x1 - x0

    def _scroll(self, button, step, mods=(), pixels=False):
        e = _Ev()
        e.inaxes = self.ax
        e.button = button
        e.step = step
        e.modifiers = frozenset(mods)
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        e.xdata, e.ydata = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        e.guiEvent = _Gui(pixels)
        self.w._on_scroll(e)

    def test_rueda_mouse_y_fina(self):
        w0 = self._width()
        self._scroll("up", 1)
        self.assertAlmostEqual(w0 / self._width(), 1.2, places=6)       # 20 % por muesca
        w1 = self._width()
        self._scroll("down", -1)
        self.assertAlmostEqual(self._width() / w1, 1.2, places=6)
        w2 = self._width()
        self._scroll("up", 1, mods=("ctrl",))                             # Cmd en macOS
        self.assertAlmostEqual(w2 / self._width(), 1.04, places=6)       # 20 % ÷ 5
        w3 = self._width()
        self._scroll("up", 1, mods=("shift",))
        self.assertAlmostEqual(w3 / self._width(), 1.04, places=6)
        w4 = self._width()
        self._scroll("up", 3)                                             # mouse de alta resolución: 3 muescas
        self.assertAlmostEqual(w4 / self._width(), 1.2 ** 3, places=6)
        w5 = self._width()
        self._scroll("up", 50)                                            # acotado a 3 muescas por evento
        self.assertAlmostEqual(w5 / self._width(), 1.2 ** 3, places=6)

    def test_trackpad_en_pixeles(self):
        w0 = self._width()
        self._scroll("up", 10, pixels=True)                               # 10 px = un cuarto de muesca
        self.assertAlmostEqual(w0 / self._width(), 1.2 ** 0.25, places=6)
        w1 = self._width()
        self._scroll("down", -200, pixels=True)                           # acotado a una muesca
        self.assertAlmostEqual(self._width() / w1, 1.2, places=6)
        w2 = self._width()
        self._scroll("up", 40, mods=("ctrl",), pixels=True)
        self.assertAlmostEqual(w2 / self._width(), 1.04, places=6)

    def test_botones_y_atajos(self):
        w = self.w
        w0 = self._width()
        w.zoom_in_fine()
        self.assertAlmostEqual(w0 / self._width(), 1.04, places=6)
        w.zoom_out_fine()
        self.assertAlmostEqual(self._width(), w0, places=6)
        w.zoom_in()
        self.assertAlmostEqual(w0 / self._width(), 1.2, places=6)
        w.zoom_out()
        self.assertAlmostEqual(self._width(), w0, places=6)
        w._btn_zoom_in.click()                                            # sin Alt: paso fino
        self.assertAlmostEqual(w0 / self._width(), 1.04, places=6)
        w._btn_zoom_out.click()
        self.assertAlmostEqual(self._width(), w0, places=6)
        self.assertEqual(w._act_zoom_in.text(), "Acercar (fino)")
        # Con Alt, no con Shift: «+» es Shift+= y Ctrl+Shift+= chocaría con
        # Ctrl++ (agrandar fuente), que Qt toma por ambiguo
        self.assertEqual([s.toString() for s in w._act_zoom_in.shortcuts()], ["Ctrl+Alt+="])
        self.assertEqual(w._act_zoom_out.shortcut().toString(), "Ctrl+Alt+-")
        from PyQt6.QtGui import QAction
        for a in w.findChildren(QAction):
            for sc in a.shortcuts():
                self.assertNotIn(sc.toString(), ("Ctrl+Shift+=", "Ctrl+Shift++", "Ctrl+Shift+-",
                                                 "Ctrl++", "Ctrl+=", "Ctrl+-"), a.text())
        w._act_zoom_in.trigger()
        self.assertAlmostEqual(w0 / self._width(), 1.04, places=6)
        # sin archivo no hace nada ni falla
        w._file_close()
        w.zoom_in_fine()

    def _drag(self, mods, dx=100):
        p = _Ev()
        p.button, p.inaxes, p.dblclick = 1, self.ax, False
        p.x, p.y = 300, 300
        p.modifiers = frozenset(mods)
        p.key = " ".join(mods) or None
        self.w.plot._on_press(p)
        m = _Ev()
        m.x, m.y, m.inaxes = 300 + dx, 300, self.ax
        self.w.plot._on_motion(m)
        r = _Ev()
        r.x, r.y, r.inaxes = 300 + dx, 300, self.ax
        self.w.plot._on_release(r)

    def test_arrastre_fino(self):
        x0 = self.ax.get_xlim()[0]
        self._drag(("shift",))
        d_fine = self.ax.get_xlim()[0] - x0
        self.assertNotEqual(d_fine, 0.0)
        x0 = self.ax.get_xlim()[0]
        self._drag(())
        d_norm = self.ax.get_xlim()[0] - x0
        self.assertAlmostEqual(d_norm / d_fine, 5.0, places=6)
        self.w._cfg["map_fine_divisor"] = 10
        self.w._apply_fine_divisor()
        x0 = self.ax.get_xlim()[0]
        self._drag(("ctrl",))
        self.assertAlmostEqual((self.ax.get_xlim()[0] - x0) / d_fine, 0.5, places=6)

    def test_preferencias(self):
        from app.dialogs.settings_dialog import SettingsDialog
        w = self.w
        d = SettingsDialog(w, cfg=w._cfg)
        self.assertEqual(d.spin_zoom.value(), 20)
        self.assertEqual(d.spin_fine.value(), 5)
        d.spin_zoom.setValue(10)
        d.spin_fine.setValue(10)
        v = d.values()
        self.assertEqual((v["map_zoom_step"], v["map_fine_divisor"]), (10, 10))
        w.apply_settings(v)
        self.assertEqual(w.plot.fine_divisor, 10.0)
        w0 = self._width()
        self._scroll("up", 1)
        self.assertAlmostEqual(w0 / self._width(), 1.10, places=6)
        w1 = self._width()
        self._scroll("up", 1, mods=("ctrl",))
        self.assertAlmostEqual(w1 / self._width(), 1.01, places=6)
        with open(os.path.join(self.tmp, "config.json"), encoding="utf-8") as fh:
            self.assertIn('"map_fine_divisor": 10', fh.read())


if __name__ == "__main__":
    unittest.main()
