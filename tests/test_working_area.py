# -*- coding: utf-8 -*-
"""Working Area de las FIR: proyección estereográfica tangente, contorno,
configuración, selección de FIR de a una desde el menú y dibujo en el mapa."""
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

from app import working_area as W

_app = None


def _qt():
    global _app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    from app.dialogs import glass_dialog
    glass_dialog._apply_dialog_blur = lambda w: None
    return _app


SAEF = dict(code="SAEF", tangent_lat=-34.8, tangent_lon=-58.5, vertex_lat=-42.0, vertex_lon=-66.0,
            width_nm=700.0, height_nm=700.0, radius_km=6371.0, enabled=True)
SACF = dict(code="SACF", tangent_lat=-31.3, tangent_lon=-64.2, vertex_lat=-35.0, vertex_lon=-70.0,
            width_nm=500.0, height_nm=500.0, radius_km=6371.0, enabled=True)


class TestProyeccion(unittest.TestCase):
    def test_tangencia_es_el_origen(self):
        x, y = W.stereo_forward(-34.8, -58.5, -34.8, -58.5, 6371.0)
        self.assertAlmostEqual(float(x), 0.0)
        self.assertAlmostEqual(float(y), 0.0)

    def test_ida_y_vuelta(self):
        for lat, lon in ((-30.123, -55.456), (-45.0, -70.0), (-10.0, -40.0), (-34.8, -58.5)):
            x, y = W.stereo_forward(lat, lon, -34.8, -58.5, 6371.0)
            la, lo = W.stereo_inverse(x, y, -34.8, -58.5, 6371.0)
            self.assertAlmostEqual(float(la), lat, places=9)
            self.assertAlmostEqual(float(lo), lon, places=9)

    def test_ejes_norte_y_este(self):
        """Un punto al norte de la tangencia cae en +y, uno al este en +x."""
        x, y = W.stereo_forward(-33.8, -58.5, -34.8, -58.5, 6371.0)
        self.assertAlmostEqual(float(x), 0.0, places=9)
        self.assertGreater(float(y), 59.0)      # ≈ 60 NM por grado de latitud
        self.assertLess(float(y), 61.0)
        x, y = W.stereo_forward(-34.8, -57.5, -34.8, -58.5, 6371.0)
        self.assertGreater(float(x), 49.0)      # ≈ 60·cos(34,8°) NM por grado de longitud
        self.assertLess(abs(float(y)), 1.0)     # el paralelo se curva apenas (plano conforme)

    def test_radio_conforme(self):
        a = W.WGS84_A_KM
        b = a * (1.0 - W.WGS84_F)
        self.assertAlmostEqual(W.conformal_radius_km(0.0), b, places=3)     # √(M·N) en el ecuador = b
        self.assertAlmostEqual(W.conformal_radius_km(90.0), a / math.sqrt(1.0 - W.WGS84_E2), places=3)
        r = W.conformal_radius_km(-34.8)
        self.assertTrue(6360.0 < r < 6380.0)


class TestWorkingArea(unittest.TestCase):
    def test_esquinas_y_contorno(self):
        wa = W.WorkingArea(**SAEF)
        so, se, ne, no = wa.corners()
        self.assertAlmostEqual(so[0], -42.0, places=9)
        self.assertAlmostEqual(so[1], -66.0, places=9)
        # lados medidos en el plano
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = wa.corners_xy()
        self.assertAlmostEqual(math.hypot(x1 - x0, y1 - y0), 700.0)
        self.assertAlmostEqual(math.hypot(x2 - x1, y2 - y1), 700.0)
        self.assertAlmostEqual(math.hypot(x3 - x0, y3 - y0), 700.0)
        self.assertGreater(ne[0], so[0])        # la esquina NE está más al norte
        self.assertGreater(ne[1], so[1])        # y más al este
        ring = wa.ring(step_nm=5.0)
        self.assertEqual(ring.shape[1], 2)
        self.assertEqual(len(ring), 4 * 140)
        self.assertAlmostEqual(ring[0, 0], -66.0, places=9)
        self.assertAlmostEqual(ring[0, 1], -42.0, places=9)
        self.assertTrue((np.abs(ring[:, 0]) <= 180).all() and (np.abs(ring[:, 1]) <= 90).all())

    def test_contiene(self):
        wa = W.WorkingArea(**SAEF)
        self.assertTrue(wa.contains(-37.0, -60.0))
        self.assertFalse(wa.contains(-20.0, -40.0))
        self.assertTrue(wa.contains(-42.0, -66.0))      # el vértice pertenece
        lon, lat = wa.label_point()
        self.assertTrue(wa.contains(lat, lon))
        bb = wa.bbox()
        self.assertLess(bb[0], -66.0 + 1e-6)
        self.assertLessEqual(bb[2], -42.0 + 1e-6)

    def test_validacion(self):
        self.assertEqual(W.validate_working_area(W.WorkingArea(**SAEF)), [])
        bad = W.WorkingArea(**dict(SAEF, width_nm=0.0))
        self.assertTrue(any("ancho" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, radius_km=5000.0))
        self.assertTrue(any("radio" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, code="SA1F"))
        self.assertTrue(any("código" in e for e in W.validate_working_area(bad)))
        bad = W.WorkingArea(**dict(SAEF, vertex_lat=95.0))
        self.assertTrue(any("latitud" in e for e in W.validate_working_area(bad)))
        far = W.WorkingArea(**dict(SAEF, vertex_lat=60.0, vertex_lon=120.0))
        self.assertTrue(any("90°" in e for e in W.validate_working_area(far)))
        dup = W.validate_working_areas([W.WorkingArea(**SAEF), W.WorkingArea(**SAEF)])
        self.assertTrue(any("repetido" in e for e in dup))

    def test_config_ida_y_vuelta(self):
        was = [W.WorkingArea(**SAEF), W.WorkingArea(**dict(SACF, enabled=False))]
        cfg = {"working_areas": W.working_areas_to_config(was)}
        back = W.working_areas_from_config(cfg)
        self.assertEqual([w.to_dict() for w in back], [w.to_dict() for w in was])
        self.assertEqual(W.find_working_area(back, "sacf").code, "SACF")
        self.assertIsNone(W.find_working_area(back, "SARR"))
        self.assertEqual(W.working_areas_from_config({}), [])
        self.assertEqual(W.working_areas_from_config({"working_areas": [None, 3]}), [])
        self.assertIn("NE", W.describe(was[0]))


class TestVentana(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _qt()
        cls.tmp = tempfile.mkdtemp()
        from app import config
        cls._old_path = config.CONFIG_PATH
        config.CONFIG_PATH = os.path.join(cls.tmp, "config.json")

    @classmethod
    def tearDownClass(cls):
        from app import config
        config.CONFIG_PATH = cls._old_path
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        from app import config
        try:
            os.remove(config.CONFIG_PATH)       # cada test arranca con la configuración por defecto
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

    def test_menu_una_por_una(self):
        w = self.w
        self.assertEqual(len(w._fir_code_actions), 14)
        self.assertFalse(w._cfg["fir_enabled"])
        w.toggle_fir_code("SAEF", True)
        self.assertTrue(w._cfg["fir_enabled"])
        self.assertEqual(w._cfg["fir_active"], ["SAEF"])
        self.assertEqual([r.code for r in w.plot.fir_visible()], ["SAEF"])
        self.assertTrue(w._fir_code_actions["SAEF"].isChecked())
        self.assertFalse(w._fir_code_actions["SACF"].isChecked())
        w.toggle_fir_code("SACF", True)
        self.assertEqual(w._cfg["fir_active"], ["SACF", "SAEF"])
        # una vecina enciende las vecinas
        self.assertFalse(w._cfg["fir_neighbors"])
        w.toggle_fir_code("SUEO", True)
        self.assertTrue(w._cfg["fir_neighbors"])
        self.assertEqual(sorted(r.code for r in w.plot.fir_visible()), ["SACF", "SAEF", "SUEO"])
        w.toggle_fir_code("SAEF", False)
        self.assertEqual(sorted(r.code for r in w.plot.fir_visible()), ["SACF", "SUEO"])
        w.set_fir_codes([])
        self.assertEqual(w.plot.fir_visible(), [])
        w.set_fir_codes(list(w._fir_code_actions))
        self.assertEqual(len(w.plot.fir_visible()), 14)
        w.set_fir_codes(["SARR", "SACF", "SAMF", "SAEF", "SAVF"])
        self.assertEqual(len(w.plot.fir_visible()), 5)

    def test_wa_con_la_fir(self):
        w = self.w
        w._cfg["working_areas"] = [dict(SAEF), dict(SACF, enabled=False)]
        w.set_fir_codes(["SAEF", "SACF"])
        self.assertEqual(w.plot.wa_visible(), [])            # todavía no se pidió
        w.set_wa_show(True)
        self.assertEqual(w.plot.wa_visible(), ["SAEF"])      # SACF está deshabilitada
        self.assertTrue(w.panel.chk_wa.isChecked())
        self.assertTrue(w._act_wa.isChecked())
        w.plot.draw_empty()
        self.assertEqual(len(w.plot._wa_artists), 2)         # contorno + etiqueta
        w.toggle_fir_code("SAEF", False)
        self.assertEqual(w.plot.wa_visible(), [])            # sin la FIR no hay WA
        w.toggle_fir_code("SAEF", True)
        self.assertEqual(w.plot.wa_visible(), ["SAEF"])
        w.panel.chk_wa.setChecked(False)
        self.assertFalse(w._cfg["wa_show"])
        self.assertEqual(w.plot.wa_visible(), [])
        w.set_wa_show(True)
        for key in ("stereo", "spstereo", "mercator", "lambert", "platecarree"):
            w.plot.set_projection(key, np.linspace(-80, -40, 5), np.linspace(-55, -15, 5))
            w.plot.draw_empty()
            self.assertEqual(len(w.plot._wa_artists), 2, key)

    def test_dialogo_working_area(self):
        from app.dialogs import fir_dialog
        from app.dialogs.fir_dialog import FirDialog
        warnings = []
        fir_dialog.QMessageBox.warning = lambda *a, **k: warnings.append(a[2])   # sin modal
        w = self.w
        w._cfg["working_areas"] = [dict(SAEF)]
        d = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        self.assertEqual(d.tabs.tabText(3), "Working Area")
        self.assertEqual(d.wa_table.rowCount(), 1)
        self.assertEqual(d.wa_errors(), [])
        self.assertIn("SAEF", d.lbl_wa_info.text())
        d._wa_add_default()
        self.assertEqual(d.wa_table.rowCount(), 2)
        self.assertEqual(d.wa_table.cellWidget(1, d.W_CODE).text(), "SARR")
        d.wa_table.cellWidget(1, d.W_TLAT).set_value(-27.0)
        d.wa_table.cellWidget(1, d.W_TLON).set_value(-59.0)
        d.wa_table.cellWidget(1, d.W_VLAT).set_value(-31.0)
        d.wa_table.cellWidget(1, d.W_VLON).set_value(-63.0)
        d.wa_table.cellWidget(1, d.W_W).setValue(400.0)
        d.wa_table.cellWidget(1, d.W_H).setValue(450.0)
        d.wa_table.selectRow(1)
        d._wa_conformal()
        self.assertAlmostEqual(d.wa_table.cellWidget(1, d.W_R).value(), W.conformal_radius_km(-27.0), places=3)
        d.chk_wa_show.setChecked(True)
        v = d.values()
        self.assertEqual([x["code"] for x in v["working_areas"]], ["SAEF", "SARR"])
        self.assertEqual(v["working_areas"][1]["width_nm"], 400.0)
        self.assertTrue(v["wa_show"])
        # un ancho inválido bloquea Aplicar
        d.wa_table.cellWidget(1, d.W_W).setValue(0.0)
        self.assertTrue(d.wa_errors())
        d.accept()
        self.assertEqual(d.result(), 0)
        self.assertEqual(len(warnings), 1)
        d.wa_table.cellWidget(1, d.W_W).setValue(400.0)
        d.accept()
        self.assertEqual(d.result(), 1)
        w._cfg.update(d.values())
        w.set_fir_codes(["SARR"])
        self.assertEqual(w.plot.wa_visible(), ["SARR"])
        # borrar la fila elegida
        d2 = FirDialog(w, cfg=w._cfg, regions=w._fir_regions, notes=[], grid_bbox=None)
        d2.wa_table.selectRow(0)
        d2._wa_remove()
        self.assertEqual([x["code"] for x in d2.values()["working_areas"]], ["SARR"])


if __name__ == "__main__":
    unittest.main()
